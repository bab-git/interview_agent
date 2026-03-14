from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.config import Settings
from app.logging_utils import log_event


@dataclass
class LLMResult:
    content: str
    backend: str
    used_fallback: bool = False


class LLMBackend:
    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        raise NotImplementedError

    def is_reachable(self) -> Optional[bool]:
        return None


class OllamaBackend(LLMBackend):
    def __init__(self, settings: Settings):
        self.settings = settings

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        payload = json.dumps(
            {
                "model": self.settings.ollama_model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "options": {"temperature": 0.1},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.settings.ollama_host}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.request_timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log_event("ollama_request_failed", error=str(exc))
            raise RuntimeError("local LLM request failed") from exc
        content = body.get("message", {}).get("content", "").strip()
        if not content:
            raise RuntimeError("local LLM returned an empty response")
        return LLMResult(content=content, backend=f"ollama:{self.settings.ollama_model}")

    def is_reachable(self) -> Optional[bool]:
        request = urllib.request.Request(f"{self.settings.ollama_host}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=3):
                return True
        except urllib.error.URLError:
            return False


class MockBackend(LLMBackend):
    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        try:
            payload = json.loads(user_prompt)
        except json.JSONDecodeError:
            payload = {"answer": user_prompt}
        answer = str(payload.get("answer", "")).strip()
        word_count = len([token for token in answer.split() if token])
        if word_count < 25:
            content = {
                "verdict": "clarify",
                "score": 2,
                "reasoning": "The answer is too brief and leaves out important context and outcomes.",
                "missing_points": ["context", "decision process", "result"],
                "follow_up": "Can you add more detail on the situation, what you decided, and the outcome?",
            }
        else:
            content = {
                "verdict": "complete",
                "score": 4,
                "reasoning": "The answer is specific and covers the main decision points.",
                "missing_points": [],
                "follow_up": None,
            }
        return LLMResult(content=json.dumps(content), backend="mock")

    def is_reachable(self) -> Optional[bool]:
        return True


def build_llm_backend(settings: Settings) -> LLMBackend:
    if settings.llm_backend == "mock":
        return MockBackend()
    return OllamaBackend(settings)
