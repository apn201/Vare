"""Process-wide LLM and Qloo clients, shared by the web app and the MCP tools.

One set per process, so the Qloo rate pacer and cache are shared too.
"""

from __future__ import annotations

from .config import get_settings
from .llm.client import LLMClient
from .qloo.client import QlooClient

_llm: LLMClient | None = None
_qloo: QlooClient | None = None


def clients() -> tuple[LLMClient, QlooClient]:
    global _llm, _qloo
    if _llm is None or _qloo is None:
        settings = get_settings()
        _llm, _qloo = LLMClient(settings), QlooClient(settings)
    return _llm, _qloo


def set_clients(llm: LLMClient, qloo: QlooClient) -> None:
    """For tests: route the MCP tools to mocked clients."""
    global _llm, _qloo
    _llm, _qloo = llm, qloo


async def close() -> None:
    global _llm, _qloo
    if _llm is not None:
        await _llm.aclose()
    if _qloo is not None:
        await _qloo.aclose()
    _llm = _qloo = None
