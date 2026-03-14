from __future__ import annotations

import importlib
import os
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    prompt_dir = tmp_path / "prompts"
    shutil.copytree(ROOT / "prompts", prompt_dir)
    os.environ["APP_DATA_DIR"] = str(tmp_path / "data")
    os.environ["APP_DB_PATH"] = str(tmp_path / "data" / "test.sqlite3")
    os.environ["PROMPT_ACTIVE_FILE"] = str(prompt_dir / "active_prompt.json")
    os.environ["PROMPT_VERSIONS_DIR"] = str(prompt_dir / "versions")
    os.environ["LLM_BACKEND"] = "mock"
    for name in list(sys.modules):
        if name.startswith("app"):
            sys.modules.pop(name, None)
    app_module = importlib.import_module("app.main")
    with TestClient(app_module.app) as test_client:
        yield test_client
