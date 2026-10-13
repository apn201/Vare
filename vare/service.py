"""One comparison run: both paths on the same text, concurrently.

Shared by POST /api/generate and the MCP tools, so a web user and an agent
get exactly the same pipeline. Never raises: a failing path is reported in
its own error field and the other path still runs.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from .config import Settings
from .db import db
from .llm.client import LLMClient
from .pipeline import baseline, experimental, normalise
from .pipeline.trace import Trace, scrub
from .qloo.client import QlooClient
from .schema import Comparison, GenerateRequest, GenerateResponse, PathResult


def _keys(result: PathResult) -> list[str]:
    if result.tags is not None:
        return [normalise(t.tag) for t in result.tags]
    return [normalise(t.topic) for t in result.topics or []]


def compare(a: PathResult, b: PathResult) -> tuple[int, int]:
    ka, kb = set(_keys(a)), set(_keys(b))
    return len(ka & kb), len(kb - ka)


async def _guard(coro, label: str, mode: str) -> PathResult:
    try:
        return await coro
    except Exception as exc:  # last line of defence; the message is shown, not hidden
        empty: list = []
        return PathResult(tags=empty if mode == "tags" else None, topics=empty if mode == "topics" else None,
                          count=0, label=label, error=f"internal error: {type(exc).__name__}: {exc}"[:400])


async def create(req: GenerateRequest, llm: LLMClient, qloo: QlooClient, settings: Settings) -> tuple[PathResult, int]:
    """The product: Väre's culture-aware tags (or topics) for a text, without
    the comparison baseline. Returns (result, latency_ms), scrubbed of secrets."""
    t0 = time.monotonic()
    result = await _guard(experimental.run(llm, qloo, req.text, req.destination, req.mode, Trace()),
                          experimental.LABEL, req.mode)
    result = PathResult(**scrub(result.model_dump(), settings.secrets()))
    return result, int((time.monotonic() - t0) * 1000)


async def generate(req: GenerateRequest, llm: LLMClient, qloo: QlooClient, settings: Settings) -> GenerateResponse:
    """The web test bench: the same Väre run next to a conventional LLM tagger."""
    trace = Trace()
    t0 = time.monotonic()

    if req.mode == "tags":
        a_coro = baseline.run(llm, req.text, req.destination, trace)
    else:
        a_coro = baseline.run_topics(llm, req.text, req.destination, trace)
    b_coro = experimental.run(llm, qloo, req.text, req.destination, req.mode, trace)

    a, b = await asyncio.gather(
        _guard(a_coro, baseline.LABEL, req.mode),
        _guard(b_coro, experimental.LABEL, req.mode),
    )
    overlap, novelty = compare(a, b)
    total_ms = int((time.monotonic() - t0) * 1000)

    stages = sorted(trace.sanitised(settings.secrets()), key=lambda s: s.stage[:2])
    resp = GenerateResponse(
        request_id=str(uuid.uuid4()),
        mode=req.mode,
        destination=req.destination,
        comparison=Comparison(baseline=a, experimental=b, overlap_count=overlap,
                              novelty_count=novelty, total_latency_ms=total_ms),
        trace=stages if req.advanced else None,
    )
    # Error strings come from upstreams and can echo a key back; scrub the
    # whole response, not just the trace.
    resp = GenerateResponse(**scrub(resp.model_dump(), settings.secrets()))
    if settings.debug_retain_traces:
        db.save(resp, stages, req)
    return resp
