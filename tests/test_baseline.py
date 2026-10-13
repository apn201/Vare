import httpx
import respx

from vare.pipeline import baseline
from vare.pipeline.trace import Trace

from .conftest import LLM, chat_reply, json_reply, prompt_of


@respx.mock
async def test_baseline_returns_llm_tags(llm):
    route = respx.post(f"{LLM}/chat/completions").mock(
        return_value=json_reply(["Dune Part Two", "#IMAX", "Hans Zimmer", "dune part two"]))
    trace = Trace()
    res = await baseline.run(llm, "Saw Dune: Part Two in IMAX", "youtube", trace)
    assert res.error is None
    assert [t.tag for t in res.tags] == ["Dune Part Two", "IMAX", "Hans Zimmer"]   # '#' stripped, dup dropped
    assert all(t.source == "llm" and t.explanation == "" for t in res.tags)
    assert res.count == 3
    assert "youtube" in prompt_of(route.calls[0].request)
    assert trace.stages[0].stage.startswith("A0")


@respx.mock
async def test_baseline_retries_once_then_reports_error(llm):
    route = respx.post(f"{LLM}/chat/completions").mock(return_value=chat_reply("sorry, no json here"))
    res = await baseline.run(llm, "text", "general", Trace())
    assert route.call_count == 2
    assert res.tags == [] and "no parseable JSON after a retry" in res.error


@respx.mock
async def test_baseline_http_error_is_reported(llm):
    respx.post(f"{LLM}/chat/completions").mock(return_value=httpx.Response(401, json={"error": {"message": "bad key"}}))
    res = await baseline.run(llm, "text", "general", Trace())
    assert "401" in res.error and res.tags == []


async def test_baseline_without_key(settings):
    from dataclasses import replace
    from vare.llm.client import LLMClient
    res = await baseline.run(LLMClient(replace(settings, llm_api_key="")), "t", "general", Trace())
    assert "LLM_API_KEY is not set" in res.error
