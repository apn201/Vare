from fastapi import APIRouter, Request

from ..config import get_settings

router = APIRouter()


@router.get("/api/health")
async def health(request: Request) -> dict:
    s = get_settings()
    qloo = getattr(request.app.state, "qloo", None)
    return {
        "status": "ok",
        "qloo_key_set": not s.qloo_stub,
        "llm_key_set": s.llm_key_set,
        "llm_model": s.llm_model,
        # last value Qloo reported (x-month-ratelimit-remaining); None until the first call
        "qloo_month_remaining": getattr(qloo, "month_remaining", None),
        "qloo_month_reserve": s.qloo_month_reserve,
    }
