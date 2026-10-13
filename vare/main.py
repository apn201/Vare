"""FastAPI app: the web front end, its API, and the MCP endpoint at /mcp."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import runtime
from .api import generate, health
from .mcp_server import http_routes, mcp
from .ratelimit import RateLimitMiddleware

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.llm, app.state.qloo = runtime.clients()
    async with mcp.session_manager.run():
        yield
    await runtime.close()


app = FastAPI(title="Väre", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
app.include_router(health.router)
app.include_router(generate.router)
app.router.routes.extend(http_routes())       # POST /mcp (streamable HTTP, stateless)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.add_middleware(RateLimitMiddleware)            # per-visitor limits on runs and lookups


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
