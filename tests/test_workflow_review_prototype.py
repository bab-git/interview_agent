from __future__ import annotations


def _start_session(client, skill: str = "Problem Solving") -> str:
    response = client.post(
        "/api/interviews",
        json={"skill": skill, "candidate_name": "Synthetic Review Session"},
    )
    assert response.status_code == 200
    return response.json()["id"]


def _complete_session(client, skill: str = "Communication") -> str:
    interview_id = _start_session(client, skill=skill)
    answers = [
        "I explained a platform migration to an operations team by mapping each technical change to their daily workflow, pausing for questions, and updating the launch guide from the points they repeated back to me.",
        "During a disagreement on release timing, I summarized the support team's concern, reframed the debate around customer impact and rollback cost, and helped the group agree on a phased launch with clear checkpoints.",
        "When delivering difficult feedback, I prepare concrete examples, describe the impact clearly, and close with one follow-up checkpoint so the conversation leads to an observable improvement.",
    ]
    for answer in answers:
        reply = client.post(f"/api/interviews/{interview_id}/reply", json={"content": answer})
        assert reply.status_code == 200
    return interview_id


def test_vague_answer_triggers_clarification_request(client) -> None:
    interview_id = _start_session(client)

    reply = client.post(
        f"/api/interviews/{interview_id}/reply",
        json={"content": "I fixed the issue quickly and moved on."},
    )

    assert reply.status_code == 200
    payload = reply.json()
    assert payload["evaluation"]["verdict"] == "clarify"
    assert payload["agent_message"]["kind"] == "clarification"
    assert payload["interview"]["phase"] == "clarifying"


def test_sufficient_answer_advances_to_the_next_stage(client) -> None:
    interview_id = _start_session(client)

    reply = client.post(
        f"/api/interviews/{interview_id}/reply",
        json={
            "content": (
                "The production incident came from a cache key mismatch after deployment. I compared failing logs, "
                "weighed a hot patch against a targeted rollback, chose the rollback because it restored consistency "
                "faster, and verified the recovery with error-rate metrics plus a regression test."
            )
        },
    )

    assert reply.status_code == 200
    payload = reply.json()
    assert payload["evaluation"]["verdict"] == "complete"
    assert payload["agent_message"]["kind"] == "question"
    assert payload["interview"]["current_question_index"] == 1
    assert payload["interview"]["phase"] == "asking"


def test_clarification_limit_is_respected_before_the_workflow_advances(client) -> None:
    interview_id = _start_session(client)

    first_reply = client.post(
        f"/api/interviews/{interview_id}/reply",
        json={"content": "I fixed a bug."},
    )
    assert first_reply.status_code == 200
    assert first_reply.json()["agent_message"]["kind"] == "clarification"

    second_reply = client.post(
        f"/api/interviews/{interview_id}/reply",
        json={"content": "I still kept the explanation short."},
    )

    assert second_reply.status_code == 200
    payload = second_reply.json()
    assert payload["evaluation"]["verdict"] == "clarify"
    assert payload["agent_message"]["kind"] == "question"
    assert payload["interview"]["current_question_index"] == 1
    assert payload["interview"]["phase"] == "asking"


def test_session_reloads_with_its_current_state_after_a_transition(client) -> None:
    interview_id = _start_session(client)

    client.post(
        f"/api/interviews/{interview_id}/reply",
        json={"content": "I found the issue and patched it."},
    )
    loaded = client.get(f"/api/interviews/{interview_id}")

    assert loaded.status_code == 200
    payload = loaded.json()
    assert payload["phase"] == "clarifying"
    assert payload["current_question_index"] == 0
    assert payload["clarification_count"] == 1


def test_evaluator_feedback_persists_and_reloads_for_review(client) -> None:
    interview_id = _complete_session(client)

    feedback = client.post(
        "/api/feedback",
        json={
            "interview_id": interview_id,
            "evaluator_id": "reviewer-a",
            "overall_quality": 4,
            "fairness": 5,
            "relevance": 4,
            "flags": ["clear_trace"],
            "notes": "The evaluation summary stayed easy to follow.",
        },
    )
    assert feedback.status_code == 200

    loaded = client.get(f"/api/interviews/{interview_id}/feedback")
    assert loaded.status_code == 200
    payload = loaded.json()
    assert len(payload) == 1
    assert payload[0]["flags"] == ["clear_trace"]
    assert payload[0]["notes"] == "The evaluation summary stayed easy to follow."


def test_prompt_version_is_stored_with_each_session(client) -> None:
    activate = client.post("/api/prompts/activate", json={"version": "v2"})
    assert activate.status_code == 200

    interview_id = _start_session(client)
    loaded = client.get(f"/api/interviews/{interview_id}")

    assert loaded.status_code == 200
    assert loaded.json()["prompt_version"] == "v2"


def test_fallback_path_is_recorded_when_the_primary_evaluator_fails(client, monkeypatch) -> None:
    import app.main as app_main

    interview_id = _start_session(client)

    def fail_complete(*args, **kwargs):
        raise RuntimeError("forced evaluator failure for test coverage")

    monkeypatch.setattr(app_main.engine.llm_backend, "complete", fail_complete)

    reply = client.post(
        f"/api/interviews/{interview_id}/reply",
        json={"content": "I fixed the outage."},
    )

    assert reply.status_code == 200
    payload = reply.json()
    assert payload["evaluation"]["used_fallback"] is True
    assert payload["evaluation"]["backend"] == "heuristic"

    loaded = client.get(f"/api/interviews/{interview_id}")
    reloaded_evaluations = [
        message
        for message in loaded.json()["messages"]
        if message["role"] == "system" and message["kind"] == "evaluation"
    ]
    assert reloaded_evaluations[-1]["metadata"]["used_fallback"] is True
    assert reloaded_evaluations[-1]["metadata"]["backend"] == "heuristic"


def test_reviewer_visible_summary_is_reproducible_after_reload(client) -> None:
    from app.gradio_ui import _format_evaluation, _format_review_trace

    interview_id = _start_session(client)

    reply = client.post(
        f"/api/interviews/{interview_id}/reply",
        json={"content": "I fixed the issue quickly and moved on."},
    )
    assert reply.status_code == 200
    live_messages = reply.json()["interview"]["messages"]

    loaded = client.get(f"/api/interviews/{interview_id}")
    assert loaded.status_code == 200
    stored_messages = loaded.json()["messages"]

    assert _format_evaluation(live_messages) == _format_evaluation(stored_messages)
    assert _format_review_trace(live_messages) == _format_review_trace(stored_messages)
