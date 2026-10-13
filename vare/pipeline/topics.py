"""Topic mode: the same extraction and Qloo resolution, but the Insights
associations (including cross-domain entity hops) become signals for adjacent
topics instead of extra tags."""

from __future__ import annotations

from ..llm.client import LLMClient, render
from ..schema import Candidate, PathResult, TopicItem
from . import llm_json_stage
from .trace import Trace

LABEL = "Qloo-assisted"
MAX_TOPICS = 5


def parse_topics(parsed: object) -> tuple[list[TopicItem], str | None]:
    if not isinstance(parsed, list):
        return [], "expected a JSON array of topic objects"
    out = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        out.append(TopicItem(topic=topic, connection=str(item.get("connection") or "").strip(),
                             cultural_basis=str(item.get("cultural_basis") or "").strip()))
    return out[:MAX_TOPICS], None


def signals_block(cands: list[Candidate]) -> str:
    lines = []
    for c in cands:
        if not c.resolved:
            continue
        lines.append(f"- \"{c.name}\" ({c.role}) = Qloo {c.qloo_kind} \"{c.qloo_name}\" ({c.qloo_resolved_type})")
        profile = [a.name for a in c.qloo_associations if a.kind == "profile"][:12]
        if profile:
            lines.append(f"  Qloo profile: {', '.join(profile)}")
        tags = [a.name for a in c.qloo_associations if a.kind == "tag"][:8]
        if tags:
            lines.append(f"  associated tags: {', '.join(tags)}")
        ents: dict[str, list[str]] = {}
        for a in c.qloo_associations:
            if a.kind == "entity":
                ents.setdefault(a.type.rsplit(":", 1)[-1], []).append(a.name)
        for kind, names in ents.items():
            lines.append(f"  people who like it also like ({kind}): {', '.join(names[:5])}")
    return "\n".join(lines)


async def run(llm: LLMClient, text: str, destination: str, cands: list[Candidate], trace: Trace) -> PathResult:
    block = signals_block(cands)
    if not block:
        return PathResult(topics=[], count=0, label=LABEL,
                          error="No reference in the text resolved in Qloo, so there are no cultural signals to build topics from.")
    prompt = render("topics", text=text, destination=destination, signals_block=block)
    parsed, stage = await llm_json_stage(llm, trace, "B5 generate: topics from Qloo signals", prompt)
    if stage.error:
        return PathResult(topics=[], count=0, label=LABEL, error=stage.error)
    topics, err = parse_topics(parsed)
    if err:
        stage.error = err
        return PathResult(topics=[], count=0, label=LABEL, error=f"topics: {err}")
    stage.selected = [t.topic for t in topics]
    return PathResult(topics=topics, count=len(topics), label=LABEL)
