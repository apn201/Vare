"""Stage 2: resolve each candidate against Qloo, or mark it unresolved.

The extractor's qloo_type picks the route directly:
  entity URN  -> GET /search?types=<urn>; if empty, retry untyped
  otherwise   -> GET /v2/tags?filter.query=<name>
  entity miss -> last resort: GET /v2/tags (platforms like "Amiga" exist as tags)

Code decides whether a hit counts. A result is accepted only if its name
actually matches the candidate, and an untyped retry is accepted only if the
type it found is compatible with the one asked for. Without that check,
"Amiga" the computer resolves to Amiga, a neighbourhood in Rosario.
"""

from __future__ import annotations

import asyncio
from difflib import SequenceMatcher

from ..qloo.client import QlooClient
from ..qloo.models import SearchEntity, Tag
from ..qloo.types import QLOO_ENTITY_TYPES, VENUE_TYPES, is_generic_tag_type
from ..schema import SIDE_ROLES, Candidate, TraceStage
from . import normalise
from .trace import Trace

COMPATIBLE = [
    {"urn:entity:brand", "urn:entity:videogame"},
    {"urn:entity:movie", "urn:entity:tv_show"},
    {"urn:entity:artist", "urn:entity:album", "urn:entity:person"},
    # an actor who also wrote a memoir is not "an author" for our purposes:
    # resolving Rutger Hauer as urn:entity:author drags in book genres
    {"urn:entity:person", "urn:entity:actor", "urn:entity:director"},
    {"urn:entity:person", "urn:entity:author"},
    {"urn:entity:book", "urn:entity:author"},
    {"urn:entity:destination", "urn:entity:locality", "urn:entity:place"},
]


def compatible(wanted: str, found: str) -> bool:
    return wanted == found or any(wanted in g and found in g for g in COMPATIBLE)


def name_match(query: str, found: str) -> float:
    """0..1. Exact normalised match = 1. The found name contained in the query
    = 0.9 ("Amiga" for "Amiga 500"); the reverse is not, because extra words
    change the meaning ("Assembly" is not "Assembly hall"). Else fuzzy ratio."""
    nq, nf = normalise(query), normalise(found)
    if not nq or not nf:
        return 0.0
    if nq == nf:
        return 1.0
    # ...and only when it covers most of the query: "Hit Me Hard" is a
    # different album from "Hit Me Hard and Soft"
    if nf in nq and len(nf) >= 4 and len(nf) / len(nq) >= 0.7:
        return 0.9
    return SequenceMatcher(None, nq, nf).ratio()


MIN_MATCH = 0.85


def best_entity(name: str, results: list[SearchEntity]) -> tuple[SearchEntity | None, float]:
    scored = sorted(((name_match(name, e.name), i, e) for i, e in enumerate(results)), key=lambda x: (-x[0], x[1]))
    if scored and scored[0][0] >= MIN_MATCH:
        return scored[0][2], scored[0][0]
    return None, scored[0][0] if scored else 0.0


def in_domains(tag: Tag, domains: list[str]) -> bool:
    return any(p in domains for p in tag.parents)


def best_tag(name: str, results: list[Tag], allow_venue: bool = False,
             domains: list[str] | None = None) -> tuple[Tag | None, float]:
    """Venue/menu/mood tag types only count for food and place references.
    Among name matches, a tag that describes one of the text's domains wins
    ("Cyberpunk" the film genre for a film post, not the decor style); then
    API order."""
    domains = domains or []
    scored = sorted(((name_match(name, t.name), i, t) for i, t in enumerate(results)
                     if allow_venue or not is_generic_tag_type(t.type)),
                    key=lambda x: (-x[0], x[1]))
    matches = [x for x in scored if x[0] >= MIN_MATCH]
    if matches:
        top = matches[0][0]
        tied = [x for x in matches if x[0] >= top - 0.05]
        pick = next((x for x in tied if in_domains(x[2], domains)), tied[0])
        return pick[2], pick[0]
    return None, scored[0][0] if scored else 0.0


def parent_for(tag: Tag, domains: list[str]) -> str | None:
    return next((p for p in tag.parents if p in domains), tag.parents[0] if tag.parents else None)


async def resolve_one(qloo: QlooClient, c: Candidate, trace: Trace, domains: list[str]) -> Candidate:
    notes: list[str] = []
    stage_name = f"B2 resolve: {c.name}"
    try:
        if c.qloo_type in QLOO_ENTITY_TYPES:
            results, res = await qloo.search(c.name, types=c.qloo_type, take=5, trace=trace, stage=stage_name + f" (search {c.qloo_type})")
            if not res.ok:
                c.error = res.error
            hit, score = best_entity(c.name, results)
            if hit is None and results:
                notes.append(f"typed search returned no name match (best {score:.2f})")
            if hit is None and res.ok:
                results, res = await qloo.search(c.name, take=5, trace=trace, stage=stage_name + " (search, untyped retry)")
                if not res.ok:
                    c.error = res.error
                cand, score = best_entity(c.name, results)
                if cand is not None and not compatible(c.qloo_type, cand.type):
                    notes.append(f"untyped match '{cand.name}' is {cand.type}, not {c.qloo_type}: rejected")
                    cand = None
                hit = cand
            if hit is not None:
                c.qloo_id, c.qloo_name, c.qloo_resolved_type, c.qloo_kind = hit.entity_id, hit.name, hit.type, "entity"
                c.error = None
                return c
            # last resort: platforms, scenes and styles often live as tags
            tags, res = await qloo.tags(c.name, take=5, trace=trace, stage=stage_name + " (tag fallback)")
        else:
            tags, res = await qloo.tags(c.name, take=5, trace=trace, stage=stage_name + " (tags)")
        if not res.ok:
            c.error = res.error
        tag, score = best_tag(c.name, tags, allow_venue=c.qloo_type in VENUE_TYPES, domains=domains)
        if tag is not None:
            c.qloo_id, c.qloo_name, c.qloo_resolved_type, c.qloo_kind = tag.id, tag.name, tag.type, "tag"
            c.qloo_parent_type = parent_for(tag, domains)
            c.error = None
        else:
            if tags:
                notes.append(f"tag search returned no name match (best {score:.2f})")
            c.unresolved = True
    finally:
        if notes:
            trace.add(TraceStage(stage=stage_name + " (decision)", response_summary={"notes": notes}))
    return c


async def run(qloo: QlooClient, cands: list[Candidate], trace: Trace,
              domains: list[str] | None = None) -> list[Candidate]:
    # comparisons and allusions are not what the text is about: not looked up
    lookups = [c for c in cands if c.role not in SIDE_ROLES]
    await asyncio.gather(*(resolve_one(qloo, c, trace, domains or []) for c in lookups))
    resolved = cands
    trace.add(TraceStage(
        stage="B2 resolve: summary",
        selected=[{"name": c.name, "role": c.role, "implied": c.implied, "qloo_name": c.qloo_name, "qloo_id": c.qloo_id,
                   "kind": c.qloo_kind, "type": c.qloo_resolved_type, "describes": c.qloo_parent_type} for c in resolved if c.resolved] or None,
        rejected=[{"name": c.name, "reason": f"{c.role}: not looked up" if c.role in SIDE_ROLES
                   else (c.error or "no matching Qloo entity or tag")}
                  for c in resolved if not c.resolved] or None,
        params={"domains": domains or []},
        response_summary={"resolved": sum(c.resolved for c in resolved), "total": len(resolved)},
    ))
    return list(resolved)
