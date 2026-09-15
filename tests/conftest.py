from __future__ import annotations

import httpx
import pytest

from uscode_mcp import tools
from uscode_mcp.govinfo import GovInfoClient


@pytest.fixture(autouse=True)
def fresh_currentthrough_memory():
    """The staleness detector remembers each edition's currentthrough per process;
    every test starts cold so one fixture's dates can't seed another's prediction."""
    tools.CURRENTTHROUGH_MEMORY.clear()
    yield
    tools.CURRENTTHROUGH_MEMORY.clear()


@pytest.fixture
def make_client():
    """Factory: build a GovInfoClient whose HTTP layer is an httpx.MockTransport handler."""

    def _make(handler) -> GovInfoClient:
        return GovInfoClient(
            api_key="test-key",
            http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    return _make
