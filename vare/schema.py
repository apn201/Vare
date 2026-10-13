"""Every pydantic model the API speaks, plus the internal Candidate record."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Destination = Literal["general", "youtube", "linkedin", "instagram"]
Mode = Literal["tags", "topics"]
Source = Literal["llm", "qloo_direct", "qloo_profile", "qloo_inferred"]
Role = Literal["subject", "creator", "cast", "context", "comparison", "allusion"]
ROLES = ("subject", "creator", "cast", "context", "comparison", "allusion")
# references the text only compares with or alludes to: not the post's topic,
# so they are neither tags nor expanded through Qloo
SIDE_ROLES = ("comparison", "allusion")

MAX_TEXT = 4000


class GenerateRequest(BaseModel):
    text: str = Field(min_length=1)
    destination: Destination = "general"
    mode: Mode = "tags"
    advanced: bool = False

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text is empty")
        if len(v) > MAX_TEXT:
            raise ValueError(f"text is {len(v)} chars; the limit is {MAX_TEXT}")
        return v


class TagItem(BaseModel):
    tag: str
    explanation: str = ""
    source: Source
    evidence: str | None = None


class TopicItem(BaseModel):
    topic: str
    connection: str
    cultural_basis: str


class PathResult(BaseModel):
    tags: list[TagItem] | None = None
    topics: list[TopicItem] | None = None
    count: int = 0
    label: str
    error: str | None = None


class Comparison(BaseModel):
    baseline: PathResult
    experimental: PathResult
    overlap_count: int
    novelty_count: int
    total_latency_ms: int


class TraceStage(BaseModel):
    stage: str
    prompt: str | None = None
    model: str | None = None
    endpoint: str | None = None
    method: str | None = None
    params: dict | None = None
    response_summary: dict | None = None
    raw_items: list | None = None
    selected: list | None = None
    rejected: list | None = None
    latency_ms: int | None = None
    tokens_used: int | None = None
    error: str | None = None


class GenerateResponse(BaseModel):
    request_id: str
    mode: Mode
    destination: Destination
    comparison: Comparison
    trace: list[TraceStage] | None = None


# ---- internal: one cultural reference moving through Path B ---------------

class Association(BaseModel):
    """Something Qloo Insights returned for a resolved candidate."""

    id: str
    name: str
    kind: Literal["tag", "entity", "profile"]   # profile = Qloo's own tag on the entity
    type: str                      # tag subtype or entity subtype URN
    affinity: float | None = None
    rank: int = 0                  # position in the Insights response


class Candidate(BaseModel):
    name: str
    qloo_type: str
    evidence: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    ambiguous: bool = False
    role: Role = "context"
    implied: bool = False          # not named in the text; proposed by the LLM, must be confirmed by Qloo
    # filled by the resolver
    qloo_id: str | None = None
    qloo_name: str | None = None
    qloo_resolved_type: str | None = None
    qloo_kind: Literal["entity", "tag"] | None = None
    qloo_parent_type: str | None = None    # entity type a resolved tag describes
    unresolved: bool = False
    error: str | None = None
    # filled by entity_tags
    qloo_associations: list[Association] = Field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.qloo_id is not None


class PoolItem(BaseModel):
    """A scored tag candidate inside the selector."""

    tag: str
    source: Source
    evidence: str | None = None
    origin: str                     # which candidate it came from
    role: str | None = None         # role of that candidate in the text
    qloo_id: str | None = None
    qloo_type: str | None = None
    affinity: float | None = None
    rank: int = 0
    support: int = 1                # how many references Qloo linked this tag to
    text_relevance: int = 0
    cultural_depth: int = 0
    specificity: int = 0
    about_subject: int = 0
    score: int = 0
