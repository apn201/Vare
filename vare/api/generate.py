"""POST /api/generate: the web front end's entry to vare.service.generate."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..config import get_settings
from ..schema import GenerateRequest, GenerateResponse
from ..service import generate as run_generate

router = APIRouter()


@router.post("/api/generate", response_model=GenerateResponse, response_model_exclude_none=False)
async def generate(req: GenerateRequest, request: Request) -> GenerateResponse:
    return await run_generate(req, request.app.state.llm, request.app.state.qloo, get_settings())
