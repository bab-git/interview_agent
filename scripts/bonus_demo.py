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
    temp_dir = tempfile.mkdtemp(prefix="interview-agent-bonus-demo-")
    prompt_src = ROOT / "prompts"
    prompt_dst = Path(temp_dir) / "prompts"
    shutil.copytree(prompt_src, prompt_dst)
    os.environ["APP_DATA_DIR"] = str(Path(temp_dir) / "data")
    os.environ["APP_DB_PATH"] = str(Path(temp_dir) / "data" / "bonus.sqlite3")
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


def complete_interview(client: TestClient, skill: str, candidate_name: str) -> str:
    start = client.post("/api/interviews", json={"skill": skill, "candidate_name": candidate_name}).json()
    interview_id = start["id"]
    answers = [
        "I coordinated a high-pressure launch with engineering, support, and operations because each group had different priorities and risks. I created a shared decision log, aligned on a rollout metric, and resolved conflicts by making trade-offs visible in one place.",
        "A teammate was blocked by a flaky test environment, so I helped isolate the failure, documented the pattern, and left the implementation with them while I improved the tooling around the issue.",
        "Strong team ownership during an incident means clear roles, concise updates, fast escalation, and a follow-up that turns confusion into process improvements with named owners.",
    ]
    for answer in answers:
        client.post(f"/api/interviews/{interview_id}/reply", json={"content": answer})
    return interview_id


def main() -> None:
    with load_client() as client:
        created = client.post(
            "/api/prompts",
            json={
                "version": "v3",
                "description": "Bonus demo prompt with more explicit follow-up wording.",
                "base_version": "v2",
                "activate": True,
                "evaluation_system_prompt": (
                    "You are evaluating a technical interview answer. Return strict JSON. "
                    "Prefer clarify when the answer lacks specifics, evidence, or outcomes."
                ),
                "skill_question_overrides": {
                    "Collaboration & Teamwork": [
                        {
                            "id": "collab2",
                            "fallback_probe": "What support did you provide, what ownership stayed with your teammate, and what changed after your help?"
                        }
                    ]
                },
            },
        )
        pretty_print("Prompt Created Through API", created.json())

        client.post("/api/prompts/activate", json={"version": "v1"})
        interview_a = complete_interview(client, "Collaboration & Teamwork", "Prompt V1 Candidate")

        client.post("/api/prompts/activate", json={"version": "v3"})
        interview_b = complete_interview(client, "Collaboration & Teamwork", "Prompt V3 Candidate")

        comparison = client.get(
            f"/api/comparisons?left_id={interview_a}&right_id={interview_b}"
        )
        pretty_print("Side-by-Side Comparison", comparison.json())

        comparison_feedback = client.post(
            "/api/comparisons/feedback",
            json={
                "left_interview_id": interview_a,
                "right_interview_id": interview_b,
                "preferred_conversation_id": interview_b,
                "evaluator_id": "reviewer-bonus",
                "overall_quality": 4,
                "fairness": 4,
                "relevance": 5,
                "flags": ["weak_followup"],
                "notes": "The newer prompt felt slightly more targeted.",
            },
        )
        pretty_print("Comparison Feedback Submitted", comparison_feedback.json())

        summary = client.get("/api/feedback/summary")
        pretty_print("Aggregated Feedback Summary", summary.json())

        suggestions = client.get("/api/prompts/suggestions")
        pretty_print("Prompt Improvement Suggestions", suggestions.json())


if __name__ == "__main__":
    main()
