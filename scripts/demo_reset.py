"""Recreate the deterministic demo database and synthetic seed sessions."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.demo import demo_session_ids, reset_demo_sessions
from app.db import Repository
from app.prompts import PromptStore


def main() -> None:
    """Reset the configured database and seed public demo content."""
    repository = Repository(settings)
    prompt_store = PromptStore(settings)
    reset_demo_sessions(settings, repository, prompt_store)

    print("Demo data reset complete.")
    print(f"Database: {settings.db_path}")
    print(f"Seed: {settings.demo_seed}")
    print("Session IDs:")
    for session_id in demo_session_ids(settings.demo_seed):
        print(f"- {session_id}")


if __name__ == "__main__":
    main()
