"""Path A (baseline) and Path B (extract -> resolve -> insights -> select -> generate)."""

from __future__ import annotations

import re
from typing import Any

from ..llm.client import LLMClient, LLMError, LLMResult, extract_json
from ..schema import TraceStage
from .trace import Trace


def normalise(tag: str) -> str:
    """Comparison key for tags: case, '#', spaces and punctuation ignored."""
    return re.sub(r"[^0-9a-zÀ-ɏ]+", "", tag.lower().lstrip("#"))


async def llm_json_stage(llm: LLMClient, trace: Trace, stage: str, prompt: str,
                         **chat_kwargs: Any) -> tuple[Any, TraceStage]:
    """Run one prompt, parse JSON, record the stage. Returns (parsed or None, stage).

    One retry when the reply has no JSON: fast models occasionally wander off
    (seen: deepseek-v4.1-flash echoing the prompt into unrelated text). Every
    LLM stage on both paths goes through here, so the retry is the same for
    the baseline. The trace records every attempt. On failure the stage
    carries the error and parsed is None."""
    record = TraceStage(stage=stage, prompt=prompt, model=llm.model)
    trace.add(record)
    attempts: list[dict] = []
    parsed = None
    total_ms = total_tok = 0
    for attempt in (1, 2):
        try:
            res: LLMResult = await llm.chat(prompt, **chat_kwargs)
        except LLMError as exc:
            record.error = str(exc)
            break
        total_ms += res.latency_ms
        total_tok += res.tokens_used
        record.model = res.model
        parsed = extract_json(res)
        attempts.append({"attempt": attempt, "text_source": res.source, "finish_reason": res.finish_reason,
                         "parsed": parsed is not None, "raw_text": res.text[:2000]})
        if parsed is not None:
            record.error = None
            break
        record.error = "LLM reply contained no parseable JSON" + (
            " (cut off at max_tokens)" if res.finish_reason == "length" else "") + (" after a retry" if attempt == 2 else "")
    record.latency_ms = total_ms or None
    record.tokens_used = total_tok or None
    if attempts:
        record.response_summary = {**{k: v for k, v in attempts[-1].items() if k != "attempt"},
                                   "attempts": len(attempts)}
        if len(attempts) > 1:
            record.response_summary["failed_attempts"] = attempts[:-1]
    return parsed, record
