from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    db_path: Path
    llm_backend: str
    ollama_host: str
    ollama_model: str
    prompt_active_file: Path
    prompt_versions_dir: Path
    request_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("APP_DATA_DIR", ROOT_DIR / "data"))
        db_path = Path(os.getenv("APP_DB_PATH", data_dir / "interview_agent.sqlite3"))
        prompt_active_file = Path(
            os.getenv("PROMPT_ACTIVE_FILE", ROOT_DIR / "prompts" / "active_prompt.json")
        )
        prompt_versions_dir = Path(
            os.getenv("PROMPT_VERSIONS_DIR", ROOT_DIR / "prompts" / "versions")
        )
        return cls(
            root_dir=ROOT_DIR,
            data_dir=data_dir,
            db_path=db_path,
            llm_backend=os.getenv("LLM_BACKEND", "ollama").strip().lower(),
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2:1b"),
            prompt_active_file=prompt_active_file,
            prompt_versions_dir=prompt_versions_dir,
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
        )


settings = Settings.from_env()
