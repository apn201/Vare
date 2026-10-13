"""Response shapes, verified against the hackathon API (S0, 2026-10-13).

Only the fields Väre reads are modelled; everything else (akas, boundaries,
long descriptions) is ignored on purpose.

GET /search -> {"results": [ {name, entity_id, types: [urn], popularity,
                 disambiguation, tags: [{name, tag_id, type, value}]} ]}
GET /v2/tags -> {"success", "results": {"tags": [ {id, name, type,
                 popularity, parents: [{type}]} ]}}
GET /v2/insights filter.type=urn:entity:* ->
                {"success", "results": {"entities": [ {name, entity_id,
                 type: "urn:entity", subtype: "urn:entity:artist",
                 query: {affinity}} ]}}
GET /entities?entity_ids=<id> -> {"results": [ {name, entity_id, types,
                 tags: [{name, tag_id, type}],          # Qloo's own profile tags
                 references: [{entity_id, name, type}]  # e.g. a film's cast
                 } ]}
GET /v2/insights filter.type=urn:tag ->
                {"success", "results": {"tags": [ {tag_id, name, subtype,
                 types: [urn], popularity, query: {affinity}} ]}}
"""

from __future__ import annotations

from pydantic import BaseModel


class SearchEntity(BaseModel):
    entity_id: str
    name: str
    types: list[str] = []
    popularity: float | None = None
    disambiguation: str | None = None

    @property
    def type(self) -> str:
        return self.types[0] if self.types else "urn:entity"


class Tag(BaseModel):
    id: str
    name: str
    type: str = ""
    popularity: float | None = None
    parents: list[str] = []        # entity types this tag describes


class InsightEntity(BaseModel):
    entity_id: str
    name: str
    subtype: str = ""
    affinity: float | None = None


class InsightTag(BaseModel):
    tag_id: str
    name: str
    subtype: str = ""
    affinity: float | None = None


def parse_search(body: dict) -> list[SearchEntity]:
    out = []
    for r in body.get("results") or []:
        if isinstance(r, dict) and r.get("entity_id") and r.get("name"):
            out.append(SearchEntity(**{k: (r[k].strip() if k == "name" else r[k]) for k in ("entity_id", "name", "types", "popularity", "disambiguation") if r.get(k) is not None}))
    return out


def parse_tags(body: dict) -> list[Tag]:
    results = body.get("results") or {}
    tags = results.get("tags") if isinstance(results, dict) else None
    out = []
    for t in tags or []:
        tid = t.get("id") or t.get("tag_id")
        if tid and t.get("name"):
            parents = [p.get("type") for p in t.get("parents") or [] if isinstance(p, dict) and p.get("type")]
            out.append(Tag(id=tid, name=t["name"].strip(), type=t.get("type") or t.get("subtype") or "",
                           popularity=t.get("popularity"), parents=parents))
    return out


def _affinity(item: dict) -> float | None:
    q = item.get("query")
    if isinstance(q, dict) and isinstance(q.get("affinity"), (int, float)):
        return float(q["affinity"])
    return None


def parse_insight_entities(body: dict) -> list[InsightEntity]:
    results = body.get("results") or {}
    out = []
    for e in (results.get("entities") if isinstance(results, dict) else None) or []:
        if e.get("entity_id") and e.get("name"):
            out.append(InsightEntity(entity_id=e["entity_id"], name=e["name"].strip(), subtype=e.get("subtype") or e.get("type") or "", affinity=_affinity(e)))
    return out


def parse_insight_tags(body: dict) -> list[InsightTag]:
    results = body.get("results") or {}
    out = []
    for t in (results.get("tags") if isinstance(results, dict) else None) or []:
        tid = t.get("tag_id") or t.get("id")
        if tid and t.get("name"):
            out.append(InsightTag(tag_id=tid, name=t["name"].strip(), subtype=t.get("subtype") or t.get("type") or "", affinity=_affinity(t)))
    return out


class ProfileTag(BaseModel):
    tag_id: str
    name: str
    type: str = ""


class EntityProfile(BaseModel):
    entity_id: str
    name: str
    tags: list[ProfileTag] = []
    references: list[SearchEntity] = []


def parse_entity_profiles(body: dict) -> list[EntityProfile]:
    out = []
    for e in body.get("results") or []:
        if not isinstance(e, dict) or not e.get("entity_id"):
            continue
        tags = [ProfileTag(tag_id=t.get("tag_id") or t.get("id"), name=t["name"].strip(), type=t.get("type") or "")
                for t in e.get("tags") or [] if isinstance(t, dict) and t.get("name") and (t.get("tag_id") or t.get("id"))]
        refs = [SearchEntity(entity_id=r["entity_id"], name=r["name"].strip(), types=[r.get("type") or "urn:entity"])
                for r in e.get("references") or [] if isinstance(r, dict) and r.get("entity_id") and r.get("name")]
        out.append(EntityProfile(entity_id=e["entity_id"], name=str(e.get("name") or ""), tags=tags, references=refs))
    return out
