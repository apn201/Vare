"""OpenAI-compatible async chat client. Port of Virta's nebius_client.

Kept from Virta:
- Reasoning models may leave `message.content` empty and put the answer in
  `reasoning_content`. `_extract_text` handles that in one place.
- Structured output by prompting for JSON and parsing the last complete JSON
  block (`extract_json`), no tools or response_format, so any OpenAI-compatible
  endpoint works.

Changed: plain async httpx instead of the openai SDK (one less dependency, and
respx can mock it in tests). Errors are raised as LLMError with a message aimed
at fixing the setup; the pipeline turns them into honest error fields.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings

PROMPT_DIR = Path(__file__).parent / "prompts"
_PROMPTS: dict[str, str] = {}


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMResult:
    content: str
    reasoning_content: str
    source: str            # "content" | "reasoning_content" | "empty"
    model: str
    tokens_used: int
    latency_ms: int
    finish_reason: str = ""

    @property
    def text(self) -> str:
        return self.content or self.reasoning_content


def load_prompt(name: str) -> str:
    if name not in _PROMPTS:
        _PROMPTS[name] = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    return _PROMPTS[name]


def render(name: str, **values: str) -> str:
    """`{{variable}}` substitution. Values are inserted verbatim, once, so text
    containing braces cannot trigger further substitution."""
    out = load_prompt(name)
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def _extract_text(message: dict) -> tuple[str, str, str]:
    content = (message.get("content") or "").strip()
    reasoning = (message.get("reasoning_content") or message.get("reasoning") or "").strip()
    source = "content" if content else ("reasoning_content" if reasoning else "empty")
    return content, reasoning, source


class LLMClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._http = http
        self._own_http = http is None

    @property
    def model(self) -> str:
        return self.settings.llm_model

    async def aclose(self) -> None:
        if self._own_http and self._http is not None:
            await self._http.aclose()

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.settings.llm_timeout_s)
        return self._http

    async def chat(self, prompt: str, *, temperature: float = 0.3, max_tokens: int = 6000) -> LLMResult:
        if not self.settings.llm_key_set:
            raise LLMError("LLM_API_KEY is not set on the server, so no LLM call was made.")
        url = self.settings.llm_base_url + "/chat/completions"
        payload = {
            "model": self.settings.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        mode = self.settings.llm_reasoning
        # Measured on deepseek-v4.1-flash: extraction took 70 s with thinking
        # (even at effort=minimal) and 2.5 s without, same output. Applied to
        # every call, so both paths get identical model behaviour.
        if mode == "off":
            payload["reasoning"] = {"enabled": False}
        elif mode:
            payload["reasoning"] = {"effort": mode}
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}", "Content-Type": "application/json"}
        t0 = time.monotonic()
        try:
            resp = await self._client().post(url, json=payload, headers=headers, timeout=self.settings.llm_timeout_s)
        except httpx.TimeoutException:
            raise LLMError(f"LLM timed out after {self.settings.llm_timeout_s:.0f}s") from None
        except httpx.HTTPError as exc:
            raise LLMError(f"could not reach the LLM endpoint ({type(exc).__name__})") from None
        ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code != 200:
            hint = {
                401: "the LLM endpoint rejected the API key",
                403: "the key is not entitled to this model, or credits ran out",
                404: f"unknown model {self.settings.llm_model!r} or wrong LLM_BASE_URL",
                429: "the LLM endpoint rate-limited the request",
            }.get(resp.status_code, "the LLM endpoint returned an error")
            raise LLMError(f"LLM HTTP {resp.status_code}: {hint}. {_short_body(resp)}")

        try:
            data = resp.json()
            choice = data["choices"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("LLM returned a response with no choices") from None
        content, reasoning, source = _extract_text(choice.get("message") or {})
        usage = data.get("usage") or {}
        return LLMResult(
            content=content,
            reasoning_content=reasoning,
            source=source,
            model=str(data.get("model") or self.settings.llm_model),
            tokens_used=int(usage.get("total_tokens") or 0),
            latency_ms=ms,
            finish_reason=str(choice.get("finish_reason") or ""),
        )


def _short_body(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        msg = err.get("message") if isinstance(err, dict) else (err or body)
        return f"Server said: {str(msg)[:200]}"
    except ValueError:
        return f"Server said: {resp.text[:200]}"


def extract_json(result: LLMResult) -> Any:
    """Find the JSON answer. `content` first, then `reasoning_content`, where
    the last complete block wins. Returns None when nothing parses; callers
    treat that as no answer and never guess."""
    for text in (result.content, result.reasoning_content):
        if not text:
            continue
        value = parse_json_block(text)
        if value is not None:
            return value
    return None


def parse_json_block(text: str) -> Any:
    cleaned = text.replace("```json", "```")
    decoder = json.JSONDecoder()
    starts = [i for i, ch in enumerate(cleaned) if ch in "[{"]
    # outermost-first from the last top-level block: try each start, keep the
    # one that parses and reaches furthest, preferring later blocks
    best = None
    best_end = -1
    for i in starts:
        try:
            value, end = decoder.raw_decode(cleaned[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, (list, dict)) and i + end > best_end:
            best, best_end = value, i + end
    return best
