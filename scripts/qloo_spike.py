"""
scripts/qloo_spike.py - Qloo API smoke test (S0 spike)

Verified against the hackathon API on 2026-10-13. Differences from the
original spec, all confirmed live:
  - tag search is GET /v2/tags?filter.query=...   (GET /tags is 404)
  - entity search filters with `types=`, not `type=`
  - the video game type is urn:entity:videogame   (video_game is 400)
  - insights accepts filter.type=urn:tag, which returns associated tags
  - rate limit: 5 req/s, 10,000 req/month (x-*-ratelimit-* headers)

Run:  python scripts/qloo_spike.py
Reads QLOO_API_KEY (or KEY) and QLOO_BASE_URL (or BASE_URL) from .env.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "private" / ".env")

API_KEY = os.environ.get("QLOO_API_KEY") or os.environ.get("KEY", "")
BASE_URL = (os.environ.get("QLOO_BASE_URL") or os.environ.get("BASE_URL") or "https://hackathon.api.qloo.com").rstrip("/")
HEADERS = {"X-Api-Key": API_KEY, "Accept": "application/json"}
DROP = {"akas", "boundaries", "ancestors", "images", "description", "short_descriptions", "external", "properties"}


def slim(o):
    if isinstance(o, dict):
        return {k: slim(v) for k, v in o.items() if k not in DROP}
    if isinstance(o, list):
        return [slim(x) for x in o[:5]]
    return o


def show(label, body):
    raw = json.dumps(slim(body), indent=2, ensure_ascii=False)
    if API_KEY:
        raw = raw.replace(API_KEY, "***REDACTED***")
    print(f"\n--- {label} ---\n{raw[:2500]}")


async def call(client, path, params):
    t0 = time.monotonic()
    try:
        r = await client.get(BASE_URL + path, params=params, headers=HEADERS, timeout=15)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text[:300]}
        limits = {k: v for k, v in r.headers.items() if "ratelimit-remaining" in k}
        return r.status_code, body, int((time.monotonic() - t0) * 1000), limits
    except httpx.HTTPError as e:
        return 0, {"error": type(e).__name__}, int((time.monotonic() - t0) * 1000), {}


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"Base URL : {BASE_URL}\nKey set  : {'yes (masked)' if API_KEY else 'NO'}")
    results = {}
    async with httpx.AsyncClient() as c:
        async def step(name, path, params, check):
            await asyncio.sleep(0.3)  # stay under 5 req/s
            status, body, ms, limits = await call(c, path, params)
            show(f"{name}: GET {path} {params}", body)
            ok = status == 200 and check(body)
            results[name] = ("PASS" if ok else f"FAIL ({status})") + f"  {ms}ms {limits}"
            return body if status == 200 else {}

        body = await step("search", "/search", {"query": "Blade Runner", "types": "urn:entity:movie", "take": 3},
                          lambda b: bool(b.get("results")))
        eid = (body.get("results") or [{}])[0].get("entity_id")
        await step("tags", "/v2/tags", {"filter.query": "demoscene", "take": 5},
                   lambda b: bool(b.get("results", {}).get("tags")))
        if eid:
            await step("insights_entities", "/v2/insights",
                       {"filter.type": "urn:entity:artist", "signal.interests.entities": eid, "take": 5},
                       lambda b: bool(b.get("results", {}).get("entities")))
            await step("insights_tags", "/v2/insights",
                       {"filter.type": "urn:tag", "signal.interests.entities": eid, "take": 5},
                       lambda b: bool(b.get("results", {}).get("tags")))
        await step("insights_from_tag", "/v2/insights",
                   {"filter.type": "urn:tag", "signal.interests.tags": "urn:tag:genre:music:demoscene", "take": 5},
                   lambda b: bool(b.get("results", {}).get("tags")))

    print("\n" + "=" * 60 + "\nRESULTS\n" + "=" * 60)
    for k, v in results.items():
        print(f"  {'OK ' if v.startswith('PASS') else 'XX '} {k.ljust(18)} {v}")
    return 0 if all(v.startswith("PASS") for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
