"""Per-visitor rate limits for the public endpoints.

The demo has no login (the hackathon rules require free, unrestricted access
for judges), so anyone who finds the URL could spend the LLM credit and the
Qloo quota. Limits, all per client IP, in memory (one worker process):

- runs     POST /api/generate and MCP create_tags / suggest_topics
           (LLM + several Qloo calls each)
- lookups  MCP qloo_profile / qloo_related (Qloo only)
- a total cap on runs per day across all visitors

MCP handshakes and tools/list are free. Behind Apache the client IP comes
from X-Forwarded-For via uvicorn --proxy-headers.

Settings (env): VARE_RUNS_PER_10MIN, VARE_RUNS_PER_DAY, VARE_LOOKUPS_PER_10MIN,
VARE_RUNS_PER_DAY_TOTAL. 0 disables that limit.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

TEN_MIN = 600
DAY = 86400

RUN_TOOLS = {"create_tags", "suggest_topics"}
LOOKUP_TOOLS = {"qloo_profile", "qloo_related"}
MAX_BODY = 64 * 1024


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Window:
    limit: int
    seconds: int
    hits: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))

    def check(self, key: str, now: float) -> int:
        """0 if allowed (and counted), else seconds until the next slot."""
        if self.limit <= 0:
            return 0
        q = self.hits[key]
        while q and q[0] <= now - self.seconds:
            q.popleft()
        if len(q) >= self.limit:
            return max(1, math.ceil(q[0] + self.seconds - now))
        q.append(now)
        return 0


class Limiter:
    def __init__(self, runs_10min: int, runs_day: int, lookups_10min: int, runs_day_total: int):
        self.runs = [Window(runs_10min, TEN_MIN), Window(runs_day, DAY)]
        self.total = Window(runs_day_total, DAY)
        self.lookups = Window(lookups_10min, TEN_MIN)

    @classmethod
    def from_env(cls) -> "Limiter":
        return cls(_int_env("VARE_RUNS_PER_10MIN", 10), _int_env("VARE_RUNS_PER_DAY", 60),
                   _int_env("VARE_LOOKUPS_PER_10MIN", 30), _int_env("VARE_RUNS_PER_DAY_TOTAL", 400))

    def check(self, kind: str, ip: str, now: float | None = None) -> tuple[int, str]:
        """(retry_after_seconds, message); retry 0 means allowed."""
        now = time.monotonic() if now is None else now
        if kind == "lookup":
            wait = self.lookups.check(ip, now)
            return wait, f"Too many Qloo lookups from your address; try again in {wait} s."
        # check without counting first, so a refused request uses no slot
        for w in self.runs:
            wait = _peek(w, ip, now)
            if wait:
                return wait, f"Rate limit: at most {w.limit} runs per {_span(w.seconds)} per visitor; try again in {_human(wait)}."
        wait = _peek(self.total, "*", now)
        if wait:
            return wait, f"The demo's daily run budget is used up; try again in {_human(wait)}."
        for w in self.runs:
            w.check(ip, now)
        self.total.check("*", now)
        return 0, ""


def _peek(w: Window, key: str, now: float) -> int:
    if w.limit <= 0:
        return 0
    q = w.hits[key]
    while q and q[0] <= now - w.seconds:
        q.popleft()
    return max(1, math.ceil(q[0] + w.seconds - now)) if len(q) >= w.limit else 0


def _span(seconds: int) -> str:
    return "10 minutes" if seconds == TEN_MIN else "day"


def _human(s: int) -> str:
    return f"{s} s" if s < 120 else f"{math.ceil(s / 60)} min"


def classify(path: str, body: bytes) -> tuple[str | None, object]:
    """('run' | 'lookup' | None, json-rpc id) for a POST body."""
    if path.rstrip("/").endswith("/api/generate"):
        return "run", None
    try:
        msg = json.loads(body or b"{}")
    except ValueError:
        return None, None
    msgs = msg if isinstance(msg, list) else [msg]
    kind, rid = None, None
    for m in msgs:
        if not isinstance(m, dict) or m.get("method") != "tools/call":
            continue
        name = (m.get("params") or {}).get("name")
        rid = m.get("id")
        if name in RUN_TOOLS:
            return "run", rid
        if name in LOOKUP_TOOLS:
            kind = "lookup"
    return kind, rid


class RateLimitMiddleware:
    """Pure ASGI: buffers small POST bodies on the limited paths, decides,
    then replays the body to the app unchanged."""

    def __init__(self, app, limiter: Limiter | None = None, paths: tuple[str, ...] = ("/api/generate", "/mcp")):
        self.app = app
        self.limiter = limiter or Limiter.from_env()
        self.paths = paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or \
                not any(scope["path"].rstrip("/").endswith(p) for p in self.paths):
            return await self.app(scope, receive, send)

        chunks, size, more = [], 0, True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                return await self.app(scope, _replay([message], receive), send)
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            more = message.get("more_body", False)
            if size > MAX_BODY:
                return await _json(send, 413, {"detail": "Request body too large."})
        body = b"".join(chunks)

        kind, rid = classify(scope["path"], body)
        if kind is not None:
            ip = (scope.get("client") or ("unknown", 0))[0]
            wait, msg = self.limiter.check(kind, ip)
            if wait:
                if scope["path"].rstrip("/").endswith("/mcp"):
                    payload = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32029, "message": msg}}
                else:
                    payload = {"detail": msg}
                return await _json(send, 429, payload, {"retry-after": str(wait)})
        return await self.app(scope, _replay([{"type": "http.request", "body": body, "more_body": False}], receive), send)


def _replay(messages, original):
    """The buffered messages first, then the real channel (so a later
    receive() still sees the client's actual disconnect, not a fake one)."""
    queue = list(messages)

    async def receive():
        if queue:
            return queue.pop(0)
        return await original()
    return receive


async def _json(send, status: int, payload: dict, headers: dict | None = None):
    body = json.dumps(payload).encode()
    hdrs = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    hdrs += [(k.encode(), v.encode()) for k, v in (headers or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": hdrs})
    await send({"type": "http.response.body", "body": body})
