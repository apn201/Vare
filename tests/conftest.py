import json
import os

# the app's rate limits would trip over the test suite; test_ratelimit tests them directly
for _name in ("VARE_RUNS_PER_10MIN", "VARE_RUNS_PER_DAY", "VARE_LOOKUPS_PER_10MIN", "VARE_RUNS_PER_DAY_TOTAL"):
    os.environ[_name] = "0"

import httpx
import pytest

from vare.config import Settings
from vare.llm.client import LLMClient
from vare.qloo.client import QlooClient

QLOO = "https://qloo.test"
LLM = "https://llm.test/v1"
QLOO_KEY = "qloo-secret-key-1234567890"
LLM_KEY = "test-llm-key-not-real-0987"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        qloo_api_key=QLOO_KEY, qloo_base_url=QLOO,
        llm_base_url=LLM, llm_api_key=LLM_KEY, llm_model="test-model",
        qloo_cache_path="", debug_retain_traces=False,
    )


@pytest.fixture(autouse=True)
def fast_pacing(monkeypatch):
    import vare.qloo.client as qc
    monkeypatch.setattr(qc, "MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(qc, "RETRY_WAIT_S", 0.0)
    monkeypatch.setattr(qc, "_PACER", qc._Pacer())


@pytest.fixture
def llm(settings):
    return LLMClient(settings, http=httpx.AsyncClient())


@pytest.fixture
def qloo(settings):
    return QlooClient(settings, http=httpx.AsyncClient())


def chat_reply(content, tokens=42):
    return httpx.Response(200, json={
        "model": "test-model",
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"total_tokens": tokens},
    })


def json_reply(obj):
    return chat_reply(json.dumps(obj))


def prompt_of(request) -> str:
    return json.loads(request.content)["messages"][0]["content"]
