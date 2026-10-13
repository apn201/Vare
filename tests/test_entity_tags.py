import httpx
import respx

from vare.pipeline import entity_tags
from vare.pipeline.trace import Trace
from vare.schema import Candidate

from .conftest import QLOO


def insight_tags(*names):
    return httpx.Response(200, json={"success": True, "results": {"tags": [
        {"tag_id": f"urn:tag:genre:music:{n}", "name": n, "subtype": "urn:tag:genre:music", "query": {"affinity": 0.9}}
        for n in names]}})


def cand(name, rtype, kind="entity", parent=None):
    return Candidate(name=name, qloo_type=rtype, qloo_id=f"ID-{name}", qloo_name=name,
                     qloo_resolved_type=rtype, qloo_kind=kind, qloo_parent_type=parent)


@respx.mock
async def test_artist_tags_scoped_to_artist(qloo):
    route = respx.get(f"{QLOO}/v2/insights").mock(return_value=insight_tags("indie pop", "electropop"))
    [c] = await entity_tags.run(qloo, [cand("Lorde", "urn:entity:artist")], Trace())
    params = route.calls[0].request.url.params
    assert params["filter.type"] == "urn:tag"
    assert params["filter.parents.types"] == "urn:entity:artist"
    assert params["signal.interests.entities"] == "ID-Lorde"
    assert [a.name for a in c.qloo_associations] == ["indie pop", "electropop"]
    assert [a.rank for a in c.qloo_associations] == [0, 1]


@respx.mock
async def test_venue_skipped_when_text_is_not_about_places(qloo):
    route = respx.get(f"{QLOO}/v2/insights").mock(return_value=insight_tags("x"))
    trace = Trace()
    [c] = await entity_tags.run(qloo, [cand("The O2", "urn:entity:place")], trace, domains=["urn:entity:artist"])
    assert route.call_count == 0 and c.qloo_associations == []
    assert any("skipped" in s.stage for s in trace.stages)


@respx.mock
async def test_person_scoped_by_text_domain(qloo):
    route = respx.get(f"{QLOO}/v2/insights").mock(return_value=insight_tags("drama"))
    await entity_tags.run(qloo, [cand("Jeremy Allen White", "urn:entity:person")], Trace(), domains=["urn:entity:tv_show"])
    assert route.calls[0].request.url.params["filter.parents.types"] == "urn:entity:tv_show"


@respx.mock
async def test_tag_signal_uses_tags_param(qloo):
    route = respx.get(f"{QLOO}/v2/insights").mock(return_value=insight_tags("synthwave"))
    await entity_tags.run(qloo, [cand("cyberpunk", "urn:tag:genre:media", kind="tag", parent="urn:entity:movie")], Trace())
    p = route.calls[0].request.url.params
    assert p["signal.interests.tags"] == "ID-cyberpunk" and "signal.interests.entities" not in p


@respx.mock
async def test_429_retried_once_then_error(qloo):
    route = respx.get(f"{QLOO}/v2/insights").mock(return_value=httpx.Response(429, json={"error_msg": "Rate limit exceeded"}))
    [c] = await entity_tags.run(qloo, [cand("Lorde", "urn:entity:artist")], Trace())
    assert route.call_count == 2
    assert c.qloo_associations == [] and "429" in c.error


@respx.mock
async def test_subject_profile_keeps_descriptive_kinds_only(qloo):
    respx.get(f"{QLOO}/v2/insights").mock(return_value=insight_tags())
    respx.get(f"{QLOO}/entities").mock(return_value=httpx.Response(200, json={"results": [{
        "entity_id": "ID-The Bear", "name": "The Bear", "tags": [
            {"tag_id": "k1", "name": "Two word title", "type": "urn:tag:keyword:media"},
            {"tag_id": "a1", "name": "Foodie", "type": "urn:tag:audience:qloo"},
            {"tag_id": "s1", "name": "Kitchen operational realism", "type": "urn:tag:style:qloo"},
            {"tag_id": "g1", "name": "Culinary drama", "type": "urn:tag:subgenre:qloo"},
            {"tag_id": "g2", "name": "Culinary drama", "type": "urn:tag:subgenre:qloo"},
        ]}]}))
    c = cand("The Bear", "urn:entity:tv_show")
    c.role = "subject"
    await entity_tags.run(qloo, [c], Trace())
    prof = [a.name for a in c.qloo_associations if a.kind == "profile"]
    assert prof == ["Culinary drama", "Kitchen operational realism"]


@respx.mock
async def test_comparison_not_expanded(qloo):
    route = respx.get(f"{QLOO}/v2/insights").mock(return_value=insight_tags("x"))
    c = cand("Limitless", "urn:entity:movie")
    c.role = "comparison"
    await entity_tags.run(qloo, [c], Trace())
    assert route.call_count == 0


@respx.mock
async def test_cuisine_not_expanded(qloo):
    route = respx.get(f"{QLOO}/v2/insights").mock(return_value=insight_tags("Of Ramen"))
    c = cand("ramen", "urn:tag:genre:place", kind="tag", parent="urn:entity:place")
    c.qloo_type = "cuisine"
    trace = Trace()
    await entity_tags.run(qloo, [c], trace)
    assert route.call_count == 0 and any("cuisine" in str(s.response_summary) for s in trace.stages)


@respx.mock
async def test_cast_confirmed_from_subject_profile(qloo):
    respx.get(f"{QLOO}/v2/insights").mock(return_value=insight_tags())
    respx.get(f"{QLOO}/entities").mock(return_value=httpx.Response(200, json={"results": [{
        "entity_id": "ID-Heat", "name": "Heat", "tags": [],
        "references": [{"entity_id": "AP", "name": "Al Pacino", "type": "urn:entity:actor"}]}]}))
    subject = cand("Heat", "urn:entity:movie")
    subject.role = "subject"
    pacino = Candidate(name="Al Pacino", qloo_type="urn:entity:actor", role="cast", unresolved=True)
    await entity_tags.run(qloo, [subject, pacino], Trace())
    assert pacino.qloo_id == "AP" and pacino.resolved and not pacino.unresolved
