"""Väre as an MCP server: a culture-aware tagging service for agents.

- create_tags     tags for a post, caption or description, grounded in Qloo:
                  what the text is about, described with Qloo's profile and
                  taste graph; every tag with its source and evidence
- suggest_topics  adjacent cultural topics for the same text
- qloo_profile    Qloo's own description of a work, artist or place
- qloo_related    what Qloo's taste graph connects an entity to

qloo_profile and qloo_related call Qloo only, no LLM. The conventional-LLM
comparison is not part of the service: it lives on the web test bench.

Transports:
- streamable HTTP at /mcp, mounted into the web app (vare.main)
- stdio for local agents:  python -m vare.mcp_server
"""

from __future__ import annotations

import os
import re
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, ValidationError

from . import runtime
from .config import get_settings
from .pipeline.entity_tags import PROFILE_QUOTAS, profile_priority
from .pipeline.resolver import best_entity
from .qloo.models import parse_insight_entities, parse_insight_tags
from .qloo.types import TAG_PARENT_FOR_ENTITY
from .schema import MAX_TEXT, GenerateRequest
from .service import create

EntityType = Literal["movie", "tv_show", "book", "artist", "album", "videogame", "podcast", "brand",
                     "place", "destination", "person", "actor", "director", "author"]
RelatedType = Literal["movie", "tv_show", "book", "artist", "videogame", "podcast", "brand",
                      "place", "destination", "person", "tag"]
Destination = Literal["general", "youtube", "linkedin", "instagram"]

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)

INSTRUCTIONS = """Väre is a culture-aware tagging service backed by Qloo's taste graph.
Use create_tags to tag a post, caption, script or description: Väre works out what the text is
about, looks it up in Qloo, and returns tags that describe it the way Qloo knows it (subgenres,
styles, themes, creators), each with its source and evidence. Use suggest_topics for adjacent
cultural topics to write about next. Use qloo_profile to see how Qloo describes a film, show,
book, artist or place, and qloo_related to see what Qloo connects it to.
Tags marked qloo_* come from real Qloo API responses; nothing is invented. Texts without a
cultural subject (e.g. corporate updates) get no Qloo tags, and the result says so."""

mcp = MCPServer(name="vare", title="Väre", instructions=INSTRUCTIONS, version="0.3.0")


def _urn(t: str) -> str:
    return "urn:tag" if t == "tag" else f"urn:entity:{t}"


def format_for(destination: str, tags: list[str]) -> str:
    """Ready to paste: comma-separated for general, hashtags otherwise."""
    if destination == "general":
        return ", ".join(tags)
    # "Body horror" -> #BodyHorror; existing capitals kept ("FINNEAS")
    words = ("".join(w[:1].upper() + w[1:] for w in re.split(r"[^\w]+", t)) for t in tags)
    return " ".join("#" + w for w in words if w)


# ---- result models (structured tool output) ------------------------------

class TagOut(BaseModel):
    tag: str
    source: str = Field(description="qloo_direct: in the text, confirmed in Qloo | qloo_profile: Qloo's own tag "
                                     "for the subject | qloo_inferred: Qloo taste-graph association | "
                                     "llm: in the text, not found in Qloo")
    explanation: str = ""
    evidence: str | None = None


class TagsResult(BaseModel):
    tags: list[TagOut] = Field(default_factory=list, description="Most important first")
    formatted: str = Field("", description="The tags ready to paste for the destination")
    note: str | None = Field(None, description="Why there are no or few tags (no cultural subject, Qloo error...)")
    latency_ms: int


class TopicOut(BaseModel):
    topic: str
    connection: str = Field(description="How it connects to the text")
    cultural_basis: str = Field(description="The Qloo signal it rests on")


class TopicsResult(BaseModel):
    topics: list[TopicOut] = Field(default_factory=list)
    note: str | None = None
    latency_ms: int


class EntityRef(BaseModel):
    name: str
    qloo_id: str
    type: str


class ProfileResult(BaseModel):
    found: bool
    entity: EntityRef | None = None
    tags_by_kind: dict[str, list[str]] = Field(default_factory=dict,
                                               description="Qloo's own tags for the entity: subgenre, theme, style...")
    cast: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list, description="Qloo search results, when no exact match")
    error: str | None = None


class RelatedItem(BaseModel):
    name: str
    type: str
    affinity: float | None = None


class RelatedResult(BaseModel):
    found: bool
    entity: EntityRef | None = None
    related_type: str
    related: list[RelatedItem] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)
    error: str | None = None


# ---- tools -----------------------------------------------------------------

def _request(text: str, destination: str, mode: str) -> GenerateRequest:
    try:
        return GenerateRequest(text=text, destination=destination, mode=mode, advanced=False)
    except ValidationError as exc:
        raise ToolError("; ".join(e["msg"] for e in exc.errors())) from None


@mcp.tool(annotations=READ_ONLY)
async def create_tags(
    text: str = Field(description=f"The post, caption, script or description to tag (max {MAX_TEXT} chars)"),
    destination: Destination = Field("general", description="Where it will be posted; sets the tone and the "
                                                            "'formatted' output (hashtags or comma-separated)"),
) -> TagsResult:
    """Culture-aware tags for a text. Väre works out what the text is about (leaving out things it
    only compares to or alludes to), resolves it in Qloo, and describes it with Qloo's own profile
    and taste graph: subgenres, styles, themes, creators. 8-14 tags, each with source and evidence.
    Takes about 5-15 seconds."""
    llm, qloo = runtime.clients()
    result, ms = await create(_request(text, destination, "tags"), llm, qloo, get_settings())
    tags = [TagOut(tag=t.tag, source=t.source, explanation=t.explanation, evidence=t.evidence) for t in result.tags or []]
    return TagsResult(tags=tags, formatted=format_for(destination, [t.tag for t in tags]), note=result.error, latency_ms=ms)


@mcp.tool(annotations=READ_ONLY)
async def suggest_topics(
    text: str = Field(description=f"The post, caption, script or description (max {MAX_TEXT} chars)"),
    destination: Destination = "general",
) -> TopicsResult:
    """Up to 5 adjacent cultural topics a creator could explore next, each resting on a named
    Qloo signal: the subject's Qloo profile, associated tags, and what its audience also likes
    in other domains (a film -> music, books). Takes about 10-20 seconds."""
    llm, qloo = runtime.clients()
    result, ms = await create(_request(text, destination, "topics"), llm, qloo, get_settings())
    return TopicsResult(topics=[TopicOut(**t.model_dump()) for t in result.topics or []], note=result.error, latency_ms=ms)


async def _resolve(name: str, entity_type: str):
    """(EntityRef | None, candidate names, error)."""
    _, qloo = runtime.clients()
    results, res = await qloo.search(name, types=_urn(entity_type), take=5)
    if not res.ok:
        return None, [], res.error
    hit, _ = best_entity(name, results)
    if hit is None:
        return None, [f"{e.name} ({e.disambiguation or e.type})" for e in results], None
    return EntityRef(name=hit.name, qloo_id=hit.entity_id, type=hit.type), [], None


@mcp.tool(annotations=READ_ONLY)
async def qloo_profile(
    name: str = Field(max_length=200, description="e.g. 'The Bear', 'Billie Eilish', 'Heat'"),
    entity_type: EntityType = Field(description="What kind of thing the name is"),
) -> ProfileResult:
    """How Qloo describes a film, show, book, artist, brand or place: its subgenres, themes,
    styles and genres (Qloo's own tags, plot-level keywords and audience labels left out), plus
    cast where Qloo lists it. Qloo data only, no LLM."""
    ref, candidates, error = await _resolve(name, entity_type)
    if ref is None:
        return ProfileResult(found=False, candidates=candidates, error=error)
    _, qloo = runtime.clients()
    profiles, res = await qloo.entities([ref.qloo_id])
    if not res.ok or not profiles:
        return ProfileResult(found=True, entity=ref, error=res.error or "Qloo returned no profile")
    groups: dict[str, list[str]] = {}
    for t in profiles[0].tags:
        prio = profile_priority(t.type)
        if prio is None:
            continue
        kind = PROFILE_QUOTAS[prio][0].removeprefix("urn:tag:").rstrip(":").split(":")[0]
        bucket = groups.setdefault(kind, [])
        if t.name not in bucket and len(bucket) < 10:
            bucket.append(t.name)
    order = [p.removeprefix("urn:tag:").rstrip(":").split(":")[0] for p, _ in PROFILE_QUOTAS]
    groups = {k: groups[k] for k in order if k in groups}
    return ProfileResult(found=True, entity=ref, tags_by_kind=groups,
                         cast=[r.name for r in profiles[0].references][:15])


@mcp.tool(annotations=READ_ONLY)
async def qloo_related(
    name: str = Field(max_length=200, description="e.g. 'The Substance'"),
    entity_type: EntityType = Field(description="What kind of thing the name is"),
    related_type: RelatedType = Field(description="What to get back: 'movie' for similar films, 'artist' "
                                                  "for music its fans like, 'tag' for associated tags, ..."),
    take: int = Field(default=10, ge=1, le=25),
) -> RelatedResult:
    """What Qloo's taste graph connects an entity to, across domains: similar films, artists or
    books its audience also likes, or associated tags. Ranked by Qloo affinity. Qloo data only,
    no LLM."""
    ref, candidates, error = await _resolve(name, entity_type)
    if ref is None:
        return RelatedResult(found=False, related_type=related_type, candidates=candidates, error=error)
    _, qloo = runtime.clients()
    parent = TAG_PARENT_FOR_ENTITY.get(ref.type) if related_type == "tag" else None
    res = await qloo.insights(_urn(related_type), entities=[ref.qloo_id], take=take, parent_type=parent)
    if not res.ok:
        return RelatedResult(found=True, entity=ref, related_type=related_type, error=res.error)
    if related_type == "tag":
        items = [RelatedItem(name=t.name, type=t.subtype, affinity=t.affinity) for t in parse_insight_tags(res.body)]
    else:
        items = [RelatedItem(name=e.name, type=e.subtype or _urn(related_type), affinity=e.affinity)
                 for e in parse_insight_entities(res.body) if e.entity_id != ref.qloo_id]
    return RelatedResult(found=True, entity=ref, related_type=related_type, related=items)


# ---- HTTP mounting -----------------------------------------------------------

def transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection stays on. Localhost is always allowed (Apache
    proxying to 127.0.0.1 keeps that Host); public hostnames come from
    MCP_ALLOWED_HOSTS, e.g. "vare.helppox.com,helppox.com"."""
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    for h in filter(None, (x.strip() for x in os.environ.get("MCP_ALLOWED_HOSTS", "").split(","))):
        hosts += [h, f"{h}:*"]
        origins += [f"https://{h}", f"http://{h}"]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=hosts, allowed_origins=origins)


def http_routes():
    """Routes for /mcp, to add to the FastAPI app. Stateless JSON responses:
    no long-lived streams, so it proxies cleanly through Apache."""
    app = mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True,
                                  transport_security=transport_security())
    return app.routes


if __name__ == "__main__":
    mcp.run("stdio")
