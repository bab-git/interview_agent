"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


ROOT_DIR = Path(__file__).resolve().parent.parent


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """Interpret common truthy and falsy environment-variable strings."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _strip_quotes(value: str) -> str:
    """Remove one layer of matching quotes from dotenv values."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_dotenv(path: Path) -> Dict[str, str]:
    """Load a local .env file into the process without overriding explicit env vars."""
    loaded: Dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        parsed = _strip_quotes(value.strip())
        loaded[key] = parsed
        os.environ.setdefault(key, parsed)
    return loaded


_load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    """Runtime settings shared across the API, storage, and LLM layers."""

    root_dir: Path
    data_dir: Path
    db_path: Path
    llm_backend: str
    ollama_host: str
    ollama_model: str
    prompt_active_file: Path
    prompt_versions_dir: Path
    request_timeout_seconds: float
    app_mode: str
    demo_mode: bool
    demo_seed: int
    demo_reset_on_start: bool
    demo_allow_external_models: bool
    prompt_admin_enabled: bool

    @classmethod
    def from_env(cls) -> "Settings":
        """Build a settings object from environment variables and defaults."""
        requested_mode = os.getenv("APP_MODE", "").strip().lower()
        demo_mode = _parse_bool(os.getenv("DEMO_MODE"), requested_mode == "demo")
        app_mode = "demo" if requested_mode == "demo" or demo_mode else "normal"
        demo_allow_external_models = _parse_bool(os.getenv("DEMO_ALLOW_EXTERNAL_MODELS"), False)
        requested_backend = os.getenv("LLM_BACKEND", "ollama").strip().lower()
        effective_backend = "mock" if app_mode == "demo" and not demo_allow_external_models else requested_backend
        data_dir = Path(os.getenv("APP_DATA_DIR", ROOT_DIR / "data"))
        db_path = Path(os.getenv("APP_DB_PATH", data_dir / "interview_agent.sqlite3"))
        prompt_active_file = Path(
            os.getenv("PROMPT_ACTIVE_FILE", data_dir / "active_prompt.json")
        )
        prompt_versions_dir = Path(
            os.getenv("PROMPT_VERSIONS_DIR", ROOT_DIR / "prompts" / "versions")
        )
        return cls(
            root_dir=ROOT_DIR,
            data_dir=data_dir,
            db_path=db_path,
            llm_backend=effective_backend,
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2:1b"),
            prompt_active_file=prompt_active_file,
            prompt_versions_dir=prompt_versions_dir,
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
            app_mode=app_mode,
            demo_mode=app_mode == "demo",
            demo_seed=int(os.getenv("DEMO_SEED", "7")),
            demo_reset_on_start=_parse_bool(os.getenv("DEMO_RESET_ON_START"), False),
            demo_allow_external_models=demo_allow_external_models,
            prompt_admin_enabled=_parse_bool(os.getenv("PROMPT_ADMIN_ENABLED"), False),
        )


settings = Settings.from_env()
