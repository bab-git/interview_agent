from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_client() -> TestClient:
    temp_dir = tempfile.mkdtemp(prefix="interview-agent-demo-")
    prompt_src = ROOT / "prompts"
    prompt_dst = Path(temp_dir) / "prompts"
    shutil.copytree(prompt_src, prompt_dst)
    os.environ["APP_DATA_DIR"] = str(Path(temp_dir) / "data")
    os.environ["APP_DB_PATH"] = str(Path(temp_dir) / "data" / "demo.sqlite3")
    os.environ["PROMPT_ACTIVE_FILE"] = str(prompt_dst / "active_prompt.json")
    os.environ["PROMPT_VERSIONS_DIR"] = str(prompt_dst / "versions")
    os.environ["LLM_BACKEND"] = "mock"
    for name in list(sys.modules):
        if name.startswith("app"):
            sys.modules.pop(name, None)
    app_module = importlib.import_module("app.main")
    return TestClient(app_module.app)


def pretty_print(title: str, payload: object) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2, default=str))


def main() -> None:
    with load_client() as client:
        prompt_list = client.get("/api/prompts")
        pretty_print("Available Prompt Versions", prompt_list.json())

        start = client.post(
            "/api/interviews",
            json={"skill": "Problem Solving", "candidate_name": "Demo Candidate"},
        )
        interview = start.json()
        interview_id = interview["id"]
        pretty_print("Interview Started", interview)

        short_reply = client.post(
            f"/api/interviews/{interview_id}/reply",
            json={"content": "I fixed a service outage quickly."},
        )
        pretty_print("Reply 1 Triggers Clarification", short_reply.json())

        detailed_answers = [
            "The outage came from a bad cache invalidation path after deployment because the rollout changed a shared key format. I compared logs, isolated the bad code path, rolled back one worker group, added metrics for the affected endpoint, and validated recovery with latency and error-rate dashboards.",
            "My first attempt was to add retries, but that only hid the real issue because the dependency contract had changed. I switched to reproducing the failure locally, traced the schema mismatch, updated the serializer, and added a regression test so the same bug would fail fast next time.",
            "During urgent incidents I first restore the critical path, then protect correctness with scoped mitigations like feature flags, read-only modes, or rollback plans. I narrate risks in the incident channel, assign clear owners, and confirm the fix with user-impact metrics before closing the incident.",
        ]
        for index, answer in enumerate(detailed_answers, start=1):
            response = client.post(
                f"/api/interviews/{interview_id}/reply",
                json={"content": answer},
            )
            pretty_print(f"Detailed Reply {index}", response.json())

        retrieved = client.get(f"/api/interviews/{interview_id}")
        pretty_print("Retrieved Conversation", retrieved.json())

        feedback = client.post(
            "/api/feedback",
            json={
                "interview_id": interview_id,
                "evaluator_id": "reviewer-1",
                "overall_quality": 4,
                "fairness": 5,
                "relevance": 4,
                "flags": ["clarification_was_helpful"],
                "notes": "The first clarification usefully pushed for specifics.",
            },
        )
        pretty_print("Feedback Submitted", feedback.json())

        activate = client.post("/api/prompts/activate", json={"version": "v2"})
        pretty_print("Prompt Activated", activate.json())

        second = client.post(
            "/api/interviews",
            json={"skill": "Problem Solving", "candidate_name": "Prompt Version Check"},
        )
        pretty_print("New Interview Uses Updated Prompt", second.json())

        metrics = client.get("/api/metrics")
        pretty_print("Metrics", metrics.json())


if __name__ == "__main__":
    main()
