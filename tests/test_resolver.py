import httpx
import respx

from vare.pipeline import resolver
from vare.pipeline.trace import Trace
from vare.qloo.models import Tag
from vare.schema import Candidate

from .conftest import QLOO, QLOO_KEY


def search(*items):
    return httpx.Response(200, json={"results": [{"name": n, "entity_id": i, "types": [t]} for n, i, t in items]})


def tags(*items):
    return httpx.Response(200, json={"success": True, "results": {"tags": [
        {"id": i, "name": n, "type": t, "parents": [{"type": p} for p in ps]} for n, i, t, ps in items]}})


@respx.mock
async def test_entity_resolves_with_typed_search(qloo):
    route = respx.get(f"{QLOO}/search").mock(return_value=search(("Lorde", "E1", "urn:entity:artist")))
    [c] = await resolver.run(qloo, [Candidate(name="Lorde", qloo_type="urn:entity:artist")], Trace())
    assert c.qloo_id == "E1" and c.qloo_kind == "entity"
    req = route.calls[0].request
    assert req.url.params["types"] == "urn:entity:artist"
    assert req.headers["X-Api-Key"] == QLOO_KEY


@respx.mock
async def test_untyped_retry_rejects_incompatible_type(qloo):
    def handler(request):
        if "types" in request.url.params:
            return search()
        return search(("Amiga", "LOC", "urn:entity:locality"))
    respx.get(f"{QLOO}/search").mock(side_effect=handler)
    respx.get(f"{QLOO}/v2/tags").mock(return_value=tags())
    trace = Trace()
    [c] = await resolver.run(qloo, [Candidate(name="Amiga", qloo_type="urn:entity:brand")], trace)
    assert c.unresolved and c.qloo_id is None
    notes = [s for s in trace.stages if "decision" in s.stage][0].response_summary["notes"]
    assert any("urn:entity:locality" in n and "rejected" in n for n in notes)


@respx.mock
async def test_genre_resolves_via_tags_preferring_text_domain(qloo):
    respx.get(f"{QLOO}/v2/tags").mock(return_value=tags(
        ("Cyberpunk", "urn:tag:genre:music:cyberpunk", "urn:tag:genre:music", ["urn:entity:artist"]),
        ("Cyberpunk", "urn:tag:genre:media:cyberpunk", "urn:tag:genre:media", ["urn:entity:movie"]),
        ("Cyberpunk", "urn:tag:decor:qloo:cyberpunk", "urn:tag:decor:qloo", ["urn:entity:place"]),
    ))
    [c] = await resolver.run(qloo, [Candidate(name="cyberpunk", qloo_type="genre")], Trace(),
                             domains=["urn:entity:movie"])
    assert c.qloo_id == "urn:tag:genre:media:cyberpunk"
    assert c.qloo_parent_type == "urn:entity:movie"


@respx.mock
async def test_qloo_error_is_recorded_not_raised(qloo):
    respx.get(f"{QLOO}/v2/tags").mock(return_value=httpx.Response(500, json={"error": {"message": "boom"}}))
    [c] = await resolver.run(qloo, [Candidate(name="x", qloo_type="genre")], Trace())
    assert c.unresolved and "500" in c.error


def test_name_match_is_directional():
    assert resolver.name_match("Lorde Melodrama", "Lorde") < 0.85
    assert resolver.name_match("Michael Mann", "Michael") < 0.85
    assert resolver.name_match("The Bear (FX)", "The Bear") >= 0.85
    assert resolver.name_match("Assembly", "Assembly hall") < 0.85
    assert resolver.name_match("Hit Me Hard and Soft", "Hit Me Hard") < 0.85


def test_venue_tags_only_for_food_and_places():
    t = [Tag(id="urn:tag:specialty_dish:place:ramen", name="Ramen", type="urn:tag:specialty_dish:place")]
    assert resolver.best_tag("ramen", t)[0] is None
    assert resolver.best_tag("ramen", t, allow_venue=True)[0] is not None
