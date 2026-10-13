"""Path B end to end: extract -> resolve -> insights -> select -> generate."""

from __future__ import annotations

from ..llm.client import LLMClient
from ..qloo.client import QlooClient
from ..schema import PathResult
from . import entity_tags, extractor, generator, resolver, selector, topics
from .trace import Trace

LABEL = "Qloo-assisted"


async def run(llm: LLMClient, qloo: QlooClient, text: str, destination: str, mode: str, trace: Trace) -> PathResult:
    empty = PathResult(tags=[] if mode == "tags" else None, topics=[] if mode == "topics" else None, count=0, label=LABEL)

    cands, domains, err = await extractor.run(llm, text, trace)
    if err:
        empty.error = f"extraction failed: {err}"
        return empty
    if not cands:
        empty.error = "The extractor found no cultural references in this text, so Qloo had nothing to look up."
        return empty

    cands = await resolver.run(qloo, cands, trace, domains)
    if qloo.stub:
        empty.error = "Qloo is in stub mode (no QLOO_API_KEY on the server); no Qloo data was used."
        return empty
    if not any(c.resolved for c in cands):
        errors = sorted({c.error for c in cands if c.error})
        empty.error = ("Qloo calls failed: " + "; ".join(errors)) if errors else \
            "None of the extracted references matched anything in Qloo. Nothing is claimed."
        return empty

    cands = await entity_tags.run(qloo, cands, trace, domains=domains, with_entities=(mode == "topics"))

    if mode == "topics":
        return await topics.run(llm, text, destination, cands, trace)

    selected = selector.run(cands, text, trace)
    return await generator.run(llm, text, destination, selected, trace)
