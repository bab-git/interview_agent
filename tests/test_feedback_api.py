from __future__ import annotations


def test_feedback_is_persisted_and_retrievable(client) -> None:
    start = client.post("/api/interviews", json={"skill": "Communication", "candidate_name": "Candidate"})
    interview_id = start.json()["id"]

    replies = [
        "I explained a platform migration to a customer success team by replacing infrastructure jargon with customer workflow examples. I paused for questions, had them restate the rollout risk in their own words, and used their questions to update the final FAQ that guided the launch.",
        "During a disagreement on rollout timing, I listened to the support team's concern about ticket volume, summarized it back to them, and reframed the discussion around customer impact and rollback cost. That helped us agree on a phased launch with clearer support coverage.",
        "When delivering difficult feedback, I prepare concrete examples, state the impact clearly, and agree on one or two next steps before ending the conversation. I follow up soon after so the feedback becomes part of an improvement loop rather than a one-time comment.",
    ]
    for answer in replies:
        response = client.post(f"/api/interviews/{interview_id}/reply", json={"content": answer})
        assert response.status_code == 200

    feedback = client.post(
        "/api/feedback",
        json={
            "interview_id": interview_id,
            "evaluator_id": "reviewer",
            "overall_quality": 5,
            "fairness": 4,
            "relevance": 5,
            "flags": ["good_flow"],
            "notes": "Strong conversation",
        },
    )
    assert feedback.status_code == 200
    payload = feedback.json()
    assert payload["flags"] == ["good_flow"]

    retrieved = client.get(f"/api/interviews/{interview_id}/feedback")
    assert retrieved.status_code == 200
    items = retrieved.json()
    assert len(items) == 1
    assert items[0]["evaluator_id"] == "reviewer"
