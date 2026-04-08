from __future__ import annotations


def _complete_interview(client, skill: str, candidate_name: str) -> str:
    start = client.post("/api/interviews", json={"skill": skill, "candidate_name": candidate_name})
    interview_id = start.json()["id"]
    answers = [
        "I explained a complex migration by mapping the technical changes to customer workflows, collecting questions in real time, and using those questions to improve the rollout guide that the team used later.",
        "During a disagreement on release timing, I summarized the other side's concerns, reframed the discussion around customer impact, and proposed a phased rollout with rollback criteria that both teams could support.",
        "When I give difficult feedback, I use concrete examples, describe the impact, and agree on next steps plus a follow-up checkpoint so the conversation leads to a measurable improvement.",
    ]
    for answer in answers:
        response = client.post(f"/api/interviews/{interview_id}/reply", json={"content": answer})
        assert response.status_code == 200
    return interview_id


def test_prompt_create_api_generates_new_version_and_activates_it(client) -> None:
    response = client.post(
        "/api/prompts",
        json={
            "version": "v3",
            "description": "Created in test",
            "base_version": "v2",
            "activate": True,
            "skill_question_overrides": {
                "Problem Solving": [
                    {
                        "id": "ps1",
                        "prompt": "Tell me about a hard technical problem and the trade-offs you weighed.",
                    }
                ]
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["version"] == "v3"
    assert response.json()["is_active"] is True

    interview = client.post("/api/interviews", json={"skill": "Problem Solving"}).json()
    assert interview["prompt_version"] == "v3"
    assert "trade-offs" in interview["question_set"][0]["prompt"]


def test_feedback_summary_and_prompt_suggestions(client) -> None:
    interview_id = _complete_interview(client, "Communication", "Summary Candidate")
    feedback = client.post(
        "/api/feedback",
        json={
            "interview_id": interview_id,
            "evaluator_id": "reviewer-summary",
            "overall_quality": 3,
            "fairness": 3,
            "relevance": 4,
            "flags": ["weak_followup", "fairness_concern"],
            "notes": "Could use more objective guidance.",
        },
    )
    assert feedback.status_code == 200

    summary = client.get("/api/feedback/summary")
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["total_feedback"] == 1
    assert summary_payload["average_quality"] == 3.0
    assert summary_payload["common_flags"][0]["flag"] in {"weak_followup", "fairness_concern"}

    suggestions = client.get("/api/prompts/suggestions")
    assert suggestions.status_code == 200
    suggestion_titles = {item["title"] for item in suggestions.json()}
    assert "Strengthen clarification guidance" in suggestion_titles
    assert "Tighten fairness criteria" in suggestion_titles


def test_comparison_endpoint_and_preference_tracking(client) -> None:
    left_id = _complete_interview(client, "Communication", "Left Candidate")
    client.post("/api/prompts/activate", json={"version": "v2"})
    right_id = _complete_interview(client, "Communication", "Right Candidate")

    compare = client.get(f"/api/comparisons?left_id={left_id}&right_id={right_id}")
    assert compare.status_code == 200
    compare_payload = compare.json()
    assert compare_payload["same_skill"] is True
    assert compare_payload["same_prompt_version"] is False
    assert compare_payload["preference_counts"]["total_comparisons"] == 0

    feedback = client.post(
        "/api/comparisons/feedback",
        json={
            "left_interview_id": left_id,
            "right_interview_id": right_id,
            "preferred_conversation_id": right_id,
            "evaluator_id": "reviewer-compare",
            "overall_quality": 4,
            "fairness": 4,
            "relevance": 5,
            "flags": [],
            "notes": "The right-hand interview felt more precise.",
        },
    )
    assert feedback.status_code == 200

    after = client.get(f"/api/comparisons?left_id={left_id}&right_id={right_id}")
    assert after.status_code == 200
    counts = after.json()["preference_counts"]
    assert counts["right_preferred"] == 1
    assert counts["total_comparisons"] == 1
