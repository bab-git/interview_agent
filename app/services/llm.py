"""LLM backend adapters used by the interview engine."""

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
    """Normalized response returned by an LLM backend."""

    content: str
    backend: str
    used_fallback: bool = False


class LLMBackend:
    """Abstract interface for answer-evaluation backends."""

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        """Return a model completion for the supplied prompts."""
        raise NotImplementedError

    def is_reachable(self) -> Optional[bool]:
        """Report whether the backend appears reachable, if detectable."""
        return None


class OllamaBackend(LLMBackend):
    """LLM backend that evaluates answers through a local Ollama service."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        """Send a structured evaluation request to the configured Ollama model."""
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
        """Check whether the configured Ollama instance responds to a tags query."""
        request = urllib.request.Request(f"{self.settings.ollama_host}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=3):
                return True
        except urllib.error.URLError:
            return False


class MockBackend(LLMBackend):
    """Deterministic backend used for tests and reviewer demos."""

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        """Return a predictable clarify-or-complete judgment from the answer length."""
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
        """Always report reachable for the in-process mock backend."""
        return True


def build_llm_backend(settings: Settings) -> LLMBackend:
    """Create the configured LLM backend implementation."""
    if settings.llm_backend == "mock":
        return MockBackend()
    return OllamaBackend(settings)
