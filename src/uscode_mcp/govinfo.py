"""Thin async client for api.govinfo.gov.

Design constraints from documentation/20-govinfo-api.md and 40-tools.md:

- Auth is the ``X-Api-Key`` request header ONLY (R7, O22), read from
  ``GOVINFO_API_KEY``. The key never travels in a URL: the spec's error contracts
  surface upstream URLs verbatim, so header transport keeps every URL the server
  builds, logs, or surfaces key-free by construction.
- Three distinct outcomes, never collapsed: callers get the raw HTTP status,
  headers, and body of every response so the tool layer can distinguish success,
  upstream failure, and rate-limiting (429 with x-ratelimit-*/Retry-After).
- Download links are data: :meth:`GovInfoClient.fetch` takes URLs verbatim from
  search results and summaries; this module never constructs granule/download URLs.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.govinfo.gov"
API_KEY_ENV_VAR = "GOVINFO_API_KEY"
_RATE_LIMIT_HEADERS = ("x-ratelimit-limit", "x-ratelimit-remaining", "retry-after")


class GovInfoTransportError(Exception):
    """Network-level failure: no HTTP response was received at all."""


class GovInfoURLPolicyError(Exception):
    """An upstream-provided URL did not match the configured API origin."""

    def __init__(self, url: str, source_field: str) -> None:
        self.url = url
        self.source_field = source_field
        super().__init__(
            f"refused URL {url!r} from upstream field {source_field!r}: it does not match the configured "
            "GovInfo API origin; no request was made"
        )


def _is_loopback(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _validated_base_url(base_url: str) -> tuple[str, tuple[str, str, int | None]]:
    try:
        parsed = httpx.URL(base_url.rstrip("/"))
    except httpx.InvalidURL as exc:
        raise ValueError(f"base_url is not a valid URL: {base_url!r}") from exc
    if not parsed.host or parsed.username or parsed.password:
        raise ValueError("base_url must be an absolute URL without userinfo")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and _is_loopback(parsed.host)):
        raise ValueError("base_url must use https; http is allowed only for a loopback test origin")
    return str(parsed).rstrip("/"), (parsed.scheme, parsed.host.casefold(), parsed.port)


@dataclass
class UpstreamResponse:
    """An HTTP response from GovInfo, carrying everything the outcome contract needs."""

    status: int
    headers: dict[str, str]
    text: str
    url: str  # key-free by construction: the key travels only in the X-Api-Key header (R7)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def rate_limited(self) -> bool:
        return self.status == 429

    def json(self) -> Any:
        return json.loads(self.text)

    def rate_limit_info(self) -> dict[str, str]:
        return {k: v for k, v in self.headers.items() if k in _RATE_LIMIT_HEADERS}


class GovInfoClient:
    """Async GovInfo API client. Returns :class:`UpstreamResponse` for every HTTP
    response; raises :class:`GovInfoTransportError` only when no response arrived."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        http: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError(f"a GovInfo API key is required (set {API_KEY_ENV_VAR})")
        self._api_key = api_key
        self._base_url, self._allowed_origin = _validated_base_url(base_url)
        self._http = http if http is not None else httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        source_field: str,
        json_body: dict[str, Any] | None = None,
    ) -> UpstreamResponse:
        # R18a: validate at the single egress seam, before attaching the key.
        try:
            parsed = httpx.URL(url)
        except httpx.InvalidURL as exc:
            raise GovInfoURLPolicyError(url, source_field) from exc
        origin = (parsed.scheme, (parsed.host or "").casefold(), parsed.port)
        if parsed.username or parsed.password or origin != self._allowed_origin:
            raise GovInfoURLPolicyError(url, source_field)
        try:
            response = await self._http.request(
                method,
                url,
                headers={"X-Api-Key": self._api_key},
                json=json_body,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise GovInfoTransportError(f"{method} {url}: {type(exc).__name__}: {exc}") from exc
        return UpstreamResponse(
            status=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            text=response.text,
            url=url,
        )

    async def search(self, body: dict[str, Any]) -> UpstreamResponse:
        """POST /search with a govinfo search request body."""
        return await self._request("POST", f"{self._base_url}/search", source_field="base_url", json_body=body)

    async def package_summary(self, package_id: str) -> UpstreamResponse:
        return await self._request(
            "GET", f"{self._base_url}/packages/{package_id}/summary", source_field="base_url"
        )

    async def granule_summary(self, package_id: str, granule_id: str) -> UpstreamResponse:
        return await self._request(
            "GET",
            f"{self._base_url}/packages/{package_id}/granules/{granule_id}/summary",
            source_field="base_url",
        )

    async def fetch(self, url: str, source_field: str) -> UpstreamResponse:
        """GET a download link taken verbatim from a search result or summary."""
        return await self._request("GET", url, source_field=source_field)


def client_from_env() -> GovInfoClient:
    """Build a client from the GOVINFO_API_KEY environment variable, failing loudly.

    The primary guard against a keyless server is at startup in ``__main__`` — the
    server exits before serving anything (R10 third amendment, from F31). This is the
    backstop for embedders that build a client directly. Blank counts as absent.
    """
    api_key = os.environ.get(API_KEY_ENV_VAR, "").strip()
    if not api_key:
        raise RuntimeError(
            f"{API_KEY_ENV_VAR} is not set (or is blank). "
            "Put it in the repo-root .env (gitignored) or the environment."
        )
    return GovInfoClient(api_key=api_key)
