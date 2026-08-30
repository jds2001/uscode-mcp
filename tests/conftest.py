from __future__ import annotations

import httpx
import pytest

from uscode_mcp.govinfo import GovInfoClient


@pytest.fixture
def make_client():
    """Factory: build a GovInfoClient whose HTTP layer is an httpx.MockTransport handler."""

    def _make(handler) -> GovInfoClient:
        return GovInfoClient(
            api_key="test-key",
            http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    return _make
