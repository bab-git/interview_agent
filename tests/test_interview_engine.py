from __future__ import annotations


def test_interview_requires_clarification_then_advances(client) -> None:
    start = client.post("/api/interviews", json={"skill": "Problem Solving", "candidate_name": "Candidate"})
    assert start.status_code == 200
    interview_id = start.json()["id"]

    short_reply = client.post(
        f"/api/interviews/{interview_id}/reply",
        json={"content": "I fixed a bug in production."},
    )
    assert short_reply.status_code == 200
    short_payload = short_reply.json()
    assert short_payload["evaluation"]["verdict"] == "clarify"
    assert short_payload["interview"]["phase"] == "clarifying"
    assert short_payload["interview"]["current_question_index"] == 0
    assert short_payload["agent_message"]["kind"] == "clarification"

    detailed_reply = client.post(
        f"/api/interviews/{interview_id}/reply",
        json={
            "content": "The production issue was caused by an indexing change because a migration ran out of order during deployment. I compared error logs, traced the failing query, rolled back the migration, and then added a deployment check plus a regression test so we could validate the fix before retrying."
        },
    )
    assert detailed_reply.status_code == 200
    detailed_payload = detailed_reply.json()
    assert detailed_payload["evaluation"]["verdict"] == "complete"
    assert detailed_payload["interview"]["current_question_index"] == 1
    assert detailed_payload["agent_message"]["kind"] == "question"
