"""Shared test fixtures: canned GovInfo response payloads and builders.

These are mocked shapes for unit-testing the server's contracts, modeled on the
response shapes documented in documentation/20-govinfo-api.md and 30-search.md.
They are test fixtures, not evidence about the live service.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

API = "https://api.govinfo.gov"

SECTION_HTML = """\
<!-- documentid:USCODE-2024-title17-chap1-sec107 currentthrough:20250106 itempath:/2024/title17/chap1/sec107 -->
<html><head><title>17 USC 107</title><style>p { margin: 0 }</style></head><body>
<h3>&sect;107. Limitations on exclusive rights: Fair use</h3>
<p>Notwithstanding the provisions of sections 106 and 106A, the fair use of a copyrighted work is not an infringement of copyright.</p>
<p>(Pub. L. 94-553, title I, &sect;101, Oct. 19, 1976, 90 Stat. 2546; Pub. L. 101-650, title VI, &sect;607, Dec. 1, 1990, 104 Stat. 5132.)</p>
<h4>Statutory Notes and Related Subsidiaries</h4>
<p>Effective date note text lives here and must never be dropped.</p>
</body></html>
"""

SECTION_HTML_NO_CURRENTTHROUGH = SECTION_HTML.replace("currentthrough:20250106 ", "")

PLAW_HTML = """\
<html><body>
<h2>Public Law 118-31</h2>
<p>An Act to authorize appropriations for fiscal year 2024 for military activities of the Department of Defense.</p>
<p>SEC. 2. This Act may be cited as the NDAA fixture.</p>
</body></html>
"""

PLAW_USLM = """<?xml version="1.0" encoding="UTF-8"?>
<uslm xmlns="http://xml.house.gov/schemas/uslm/1.0"><main><section>Sec. 1.</section></main></uslm>
"""


def usc_hit(
    package_id: str = "USCODE-2024-title17",
    granule_id: str = "USCODE-2024-title17-chap1-sec107",
    date_issued: str = "2025-01-06",
    title: str = "107. Limitations on exclusive rights: Fair use",
) -> dict[str, Any]:
    return {
        "title": title,
        "packageId": package_id,
        "granuleId": granule_id,
        "dateIssued": date_issued,
        "collectionCode": "USCODE",
        "lastModified": "2025-03-01T00:00:00Z",
        "download": {
            "txtLink": f"{API}/packages/{package_id}/granules/{granule_id}/htm",
            "pdfLink": f"{API}/packages/{package_id}/granules/{granule_id}/pdf",
            "modsLink": f"{API}/packages/{package_id}/granules/{granule_id}/mods",
        },
        "resultLink": f"{API}/packages/{package_id}/granules/{granule_id}/summary",
    }


def plaw_hit(package_id: str = "PLAW-118publ31", date_issued: str = "2023-12-22") -> dict[str, Any]:
    return {
        "title": "National Defense Authorization Act for Fiscal Year 2024",
        "packageId": package_id,
        "granuleId": None,
        "dateIssued": date_issued,
        "collectionCode": "PLAW",
        "lastModified": "2024-01-15T00:00:00Z",
        "download": {
            "txtLink": f"{API}/packages/{package_id}/htm",
            "pdfLink": f"{API}/packages/{package_id}/pdf",
        },
        "resultLink": f"{API}/packages/{package_id}/summary",
    }


def plaw_summary(package_id: str = "PLAW-118publ31", uslm: bool = True) -> dict[str, Any]:
    download = {
        "txtLink": f"{API}/packages/{package_id}/htm",
        "pdfLink": f"{API}/packages/{package_id}/pdf",
        "modsLink": f"{API}/packages/{package_id}/mods",
        "premisLink": f"{API}/packages/{package_id}/premis",
        "zipLink": f"{API}/packages/{package_id}/zip",
    }
    if uslm:
        download["uslmLink"] = f"{API}/packages/{package_id}/uslm"
    return {
        "packageId": package_id,
        "dateIssued": "2023-12-22",
        "lastModified": "2024-01-15T00:00:00Z",
        "download": download,
        "references": [{"contents": [{"title": "42", "sections": [{"section": "2210"}]}]}],
    }


def search_response(hits: list[dict[str, Any]], count: int | None = None, offset_mark: str = "AoE=") -> dict[str, Any]:
    return {"count": count if count is not None else len(hits), "offsetMark": offset_mark, "results": hits}


def json_response(payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers)


def request_body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content.decode("utf-8"))
