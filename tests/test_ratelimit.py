import httpx
import respx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from vare.ratelimit import Limiter, RateLimitMiddleware, classify

from .conftest import QLOO


def call(name, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": {}}}


def test_classify():
    assert classify("/api/generate", b"") == ("run", None)
    assert classify("/mcp", b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}') == (None, None)
    assert classify("/vare/mcp", httpx.Request("POST", "/", json=call("create_tags", 7)).read()) == ("run", 7)
    assert classify("/mcp", httpx.Request("POST", "/", json=call("qloo_profile", 3)).read()) == ("lookup", 3)
    assert classify("/mcp", b"not json") == (None, None)


def test_windows_per_ip_and_total():
    lim = Limiter(runs_10min=2, runs_day=3, lookups_10min=1, runs_day_total=4)
    assert lim.check("run", "a", now=0)[0] == 0
    assert lim.check("run", "a", now=1)[0] == 0
    wait, msg = lim.check("run", "a", now=2)
    assert wait == 598 and "10 minutes" in msg
    assert lim.check("run", "a", now=700)[0] == 0          # window moved on
    wait, msg = lim.check("run", "a", now=800)               # 4th today, day limit is 3
    assert wait > 0 and "per day" in msg
    assert lim.check("run", "b", now=800)[0] == 0           # another visitor is unaffected
    wait, msg = lim.check("run", "c", now=801)               # total budget (4) used up
    assert wait > 0 and "daily run budget" in msg
    assert lim.check("lookup", "a", now=900)[0] == 0
    assert lim.check("lookup", "a", now=901)[0] > 0


def test_refused_request_does_not_use_a_slot():
    lim = Limiter(runs_10min=1, runs_day=0, lookups_10min=0, runs_day_total=0)
    assert lim.check("run", "a", now=0)[0] == 0
    for t in range(1, 5):
        assert lim.check("run", "a", now=t)[0] > 0
    assert lim.check("run", "a", now=601)[0] == 0


async def _echo(request):
    return JSONResponse({"ok": True, "body": (await request.body()).decode()})


def _app(limiter):
    inner = Starlette(routes=[Route("/api/generate", _echo, methods=["POST"]), Route("/mcp", _echo, methods=["POST"])])
    return RateLimitMiddleware(inner, limiter)


async def test_middleware_web_and_mcp():
    app = _app(Limiter(runs_10min=1, runs_day=0, lookups_10min=0, runs_day_total=0))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/generate", json={"text": "x"})
        assert r.status_code == 200 and '"text"' in r.json()["body"]      # body replayed intact
        r = await c.post("/api/generate", json={"text": "x"})
        assert r.status_code == 429 and "runs per 10 minutes" in r.json()["detail"]
        assert int(r.headers["retry-after"]) > 0
        # the same visitor's MCP run counts against the same budget, as a JSON-RPC error
        r = await c.post("/mcp", json=call("create_tags", 9))
        assert r.status_code == 429
        assert r.json()["id"] == 9 and r.json()["error"]["code"] == -32029
        # handshakes and listing stay free
        r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert r.status_code == 200


async def test_qloo_monthly_reserve_stops_calls(qloo):
    qloo.month_reserve = 300
    with respx.mock:
        route = respx.get(f"{QLOO}/search").mock(return_value=httpx.Response(
            200, json={"results": []}, headers={"x-month-ratelimit-remaining": "299"}))
        _, first = await qloo.search("Heat", take=1)
        assert first.ok and qloo.month_remaining == 299
        _, second = await qloo.search("Heat 2", take=1)
        assert not second.ok and "reserve" in second.error
        assert route.call_count == 1
