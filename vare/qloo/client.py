"""Async Qloo client.

- X-Api-Key auth against the hackathon base URL.
- Never raises: every call returns a QlooResult carrying either data or a
  structured error, plus the TraceStage describing what happened.
- Process-wide pacing keeps us under the hackathon limit of 5 requests/second
  (the API returns x-second-ratelimit-limit: 5). One retry on 429 after 2 s.
- Optional private SQLite cache, allowed by the hackathon terms, so repeated
  demo runs do not burn the 10,000/month quota.
- Stub mode (no key, or key == "stub"): no network, empty results, and the
  trace says so.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..config import ROOT, Settings
from ..schema import TraceStage
from ..pipeline.trace import Trace, strip_params
from . import models

MIN_INTERVAL_S = 0.25          # 4 req/s, under the 5/s limit
MAX_CONCURRENCY = 4
RETRY_WAIT_S = 2.0


@dataclass
class QlooResult:
    ok: bool
    status: int
    body: dict = field(default_factory=dict)
    error: str | None = None
    cached: bool = False
    stub: bool = False


class _Pacer:
    """Spaces request starts at least MIN_INTERVAL_S apart, process-wide."""

    def __init__(self) -> None:
        self._lock: asyncio.Lock | None = None
        self._next = 0.0

    async def wait(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = time.monotonic() + MIN_INTERVAL_S


_PACER = _Pacer()


class _Cache:
    def __init__(self, path: str) -> None:
        self.path = None
        if path:
            p = Path(path)
            if not p.is_absolute():
                p = ROOT / p
            p.parent.mkdir(parents=True, exist_ok=True)
            self.path = p
            with sqlite3.connect(p) as db:
                db.execute("CREATE TABLE IF NOT EXISTS qloo_cache (k TEXT PRIMARY KEY, body TEXT, ts REAL)")

    @staticmethod
    def key(path: str, params: dict) -> str:
        return path + "?" + json.dumps(sorted((str(k), str(v)) for k, v in params.items()))

    def get(self, k: str) -> dict | None:
        if not self.path:
            return None
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT body FROM qloo_cache WHERE k = ?", (k,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, k: str, body: dict) -> None:
        if not self.path:
            return
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO qloo_cache (k, body, ts) VALUES (?, ?, ?)", (k, json.dumps(body), time.time()))


def _count(body: dict) -> int:
    r = body.get("results")
    if isinstance(r, list):
        return len(r)
    if isinstance(r, dict):
        return sum(len(v) for v in r.values() if isinstance(v, list))
    return 0


def _names(body: dict, limit: int = 12) -> list[str]:
    r = body.get("results")
    items: list[Any] = []
    if isinstance(r, list):
        items = r
    elif isinstance(r, dict):
        for v in r.values():
            if isinstance(v, list):
                items.extend(v)
    out = []
    for it in items[:limit]:
        if isinstance(it, dict):
            kind = it.get("subtype") or (it.get("types") or [None])[0] or it.get("type")
            out.append(f"{it.get('name')} [{kind}]" if kind else str(it.get("name")))
    return out


class QlooClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._http = http
        self._own_http = http is None
        self._sem = asyncio.Semaphore(MAX_CONCURRENCY)
        self._cache = _Cache(settings.qloo_cache_path)
        # Qloo reports the remaining monthly quota on every response. Below
        # the reserve, stop calling: the key has to last through judging.
        self.month_remaining: int | None = None
        self.month_reserve = settings.qloo_month_reserve

    @property
    def stub(self) -> bool:
        return self.settings.qloo_stub

    async def aclose(self) -> None:
        if self._own_http and self._http is not None:
            await self._http.aclose()

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.settings.qloo_timeout_s)
        return self._http

    async def get(self, path: str, params: dict, trace: Trace | None, stage: str) -> QlooResult:
        t0 = time.monotonic()
        record = TraceStage(stage=stage, endpoint=path, method="GET", params=strip_params(dict(params)))

        def finish(res: QlooResult) -> QlooResult:
            record.latency_ms = int((time.monotonic() - t0) * 1000)
            record.response_summary = {"status": res.status, "count": _count(res.body), "cached": res.cached}
            if res.stub:
                record.response_summary["stub_mode"] = True
            record.raw_items = _names(res.body) or None
            record.error = res.error
            if trace is not None:
                trace.add(record)
            return res

        if self.stub:
            return finish(QlooResult(ok=True, status=0, body={"results": []}, stub=True))

        ck = _Cache.key(path, params)
        hit = self._cache.get(ck)
        if hit is not None:
            return finish(QlooResult(ok=True, status=200, body=hit, cached=True))

        if self.month_remaining is not None and self.month_remaining <= self.month_reserve:
            return finish(QlooResult(ok=False, status=0, error=(
                f"Qloo monthly quota reserve reached ({self.month_remaining} calls left, "
                f"reserve {self.month_reserve}); not calling Qloo")))

        url = self.settings.qloo_base_url + path
        headers = {"X-Api-Key": self.settings.qloo_api_key, "Accept": "application/json"}
        async with self._sem:
            for attempt in (1, 2):
                await _PACER.wait()
                try:
                    resp = await self._client().get(url, params=params, headers=headers, timeout=self.settings.qloo_timeout_s)
                except httpx.TimeoutException:
                    return finish(QlooResult(ok=False, status=0, error=f"timeout after {self.settings.qloo_timeout_s:.0f}s"))
                except httpx.HTTPError as exc:
                    return finish(QlooResult(ok=False, status=0, error=f"network error: {type(exc).__name__}"))
                if resp.status_code == 429 and attempt == 1:
                    await asyncio.sleep(RETRY_WAIT_S)
                    continue
                break

        remaining = resp.headers.get("x-month-ratelimit-remaining")
        if remaining is not None and remaining.isdigit():
            self.month_remaining = int(remaining)
        try:
            body = resp.json()
        except ValueError:
            body = {"_raw": resp.text[:300]}
        if not isinstance(body, dict):
            body = {"results": body}
        if resp.status_code // 100 != 2:
            msg = _error_message(body) or resp.reason_phrase
            return finish(QlooResult(ok=False, status=resp.status_code, body={}, error=f"Qloo {resp.status_code}: {msg}"))
        self._cache.put(ck, body)
        return finish(QlooResult(ok=True, status=resp.status_code, body=body))

    # ---- typed helpers ---------------------------------------------------

    async def search(self, query: str, types: str | None = None, take: int = 3,
                     trace: Trace | None = None, stage: str = "qloo search") -> tuple[list[models.SearchEntity], QlooResult]:
        params: dict = {"query": query, "take": take}
        if types:
            params["types"] = types
        res = await self.get("/search", params, trace, stage)
        return (models.parse_search(res.body) if res.ok else []), res

    async def tags(self, query: str, take: int = 3, trace: Trace | None = None,
                   stage: str = "qloo tags") -> tuple[list[models.Tag], QlooResult]:
        res = await self.get("/v2/tags", {"filter.query": query, "take": take}, trace, stage)
        return (models.parse_tags(res.body) if res.ok else []), res

    async def entities(self, ids: list[str], trace: Trace | None = None,
                       stage: str = "qloo entities") -> tuple[list[models.EntityProfile], QlooResult]:
        """Entity detail: Qloo's own profile tags for the entity, and its references (cast)."""
        res = await self.get("/entities", {"entity_ids": ",".join(ids)}, trace, stage)
        return (models.parse_entity_profiles(res.body) if res.ok else []), res

    async def insights(self, filter_type: str, entities: list[str] | None = None, tags: list[str] | None = None,
                       take: int = 10, trace: Trace | None = None, stage: str = "qloo insights",
                       parent_type: str | None = None, tag_types: str | None = None) -> QlooResult:
        params: dict = {"filter.type": filter_type, "take": take}
        if parent_type:
            params["filter.parents.types"] = parent_type
        if tag_types:
            params["filter.tag.types"] = tag_types
        if entities:
            params["signal.interests.entities"] = ",".join(entities)
        if tags:
            params["signal.interests.tags"] = ",".join(tags)
        return await self.get("/v2/insights", params, trace, stage)


def _error_message(body: dict) -> str:
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("reason") or "")[:300]
    if isinstance(err, str):
        return err[:300]
    errs = body.get("errors")
    if isinstance(errs, list) and errs:
        return str(errs[0].get("message") if isinstance(errs[0], dict) else errs[0])[:300]
    return str(body.get("error_msg") or body.get("message") or "")[:300]
