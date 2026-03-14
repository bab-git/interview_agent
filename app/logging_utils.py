"""Structured logging helpers for the interview service."""

from __future__ import annotations

import json
import logging
from typing import Any


def configure_logging() -> None:
    """Configure application-wide log formatting and noisy dependency levels."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def log_event(event: str, **fields: Any) -> None:
    """Emit a structured JSON log event with arbitrary key-value fields."""
    payload = {"event": event, **fields}
    logging.getLogger("interview_agent").info(json.dumps(payload, sort_keys=True))
