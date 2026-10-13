"""End to end through FastAPI with respx standing in for the LLM and Qloo."""

import json

import httpx
import pytest
import respx

import vare.api.generate as gen_mod
from vare.main import app

from .conftest import LLM, LLM_KEY, QLOO, QLOO_KEY, chat_reply, json_reply, prompt_of

TEXT = "Billie Eilish at the O2 last night. Haven't felt a room like that since Lorde's Melodrama tour."


def llm_handler(request):
    p = prompt_of(request)
    if "You are a tag generator" in p:
        return json_reply(["Billie Eilish", "Lorde", "concert"])
    if "work out what it is actually about" in p:
        return json_reply({"subject": {"name": "Billie Eilish", "qloo_type": "urn:entity:artist"},
                           "domains": ["music"], "references": [
            {"name": "Billie Eilish", "qloo_type": "urn:entity:artist", "role": "subject", "evidence": "Billie Eilish", "confidence": "high"},
            {"name": "Lorde", "qloo_type": "urn:entity:artist", "role": "comparison", "evidence": "Lorde's Melodrama tour", "confidence": "high"},
            {"name": "FINNEAS", "qloo_type": "urn:entity:artist", "role": "creator", "evidence": "brother and producer", "confidence": "high", "implied": True},
        ]})
    if "You are choosing tags" in p:
        return json_reply([{"tag": "Whisper Pop", "explanation": "Qloo profile."},
                           {"tag": "FINNEAS", "explanation": "Implied, confirmed."},
                           {"tag": "indie pop", "explanation": "Qloo links it to Billie Eilish."},
                           {"tag": "Lorde", "explanation": "Sneaked back in."}])
    if "adjacent topics" in p and "Cultural signals" in p:
        return json_reply([{"topic": "Bedroom pop's arena era", "connection": "c", "cultural_basis": "indie pop"}] * 3)
    if "adjacent topics" in p:
        return json_reply([{"topic": "Pop concerts", "connection": "c", "cultural_basis": "b"}])
    return chat_reply("?")


def qloo_handler(request):
    path, params = request.url.path, request.url.params
    if path == "/search":
        q = params["query"]
        return httpx.Response(200, json={"results": [{"name": q, "entity_id": f"ID-{q}", "types": ["urn:entity:artist"]}]})
    if path == "/entities":
        return httpx.Response(200, json={"results": [{"entity_id": params["entity_ids"], "name": "Billie Eilish", "tags": [
            {"tag_id": "t1", "name": "Whisper Pop", "type": "urn:tag:style:qloo"},
            {"tag_id": "t2", "name": "Youthful", "type": "urn:tag:audience:qloo"}]}]})
    if path == "/v2/insights":
        if params["filter.type"] == "urn:tag":
            return httpx.Response(200, json={"results": {"tags": [
                {"tag_id": "urn:tag:genre:music:indie_pop", "name": "indie pop", "subtype": "urn:tag:genre:music"}]}})
        return httpx.Response(200, json={"results": {"entities": [
            {"name": "Olivia Rodrigo", "entity_id": "OR", "subtype": "urn:entity:artist"}]}})
    return httpx.Response(404, json={"error": {"message": "nope"}})


@pytest.fixture
async def client(settings, llm, qloo, monkeypatch):
    monkeypatch.setattr(gen_mod, "get_settings", lambda: settings)
    app.state.llm, app.state.qloo = llm, qloo
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


@respx.mock
async def test_tags_mode_two_columns(client):
    respx.post(f"{LLM}/chat/completions").mock(side_effect=llm_handler)
    respx.get(url__startswith=QLOO).mock(side_effect=qloo_handler)
    r = await client.post("/api/generate", json={"text": TEXT, "destination": "instagram", "advanced": True})
    assert r.status_code == 200
    d = r.json()
    a, b = d["comparison"]["baseline"], d["comparison"]["experimental"]
    assert a["error"] is None and b["error"] is None
    tags = {t["tag"]: t for t in b["tags"]}
    # subject kept by code although the model did not pick it; the comparison
    # (Lorde) stays out even though the model tried to return it
    assert list(tags) == ["Billie Eilish", "Whisper Pop", "FINNEAS", "indie pop"]
    assert tags["Whisper Pop"]["source"] == "qloo_profile"
    assert tags["FINNEAS"]["source"] == "qloo_direct" and "not named in the text" in tags["FINNEAS"]["evidence"]
    assert tags["indie pop"]["source"] == "qloo_inferred"
    assert "Youthful" not in tags                       # audience label dropped from profile
    assert d["comparison"]["overlap_count"] == 1       # Billie Eilish
    assert d["comparison"]["novelty_count"] == 3
    stages = [s["stage"] for s in d["trace"]]
    assert stages[0].startswith("A0") and any(s.startswith("B4") for s in stages)


@respx.mock
async def test_trace_absent_unless_advanced(client):
    respx.post(f"{LLM}/chat/completions").mock(side_effect=llm_handler)
    respx.get(url__startswith=QLOO).mock(side_effect=qloo_handler)
    r = await client.post("/api/generate", json={"text": TEXT})
    assert r.json()["trace"] is None


@respx.mock
async def test_topics_mode(client):
    respx.post(f"{LLM}/chat/completions").mock(side_effect=llm_handler)
    respx.get(url__startswith=QLOO).mock(side_effect=qloo_handler)
    r = await client.post("/api/generate", json={"text": TEXT, "mode": "topics", "advanced": True})
    d = r.json()["comparison"]
    assert len(d["experimental"]["topics"]) == 3 and d["experimental"]["tags"] is None, d["experimental"]
    assert len(d["baseline"]["topics"]) == 1


@respx.mock
async def test_one_path_failing_does_not_hide_the_other(client):
    def handler(request):
        if "work out what it is actually about" in prompt_of(request):
            return httpx.Response(500, json={"error": {"message": "upstream down"}})
        return llm_handler(request)
    respx.post(f"{LLM}/chat/completions").mock(side_effect=handler)
    r = await client.post("/api/generate", json={"text": TEXT})
    d = r.json()["comparison"]
    assert r.status_code == 200
    assert d["baseline"]["count"] == 3
    assert "extraction failed" in d["experimental"]["error"]


@respx.mock
async def test_no_secret_in_response_even_when_echoed(client):
    """Upstreams that echo the key into an error body must not leak it."""
    def handler(request):
        if "You are a tag generator" in prompt_of(request):
            return httpx.Response(400, json={"error": {"message": f"invalid key {LLM_KEY}"}})
        return llm_handler(request)

    def qhandler(request):
        if request.url.path == "/v2/insights":
            return httpx.Response(403, json={"error": {"message": f"key {QLOO_KEY} not allowed"}})
        return qloo_handler(request)

    respx.post(f"{LLM}/chat/completions").mock(side_effect=handler)
    respx.get(url__startswith=QLOO).mock(side_effect=qhandler)
    r = await client.post("/api/generate", json={"text": TEXT, "advanced": True})
    body = r.text
    assert LLM_KEY not in body and QLOO_KEY not in body
    assert "REDACTED" in body
    for stage in r.json()["trace"]:
        assert not any(k.lower() in ("x-api-key", "authorization", "api_key") for k in (stage.get("params") or {}))


async def test_validation_rejects_empty_and_long(client):
    assert (await client.post("/api/generate", json={"text": "   "})).status_code == 422
    assert (await client.post("/api/generate", json={"text": "x" * 4001})).status_code == 422


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200 and set(r.json()) >= {"status", "qloo_key_set", "llm_key_set"}
    assert QLOO_KEY not in r.text and LLM_KEY not in r.text


async def test_index_served(client):
    r = await client.get("/")
    assert r.status_code == 200 and "Väre" in r.text
