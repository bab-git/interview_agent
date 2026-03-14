from __future__ import annotations


def test_full_interview_flow_and_discovery_filters(client) -> None:
    start = client.post(
        "/api/interviews",
        json={"skill": "Collaboration & Teamwork", "candidate_name": "Candidate"},
    )
    assert start.status_code == 200
    interview = start.json()
    interview_id = interview["id"]
    assert interview["prompt_version"] == "v1"

    replies = [
        "I coordinated a launch across engineering, design, and support because each group had a different dependency and timeline. I ran a weekly risks review, kept decisions in a shared doc, and resolved conflicts by linking every change back to the launch metric we all owned together.",
        "A teammate was blocked on a flaky integration test suite, so I first helped isolate whether the issue was data, environment, or timing related. We paired on the diagnosis, documented the reproduction steps, and split the fix so they still owned the implementation while I unblocked the surrounding tooling.",
        "During deadline pressure, strong team ownership means making responsibilities explicit, escalating early when assumptions break, and keeping shared status visible. In one launch, I owned the release checklist, another teammate handled observability, and after the incident we turned the gaps into action items with owners and dates.",
    ]
    for answer in replies:
        reply = client.post(f"/api/interviews/{interview_id}/reply", json={"content": answer})
        assert reply.status_code == 200

    retrieved = client.get(f"/api/interviews/{interview_id}")
    assert retrieved.status_code == 200
    conversation = retrieved.json()
    assert conversation["status"] == "completed"
    assert len(conversation["messages"]) >= 8

    review = client.post(
        "/api/feedback",
        json={
            "interview_id": interview_id,
            "evaluator_id": "reviewer-a",
            "overall_quality": 4,
            "fairness": 5,
            "relevance": 4,
            "flags": ["well_scoped"],
            "notes": "Helpful interview flow",
        },
    )
    assert review.status_code == 200

    by_skill = client.get("/api/interviews", params={"skill": "Collaboration & Teamwork", "reviewed": "true"})
    assert by_skill.status_code == 200
    items = by_skill.json()
    assert len(items) == 1
    assert items[0]["id"] == interview_id

    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["completed_interviews"] >= 1
