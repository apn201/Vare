import respx

from vare.pipeline import generator
from vare.pipeline.trace import Trace
from vare.schema import PoolItem

from .conftest import LLM, json_reply, prompt_of


def pool():
    return [
        PoolItem(tag="Lorde", source="qloo_direct", evidence="Lorde's Melodrama tour", origin="Lorde",
                 qloo_type="urn:entity:artist"),
        PoolItem(tag="indie pop", source="qloo_inferred", evidence="Qloo Insights: associated with Lorde",
                 origin="Lorde", qloo_type="urn:tag:genre:music", affinity=0.9),
        PoolItem(tag="teenager", source="qloo_inferred", evidence="Qloo Insights: associated with Lorde",
                 origin="Lorde", qloo_type="urn:tag:audience:qloo"),
    ]


@respx.mock
async def test_hallucinated_tags_discarded_and_fields_come_from_pool(llm):
    route = respx.post(f"{LLM}/chat/completions").mock(return_value=json_reply([
        {"tag": "lorde", "explanation": "Named in the text."},
        {"tag": "indie pop", "explanation": "Qloo links it to Lorde."},
        {"tag": "Taylor Swift", "explanation": "Invented."},
    ]))
    trace = Trace()
    res = await generator.run(llm, "text", "general", pool(), trace)
    assert [t.tag for t in res.tags] == ["Lorde", "indie pop"]          # pool spelling kept
    assert [t.source for t in res.tags] == ["qloo_direct", "qloo_inferred"]
    assert res.tags[1].evidence.startswith("Qloo Insights")
    reasons = {r["tag"]: r["reason"] for r in trace.stages[0].rejected}
    assert "hallucination guard" in reasons["Taylor Swift"]
    assert "not chosen" in reasons["teenager"]
    assert "- indie pop: Qloo Insights: associated with Lorde (genre:music)" in prompt_of(route.calls[0].request)


@respx.mock
async def test_subject_kept_even_if_model_drops_it(llm):
    items = pool()
    items[0].role = "subject"
    respx.post(f"{LLM}/chat/completions").mock(return_value=json_reply([{"tag": "indie pop", "explanation": "x"}]))
    res = await generator.run(llm, "text", "general", items, Trace())
    assert [t.tag for t in res.tags] == ["Lorde", "indie pop"]


async def test_empty_selection_is_honest(llm):
    res = await generator.run(llm, "text", "general", [], Trace())
    assert res.tags == [] and "nothing to show" in res.error
