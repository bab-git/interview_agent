from __future__ import annotations

import importlib.util

from app.gradio_ui import _format_evaluation, _format_state, _format_transcript


def test_gradio_ui_formatters_render_interview_details() -> None:
    interview = {
        "id": "interview-123",
        "candidate_name": "Sam",
        "skill": "Problem Solving",
        "status": "active",
        "phase": "clarifying",
        "current_question_index": 0,
        "clarification_count": 1,
        "prompt_version": "v2",
        "llm_backend": "mock",
        "feedback_count": 0,
        "created_at": "2026-03-14T10:00:00+00:00",
        "completed_at": None,
        "question_set": [{"prompt": "Tell me about a hard debugging problem."}],
    }
    messages = [
        {"role": "agent", "kind": "welcome", "content": "Welcome to the interview.", "metadata": {}},
        {"role": "agent", "kind": "question", "content": "Tell me about a hard debugging problem.", "metadata": {}},
        {"role": "candidate", "kind": "answer", "content": "I narrowed it down step by step.", "metadata": {}},
        {
            "role": "system",
            "kind": "evaluation",
            "content": "The answer needs more specifics before moving on.",
            "metadata": {
                "verdict": "clarify",
                "score": 2,
                "backend": "mock",
                "used_fallback": False,
                "missing_points": ["context", "outcome"],
                "follow_up": "What changed after your fix shipped?",
            },
        },
    ]

    state = _format_state(interview)
    evaluation = _format_evaluation(messages)
    transcript = _format_transcript(messages)

    assert "Problem Solving" in state
    assert "clarifying" in state
    assert "Latest Evaluation" in evaluation
    assert "What changed after your fix shipped?" in evaluation
    assert "Candidate" in transcript
    assert "Verdict: `clarify`" in transcript


def test_ui_mount_is_available_when_gradio_is_installed(client) -> None:
    if importlib.util.find_spec("gradio") is None:
        return
    response = client.get("/ui")
    assert response.status_code == 200
    assert "Interview Agent Live Test" in response.text
