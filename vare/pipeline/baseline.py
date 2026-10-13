"""Path A: a conventional LLM tag (or topic) generator.

Same model and endpoint as Path B. Not weakened: the prompt asks for specific
tags and the model is free to use everything it knows.
"""

from __future__ import annotations

from ..llm.client import LLMClient, render
from ..schema import PathResult, TagItem
from . import llm_json_stage, normalise
from .topics import parse_topics
from .trace import Trace

LABEL = "Conventional LLM"


async def run(llm: LLMClient, text: str, destination: str, trace: Trace) -> PathResult:
    prompt = render("baseline", text=text, destination=destination)
    parsed, stage = await llm_json_stage(llm, trace, "A0 baseline: LLM tags", prompt)
    if stage.error:
        return PathResult(tags=[], count=0, label=LABEL, error=stage.error)
    if not isinstance(parsed, list) or not all(isinstance(t, str) for t in parsed):
        stage.error = "expected a JSON array of strings"
        return PathResult(tags=[], count=0, label=LABEL, error=f"baseline: {stage.error}")

    tags: list[TagItem] = []
    seen: set[str] = set()
    for raw in parsed:
        t = raw.strip().lstrip("#").strip()
        key = normalise(t)
        if not key or key in seen:
            continue
        seen.add(key)
        tags.append(TagItem(tag=t, explanation="", source="llm", evidence=None))
    stage.selected = [t.tag for t in tags]
    return PathResult(tags=tags, count=len(tags), label=LABEL)


async def run_topics(llm: LLMClient, text: str, destination: str, trace: Trace) -> PathResult:
    prompt = render("baseline_topics", text=text, destination=destination)
    parsed, stage = await llm_json_stage(llm, trace, "A0 baseline: LLM topics", prompt)
    if stage.error:
        return PathResult(topics=[], count=0, label=LABEL, error=stage.error)
    topics, err = parse_topics(parsed)
    if err:
        stage.error = err
        return PathResult(topics=[], count=0, label=LABEL, error=f"baseline: {err}")
    stage.selected = [t.topic for t in topics]
    return PathResult(topics=topics, count=len(topics), label=LABEL)
