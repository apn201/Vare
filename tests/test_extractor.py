import respx

from vare.pipeline import extractor
from vare.pipeline.trace import Trace

from .conftest import LLM, json_reply


def ref(name, t, conf="high"):
    return {"name": name, "qloo_type": t, "evidence": name, "confidence": conf, "ambiguous": False}


@respx.mock
async def test_extractor_parses_domains_and_references(llm):
    respx.post(f"{LLM}/chat/completions").mock(return_value=json_reply({
        "domains": ["movie", "music", "nonsense"],
        "references": [ref("Dune: Part Two", "urn:entity:movie"), ref("Hans Zimmer", "urn:entity:artist"),
                       ref("cyberpunk", "genre"), ref("weird", "urn:entity:spaceship")],
    }))
    trace = Trace()
    cands, domains, err = await extractor.run(llm, "text", trace)
    assert err is None
    assert domains == ["urn:entity:movie", "urn:entity:artist"]
    assert [c.qloo_type for c in cands] == ["urn:entity:movie", "urn:entity:artist", "genre", "none"]
    rejected = trace.stages[0].rejected
    assert any("unknown domain" in r["reason"] for r in rejected)
    assert any("unknown qloo_type" in r["reason"] for r in rejected)


@respx.mock
async def test_extractor_accepts_bare_array(llm):
    respx.post(f"{LLM}/chat/completions").mock(return_value=json_reply([ref("Lorde", "urn:entity:artist")]))
    cands, domains, err = await extractor.run(llm, "text", Trace())
    assert [c.name for c in cands] == ["Lorde"] and domains == []


def test_low_confidence_dropped_only_when_enough_remain():
    cands, _ = extractor.parse_candidates([ref("a", "genre"), ref("b", "genre"), ref("c", "genre"), ref("d", "genre", "low")])
    kept, low = extractor.drop_low_confidence(cands)
    assert [c.name for c in kept] == ["a", "b", "c"] and [c.name for c in low] == ["d"]
    cands, _ = extractor.parse_candidates([ref("a", "genre"), ref("d", "genre", "low")])
    kept, low = extractor.drop_low_confidence(cands)
    assert len(kept) == 2 and low == []


def test_roles_subject_and_implied_limits():
    parsed = {"subject": {"name": "The Substance", "qloo_type": "urn:entity:movie"}, "references": [
        {"name": "Kubrick", "qloo_type": "urn:entity:director", "role": "comparison"},
        {"name": "Coralie Fargeat", "qloo_type": "urn:entity:director", "role": "creator", "implied": True},
        {"name": "Demi Moore", "qloo_type": "urn:entity:actor", "role": "cast", "implied": True},
        {"name": "Margaret Qualley", "qloo_type": "urn:entity:actor", "role": "cast", "implied": True},
        {"name": "Icarus", "qloo_type": "concept", "role": "allusion", "implied": True},
    ]}
    cands, rejected = extractor.parse_candidates(parsed["references"])
    cands = extractor.apply_subject(parsed, cands)
    assert cands[0].name == "The Substance" and cands[0].role == "subject"
    assert [c.name for c in cands if c.implied] == ["Coralie Fargeat", "Demi Moore"]
    reasons = " ".join(r["reason"] for r in rejected)
    assert "more than 2 implied" in reasons and "implied allusion not allowed" in reasons
