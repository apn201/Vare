"""Per-request trace: collect one TraceStage per step, sanitise before it leaves.

Two layers of protection (spec rule 4):
1. Parameter keys that look like credentials are dropped when a stage is added.
2. Before the trace reaches the response, every string anywhere in it is
   scrubbed of the actual secret values. Even if a key ended up inside an
   error message or a prompt, it does not get out.
"""

from __future__ import annotations

import time
from typing import Any

from ..schema import TraceStage

SENSITIVE_MARKERS = ("key", "token", "secret", "auth", "api", "password", "cookie")
REDACTED = "***REDACTED***"


def is_sensitive_name(name: str) -> bool:
    low = name.lower()
    return any(m in low for m in SENSITIVE_MARKERS)


def strip_params(params: dict | None) -> dict | None:
    if params is None:
        return None
    return {k: v for k, v in params.items() if not is_sensitive_name(str(k))}


def scrub(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for s in secrets:
            if s and s in value:
                value = value.replace(s, REDACTED)
        return value
    if isinstance(value, dict):
        return {k: scrub(v, secrets) for k, v in value.items() if not is_sensitive_name(str(k)) or k in ("tokens_used",)}
    if isinstance(value, (list, tuple)):
        return [scrub(v, secrets) for v in value]
    return value


class Trace:
    def __init__(self) -> None:
        self.stages: list[TraceStage] = []

    def add(self, stage: TraceStage) -> TraceStage:
        stage.params = strip_params(stage.params)
        self.stages.append(stage)
        return stage

    def sanitised(self, secrets: list[str]) -> list[TraceStage]:
        out = []
        for st in self.stages:
            data = scrub(st.model_dump(), secrets)
            out.append(TraceStage(**data))
        return out


class Timer:
    def __init__(self) -> None:
        self.t0 = time.monotonic()

    @property
    def ms(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)
