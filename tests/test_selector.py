from vare.pipeline import selector
from vare.pipeline.trace import Trace
from vare.schema import Association, Candidate

TEXT = "Billie Eilish at the O2. Haven't felt a room like that since Lorde's Melodrama tour."


def resolved(name, assoc=()):
    return Candidate(name=name, qloo_type="urn:entity:artist", evidence=name, qloo_id=f"ID-{name}", qloo_name=name,
                     qloo_resolved_type="urn:entity:artist", qloo_kind="entity",
                     qloo_associations=[Association(id=f"T-{a}", name=a, kind="tag", type=t, rank=i)
                                        for i, (a, t) in enumerate(assoc)])


def test_scoring_formula():
    pool = selector.build_pool([resolved("Lorde", [("indie pop", "urn:tag:genre:music")])], TEXT)
    direct, inferred = pool
    assert (direct.text_relevance, direct.cultural_depth, direct.specificity, direct.score) == (2, 0, 1, 5)
    assert (inferred.text_relevance, inferred.cultural_depth, inferred.specificity, inferred.score) == (0, 1, 1, 2)


def test_support_merges_and_wins_ties():
    cands = [
        resolved("Billie Eilish", [("Animated", "urn:tag:subgenre:qloo"), ("indie pop", "urn:tag:genre:music")]),
        resolved("Lorde", [("indie pop", "urn:tag:genre:music")]),
    ]
    kept = selector.run(cands, TEXT, Trace())
    inferred = [p for p in kept if p.source == "qloo_inferred"]
    assert inferred[0].tag == "indie pop" and inferred[0].support == 2
    assert "Billie Eilish + Lorde" in inferred[0].origin


def test_generic_inferred_rejected_with_reason():
    cands = [resolved("Lorde", [("VISA", "urn:tag:credit_card:place")])]
    trace = Trace()
    kept = selector.run(cands, TEXT, trace)
    assert all(p.tag != "VISA" for p in kept)
    assert any(r["tag"] == "VISA" and "below" in r["reason"] for r in trace.stages[-1].rejected)


def test_inferred_cannot_match_text_through_its_own_origin():
    cands = [Candidate(name="Future Crew", qloo_type="urn:entity:artist", evidence="Future Crew", qloo_id="F",
                       qloo_name="Future Crew", qloo_resolved_type="urn:entity:artist", qloo_kind="entity",
                       qloo_associations=[Association(id="t", name="Dystopian Futures", kind="tag", type="urn:tag:theme:qloo")])]
    pool = selector.build_pool(cands, "I love Future Crew demos")
    assert pool[1].text_relevance == 0


def test_near_duplicates_dropped():
    assert selector.is_dup("Demoscene", "demo scene")
    assert selector.is_dup("demoscene", "demoszene")
    assert selector.is_dup("Tracker", "tracker music")
    assert not selector.is_dup("pop", "k pop")


def test_specific_inferred_tag_replaces_generic_one():
    cands = [resolved("Frank Herbert", [("Fiction", "urn:tag:genre:media"), ("Science Fiction", "urn:tag:genre:media")]),
             resolved("Messiah", [("Fiction", "urn:tag:genre:media")])]
    kept = selector.run(cands, "reread Frank Herbert before Messiah", Trace())
    tags = [p.tag for p in kept]
    assert "Science Fiction" in tags and "Fiction" not in tags


def test_unresolved_candidate_enters_as_llm():
    c = Candidate(name="Feyd-Rautha", qloo_type="none", evidence="Feyd-Rautha", unresolved=True)
    [p] = selector.build_pool([c], "Austin Butler's Feyd-Rautha stole every scene")
    assert p.source == "llm" and p.cultural_depth == 0


def test_cap_at_max_selected():
    names = ["Adele", "Bjork", "Coldplay", "Drake", "Eminem", "Feist", "Gorillaz", "Hozier", "Interpol", "Jamiroquai",
             "Kesha", "Lizzo", "Muse", "Nirvana", "Oasis", "Pulp", "Queen", "Radiohead", "Sade", "Toto",
             "Usher", "Weezer", "Xzibit", "Yello", "Zappa"]
    kept = selector.run([resolved(n) for n in names], " ".join(names), Trace())
    assert len(kept) == selector.MAX_SHORTLIST


def test_comparisons_and_unconfirmed_implied_never_become_tags():
    cands = [
        Candidate(name="The Substance", qloo_type="urn:entity:movie", role="subject", evidence="The Substance",
                  qloo_id="S", qloo_name="The Substance", qloo_resolved_type="urn:entity:movie", qloo_kind="entity",
                  qloo_associations=[Association(id="p1", name="Body horror", kind="profile", type="urn:tag:subgenre:qloo")]),
        Candidate(name="Kubrick", qloo_type="urn:entity:director", role="comparison", evidence="Kubrik movies"),
        Candidate(name="Cinderella", qloo_type="concept", role="allusion", evidence="Cinderella"),
        Candidate(name="Someone", qloo_type="urn:entity:director", role="creator", implied=True, unresolved=True),
    ]
    trace = Trace()
    kept = selector.run(cands, "Finally watched The Substance. Kubrik vibes, Cinderella themes.", trace)
    assert [p.tag for p in kept] == ["The Substance", "Body horror"]
    assert kept[0].about_subject == 1 and kept[1].source == "qloo_profile"
    reasons = {r["tag"]: r["reason"] for r in trace.stages[-1].rejected}
    assert reasons["Kubrick"].startswith("comparison") and reasons["Cinderella"].startswith("allusion")
    assert "not confirmed by Qloo" in reasons["Someone"]


def test_profile_and_insights_agreeing_merge_into_one():
    c = Candidate(name="Heat", qloo_type="urn:entity:movie", role="subject", evidence="Heat", qloo_id="H",
                  qloo_name="Heat", qloo_resolved_type="urn:entity:movie", qloo_kind="entity",
                  qloo_associations=[Association(id="a", name="Neo noir", kind="tag", type="urn:tag:subgenre:qloo"),
                                     Association(id="b", name="Neo noir", kind="profile", type="urn:tag:subgenre:qloo")])
    pool = selector.build_pool([c], "Rewatched Heat")
    neo = [p for p in pool if p.tag == "Neo noir"]
    assert len(neo) == 1 and neo[0].source == "qloo_profile" and neo[0].support == 2
