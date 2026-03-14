from __future__ import annotations

import argparse
import sys

import httpx


def assert_status(response: httpx.Response, expected: int) -> None:
    if response.status_code != expected:
        raise AssertionError(f"Expected {expected}, got {response.status_code}: {response.text}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live smoke test against the interview agent API.")
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        health = client.get("/health")
        assert_status(health, 200)

        start = client.post("/api/interviews", json={"skill": "Communication", "candidate_name": "Smoke Test"})
        assert_status(start, 200)
        interview = start.json()
        interview_id = interview["id"]

        replies = [
            "I explained a platform migration to a sales team by relating APIs to the product features they already sold every day. I paused after each section, asked them to summarize the risk in their own words, and updated the rollout FAQ based on their questions.",
            "During a disagreement on release timing, I repeated the other team's concerns back to them, clarified where our assumptions differed, and reframed the discussion around customer impact and rollback cost. That moved the conversation from opinions to trade-offs and we agreed on a phased launch.",
            "I prepare difficult feedback by gathering examples, separating impact from intent, and making the next step explicit. I deliver it privately, invite the other person to respond, and follow up with a concrete checkpoint to make sure the issue actually improves.",
        ]
        for answer in replies:
            reply = client.post(f"/api/interviews/{interview_id}/reply", json={"content": answer})
            assert_status(reply, 200)

        retrieved = client.get(f"/api/interviews/{interview_id}")
        assert_status(retrieved, 200)
        conversation = retrieved.json()
        if conversation["status"] != "completed":
            raise AssertionError(f"Interview did not complete: {conversation['status']}")

        feedback = client.post(
            "/api/feedback",
            json={
                "interview_id": interview_id,
                "evaluator_id": "smoke-test",
                "overall_quality": 4,
                "fairness": 4,
                "relevance": 4,
                "flags": [],
                "notes": "Smoke test feedback",
            },
        )
        assert_status(feedback, 200)

        print("Smoke test passed.")
        print(f"Interview ID: {interview_id}")
        print(f"Prompt version: {conversation['prompt_version']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        raise
