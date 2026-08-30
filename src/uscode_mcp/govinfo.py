"""Thin async client for api.govinfo.gov.

Design constraints from documentation/20-govinfo-api.md and 40-tools.md:

- Auth is the ``api_key`` query parameter (observed working, O1-O19), read from
  ``GOVINFO_API_KEY``; the key is never logged and never echoed back in URLs.
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
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.govinfo.gov"
API_KEY_ENV_VAR = "GOVINFO_API_KEY"
_RATE_LIMIT_HEADERS = ("x-ratelimit-limit", "x-ratelimit-remaining", "retry-after")


class GovInfoTransportError(Exception):
    """Network-level failure: no HTTP response was received at all."""


@dataclass
class UpstreamResponse:
    """An HTTP response from GovInfo, carrying everything the outcome contract needs."""

    status: int
    headers: dict[str, str]
    text: str
    url: str  # the request URL *without* the api_key parameter

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
        self._base_url = base_url.rstrip("/")
        self._http = http if http is not None else httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, url: str, json_body: dict[str, Any] | None = None) -> UpstreamResponse:
        # copy_merge_params preserves any query already on a download link taken
        # verbatim from a search result or summary; passing params= would replace it.
        full_url = httpx.URL(url).copy_merge_params({"api_key": self._api_key})
        try:
            response = await self._http.request(method, full_url, json=json_body)
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
        return await self._request("POST", f"{self._base_url}/search", json_body=body)

    async def package_summary(self, package_id: str) -> UpstreamResponse:
        return await self._request("GET", f"{self._base_url}/packages/{package_id}/summary")

    async def granule_summary(self, package_id: str, granule_id: str) -> UpstreamResponse:
        return await self._request("GET", f"{self._base_url}/packages/{package_id}/granules/{granule_id}/summary")

    async def fetch(self, url: str) -> UpstreamResponse:
        """GET a download link taken verbatim from a search result or summary."""
        return await self._request("GET", url)


def client_from_env() -> GovInfoClient:
    """Build a client from the GOVINFO_API_KEY environment variable, failing loudly."""
    api_key = os.environ.get(API_KEY_ENV_VAR, "")
    if not api_key:
        raise RuntimeError(
            f"{API_KEY_ENV_VAR} is not set. Put it in the repo-root .env (gitignored) or the environment."
        )
    return GovInfoClient(api_key=api_key)
