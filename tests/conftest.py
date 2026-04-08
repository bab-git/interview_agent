from __future__ import annotations

import importlib
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@contextmanager
def _build_client(tmp_path: Path, **env_overrides: str) -> TestClient:
    prompt_dir = tmp_path / "prompts"
    shutil.copytree(ROOT / "prompts", prompt_dir)
    base_env = {
        "APP_DATA_DIR": str(tmp_path / "data"),
        "APP_DB_PATH": str(tmp_path / "data" / "test.sqlite3"),
        "PROMPT_ACTIVE_FILE": str(prompt_dir / "active_prompt.json"),
        "PROMPT_VERSIONS_DIR": str(prompt_dir / "versions"),
        "LLM_BACKEND": "mock",
        "APP_MODE": "normal",
        "DEMO_MODE": "false",
        "DEMO_RESET_ON_START": "false",
        "PROMPT_ADMIN_ENABLED": "true",
    }
    previous = {key: os.environ.get(key) for key in {**base_env, **env_overrides}}
    for key, value in {**base_env, **env_overrides}.items():
        os.environ[key] = value
    for name in list(sys.modules):
        if name.startswith("app"):
            sys.modules.pop(name, None)
    app_module = importlib.import_module("app.main")
    try:
        with TestClient(app_module.app) as test_client:
            yield test_client
    finally:
        for name in list(sys.modules):
            if name.startswith("app"):
                sys.modules.pop(name, None)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    with _build_client(tmp_path) as test_client:
        yield test_client


@pytest.fixture
def locked_prompt_client(tmp_path: Path) -> TestClient:
    with _build_client(
        tmp_path,
        APP_MODE="demo",
        DEMO_MODE="true",
        PROMPT_ADMIN_ENABLED="false",
    ) as test_client:
        yield test_client
