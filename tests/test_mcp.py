"""The MCP tools, with respx standing in for Qloo and the LLM."""

import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError

import vare.mcp_server as mcp_mod
from vare import runtime
from vare.main import app
from vare.mcp_server import mcp

from .conftest import LLM, LLM_KEY, QLOO, QLOO_KEY
from .test_api import TEXT, llm_handler, qloo_handler


@pytest.fixture(autouse=True)
def mocked_clients(llm, qloo, settings, monkeypatch):
    runtime.set_clients(llm, qloo)
    monkeypatch.setattr(mcp_mod, "get_settings", lambda: settings)
    yield
    runtime.set_clients(None, None)


def search_reply(*items):
    return httpx.Response(200, json={"results": [{"name": n, "entity_id": i, "types": [t]} for n, i, t in items]})


async def test_tools_listed_read_only():
    tools = {t.name: t for t in await mcp.list_tools()}
    assert set(tools) == {"create_tags", "suggest_topics", "qloo_profile", "qloo_related"}
    assert all(t.annotations.read_only_hint for t in tools.values())


@respx.mock
async def test_qloo_profile_groups_descriptive_kinds():
    respx.get(f"{QLOO}/search").mock(return_value=search_reply(("The Bear", "TB", "urn:entity:tv_show")))
    respx.get(f"{QLOO}/entities").mock(return_value=httpx.Response(200, json={"results": [{
        "entity_id": "TB", "name": "The Bear",
        "tags": [{"tag_id": "1", "name": "Culinary drama", "type": "urn:tag:subgenre:qloo"},
                 {"tag_id": "2", "name": "Grief", "type": "urn:tag:theme:qloo"},
                 {"tag_id": "3", "name": "Two word title", "type": "urn:tag:keyword:media"},
                 {"tag_id": "4", "name": "Foodie", "type": "urn:tag:audience:qloo"}],
        "references": [{"entity_id": "J", "name": "Jeremy Allen White", "type": "urn:entity:actor"}]}]}))
    res = await mcp.call_tool("qloo_profile", {"name": "The Bear", "entity_type": "tv_show"})
    out = res.structured_content
    assert out["found"] and out["entity"]["qloo_id"] == "TB"
    assert out["tags_by_kind"] == {"subgenre": ["Culinary drama"], "theme": ["Grief"]}
    assert out["cast"] == ["Jeremy Allen White"]


@respx.mock
async def test_qloo_profile_not_found_lists_candidates():
    respx.get(f"{QLOO}/search").mock(return_value=search_reply(("The Bears of Alaska", "X", "urn:entity:tv_show")))
    res = await mcp.call_tool("qloo_profile", {"name": "The Bear", "entity_type": "tv_show"})
    out = res.structured_content
    assert not out["found"] and out["candidates"][0].startswith("The Bears of Alaska")


@respx.mock
async def test_qloo_related_movies():
    respx.get(f"{QLOO}/search").mock(return_value=search_reply(("The Substance", "S", "urn:entity:movie")))
    route = respx.get(f"{QLOO}/v2/insights").mock(return_value=httpx.Response(200, json={"results": {"entities": [
        {"name": "Heretic", "entity_id": "H", "subtype": "urn:entity:movie", "query": {"affinity": 0.92}}]}}))
    res = await mcp.call_tool("qloo_related", {"name": "The Substance", "entity_type": "movie", "related_type": "movie"})
    out = res.structured_content
    assert out["related"] == [{"name": "Heretic", "type": "urn:entity:movie", "affinity": 0.92}]
    assert route.calls[0].request.url.params["filter.type"] == "urn:entity:movie"


@respx.mock
async def test_create_tags_returns_only_the_vare_tags():
    llm_route = respx.post(f"{LLM}/chat/completions").mock(side_effect=llm_handler)
    respx.get(url__startswith=QLOO).mock(side_effect=qloo_handler)
    res = await mcp.call_tool("create_tags", {"text": TEXT, "destination": "instagram"})
    out = res.structured_content
    assert [t["tag"] for t in out["tags"]] == ["Billie Eilish", "Whisper Pop", "FINNEAS", "indie pop"]
    assert out["tags"][1]["source"] == "qloo_profile"
    assert out["formatted"] == "#BillieEilish #WhisperPop #FINNEAS #IndiePop"
    assert out["note"] is None
    # no conventional baseline in the service: extract + choose only
    prompts = [c.request.content.decode() for c in llm_route.calls]
    assert not any("You are a tag generator" in p for p in prompts)
    assert LLM_KEY not in str(out) and QLOO_KEY not in str(out)


@respx.mock
async def test_create_tags_no_cultural_subject_says_so():
    from .conftest import json_reply
    respx.post(f"{LLM}/chat/completions").mock(return_value=json_reply({"subject": None, "domains": [], "references": []}))
    res = await mcp.call_tool("create_tags", {"text": "Great Q3, team. Onwards to Q4!"})
    out = res.structured_content
    assert out["tags"] == [] and "no cultural references" in out["note"]


@respx.mock
async def test_suggest_topics():
    respx.post(f"{LLM}/chat/completions").mock(side_effect=llm_handler)
    respx.get(url__startswith=QLOO).mock(side_effect=qloo_handler)
    res = await mcp.call_tool("suggest_topics", {"text": TEXT})
    out = res.structured_content
    assert len(out["topics"]) == 3 and out["topics"][0]["cultural_basis"]


async def test_create_tags_rejects_empty_text():
    with pytest.raises(ToolError, match="empty"):
        await mcp.call_tool("create_tags", {"text": "   "})


async def test_http_endpoint():
    """POST /mcp on the FastAPI app, as an agent would. One test, because the
    MCP session manager can only be started once per process."""
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    async with mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as c:
            init = await c.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "0"}}})
            assert init.status_code == 200, init.text
            assert init.json()["result"]["serverInfo"]["name"] == "vare"
            listed = await c.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            assert {t["name"] for t in listed.json()["result"]["tools"]} == {"create_tags", "suggest_topics", "qloo_profile", "qloo_related"}
        # DNS-rebinding protection: an unknown Host is refused
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://evil.example") as c:
            r = await c.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
            assert r.status_code in (403, 421)
