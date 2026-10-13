"""Stage 3: ask Qloo what it knows about the references.

Three Qloo sources, all real API data, nothing generated here:

1. Profile (GET /entities) for the subject: Qloo's own tags on that work or
   artist. The Bear -> "Culinary drama", "Kitchen operational realism";
   Billie Eilish -> "Whisper Pop", "Dark Electropop". Only tag kinds that
   describe the work are kept (PROFILE_PRIORITY); plot keywords ("Stabbed in
   the neck"), audience labels and character traits are dropped.
2. Insights tags (GET /v2/insights filter.type=urn:tag) for every reference
   the text is about, scoped to the right kind of entity with
   filter.parents.types. Comparisons and allusions are not expanded: "felt
   like Kubrick" says nothing about what the post is about.
3. Topics mode adds cross-domain entity hops (a film -> artists, books).
"""

from __future__ import annotations

import asyncio

from ..qloo.client import QlooClient
from ..qloo.models import parse_insight_entities, parse_insight_tags
from ..qloo.types import CROSS_DOMAIN, DEFAULT_CROSS_DOMAIN, TAG_PARENT_FOR_ENTITY
from ..schema import SIDE_ROLES, Association, Candidate, TraceStage
from .trace import Trace

TAKE_TAGS = 10
TAKE_ENTITIES = 5
MAX_PROFILE_TAGS = 18

# Which of Qloo's profile tag kinds describe the work itself, and how many of
# each to keep. Quotas rather than a strict order: a film profile has ~19
# style tags, and a strict order let "Contemporary" and "Dynamic" crowd out
# themes like "Celebrity culture". Anything not listed is dropped (plot
# keywords such as "Stabbed in the neck", audience labels, character traits).
PROFILE_QUOTAS = (
    ("urn:tag:subgenre:", 4),
    ("urn:tag:theme:", 4),
    ("urn:tag:style:", 4),
    ("urn:tag:genre:", 2),
    ("urn:tag:keyword:qloo", 3),
    ("urn:tag:influence:", 2),
    ("urn:tag:music:", 2),
    ("urn:tag:interests:", 2),
    ("urn:tag:plot:", 1),
)
PROFILE_PRIORITY = tuple((prefix, i) for i, (prefix, _) in enumerate(PROFILE_QUOTAS))

PEOPLE = {"urn:entity:person", "urn:entity:actor", "urn:entity:director"}
VENUES = {"urn:entity:place", "urn:entity:destination", "urn:entity:locality"}
VENUE_DOMAINS = {"urn:entity:place", "urn:entity:destination"}


def profile_priority(tag_type: str) -> int | None:
    return next((v for prefix, v in PROFILE_PRIORITY if tag_type.startswith(prefix)), None)


def _signal(c: Candidate) -> dict:
    return {"entities": [c.qloo_id]} if c.qloo_kind == "entity" else {"tags": [c.qloo_id]}


def tag_plan(c: Candidate, domains: list[str]) -> tuple[bool, dict, str]:
    """(query?, extra insights params, why). Measured: unscoped, a film returns
    "Three Star" and "VISA"; a person scoped to movies returns "teenage girl";
    a concert venue returns "Reservations"; a dish tag returns "Of Ramen"."""
    rtype = c.qloo_resolved_type or ""
    if c.role in SIDE_ROLES:
        return False, {}, f"{c.role}: mentioned, not what the text is about"
    if c.qloo_kind == "tag":
        if c.qloo_type == "cuisine":
            # tag->tag returns variants ("Of Ramen"); restricted to cuisines it
            # works but measured 13-16 s per call on the hackathon API, so the
            # dish keeps its Qloo-confirmed name and is not expanded
            return False, {}, "cuisine: Qloo cuisine associations measured >13 s per call, not expanded"
        return True, {"parent_type": c.qloo_parent_type}, "tag's own parent type"
    if rtype in VENUES and not (set(domains) & VENUE_DOMAINS):
        return False, {}, "a venue or place in a text that is not about places"
    if rtype in PEOPLE:
        if domains:
            return True, {"parent_type": domains[0]}, "person: scoped to the text's main domain"
        return False, {}, "a person, and the text has no domain to scope by"
    return True, {"parent_type": TAG_PARENT_FOR_ENTITY.get(rtype)}, "entity's own type"


def confirm_from_references(subject_refs: list, cands: list[Candidate], trace: Trace) -> None:
    """Cast and creators the search did not resolve, confirmed from the
    subject's own Qloo profile (a film's references list its cast). Heat ->
    Al Pacino: search for the actor missed, the film's profile has him."""
    by_name = {r.name.lower(): r for r in subject_refs}
    confirmed = []
    for c in cands:
        if c.resolved or c.role not in ("cast", "creator"):
            continue
        r = by_name.get(c.name.lower())
        if r is None:
            continue
        c.qloo_id, c.qloo_name, c.qloo_resolved_type, c.qloo_kind = r.entity_id, r.name, r.type, "entity"
        c.unresolved, c.error = False, None
        confirmed.append(f"{c.name} -> {r.name} [{r.type}]")
    if confirmed:
        trace.add(TraceStage(stage="B3 profile: cast confirmed from the subject's Qloo references", selected=confirmed))


async def _profile_for(qloo: QlooClient, c: Candidate, trace: Trace, refs_out: list) -> list[Association]:
    profiles, res = await qloo.entities([c.qloo_id], trace=trace, stage=f"B3 profile: Qloo's own tags for {c.qloo_name}")
    if not res.ok:
        c.error = res.error
        return []
    if not profiles:
        return []
    refs_out.extend(profiles[0].references)
    kept: list[tuple[int, int, Association]] = []
    dropped: dict[str, int] = {}
    seen: set[str] = set()
    for i, t in enumerate(profiles[0].tags):
        prio = profile_priority(t.type)
        key = t.name.lower()
        if prio is None:
            kind = t.type.replace("urn:tag:", "")
            dropped[kind] = dropped.get(kind, 0) + 1
            continue
        if key in seen:
            continue
        seen.add(key)
        kept.append((prio, i, Association(id=t.tag_id, name=t.name, kind="profile", type=t.type)))
    # within each kind keep Qloo's order, up to the kind's quota; then
    # interleave the kinds so every kind is represented near the top
    by_kind: dict[int, list[Association]] = {}
    for prio, _, a in sorted(kept, key=lambda x: (x[0], x[1])):
        if len(by_kind.setdefault(prio, [])) < PROFILE_QUOTAS[prio][1]:
            by_kind[prio].append(a)
    out: list[Association] = []
    for round_ in range(max((q for _, q in PROFILE_QUOTAS), default=0)):
        for prio in sorted(by_kind):
            if round_ < len(by_kind[prio]):
                out.append(by_kind[prio][round_])
    out = out[:MAX_PROFILE_TAGS]
    for rank, a in enumerate(out):
        a.rank = rank
    trace.add(TraceStage(
        stage=f"B3 profile: kept for {c.qloo_name}",
        params={"kinds_and_quotas": dict(PROFILE_QUOTAS), "max": MAX_PROFILE_TAGS},
        selected=[f"{a.name} [{a.type.replace('urn:tag:', '')}]" for a in out] or None,
        response_summary={"profile_tags": len(profiles[0].tags), "kept": len(out), "dropped_by_kind": dropped},
    ))
    return out


async def _tags_for(qloo: QlooClient, c: Candidate, trace: Trace, domains: list[str]) -> list[Association]:
    ok, extra, why = tag_plan(c, domains)
    if not ok:
        trace.add(TraceStage(stage=f"B3 insights: {c.qloo_name or c.name} (skipped)", response_summary={"reason": why}))
        return []
    res = await qloo.insights("urn:tag", take=TAKE_TAGS, trace=trace,
                              stage=f"B3 insights: tags for {c.qloo_name}", **extra, **_signal(c))
    if not res.ok:
        c.error = res.error
        return []
    return [Association(id=t.tag_id, name=t.name, kind="tag", type=t.subtype, affinity=t.affinity, rank=i)
            for i, t in enumerate(parse_insight_tags(res.body))
            if t.tag_id != c.qloo_id]


async def _entities_for(qloo: QlooClient, c: Candidate, trace: Trace) -> list[Association]:
    targets = CROSS_DOMAIN.get(c.qloo_resolved_type or "", DEFAULT_CROSS_DOMAIN) if c.qloo_kind == "entity" else DEFAULT_CROSS_DOMAIN
    out: list[Association] = []
    for ft in targets:
        res = await qloo.insights(ft, take=TAKE_ENTITIES, trace=trace,
                                  stage=f"B3 insights: {ft.rsplit(':', 1)[-1]} for {c.qloo_name}", **_signal(c))
        if not res.ok:
            c.error = res.error
            continue
        out += [Association(id=e.entity_id, name=e.name, kind="entity", type=e.subtype or ft, affinity=e.affinity)
                for e in parse_insight_entities(res.body) if e.entity_id != c.qloo_id]
    return out


async def run(qloo: QlooClient, cands: list[Candidate], trace: Trace, *, domains: list[str] | None = None,
              with_entities: bool = False, max_entity_sources: int = 4) -> list[Candidate]:
    resolved = [c for c in cands if c.resolved]
    subject_refs: list = []

    async def one(c: Candidate, i: int) -> None:
        jobs = [_tags_for(qloo, c, trace, domains or [])]
        if c.role == "subject" and c.qloo_kind == "entity":
            jobs.append(_profile_for(qloo, c, trace, subject_refs))
        if with_entities and i < max_entity_sources and c.role not in SIDE_ROLES:
            jobs.append(_entities_for(qloo, c, trace))
        parts = await asyncio.gather(*jobs)
        c.qloo_associations = [a for part in parts for a in part]

    await asyncio.gather(*(one(c, i) for i, c in enumerate(resolved)))
    confirm_from_references(subject_refs, cands, trace)
    return cands
