"""Deterministic demo-mode helpers for seeded public review sessions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable
from uuid import NAMESPACE_URL, uuid5

from app.config import Settings
from app.db import Repository
from app.models import InterviewPhase, InterviewStatus, MessageKind, MessageRole
from app.prompts import PromptStore


DEMO_BASE_TIME = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)


def _stable_id(seed: int, label: str) -> str:
    """Return a deterministic identifier for demo interviews and records."""
    return str(uuid5(NAMESPACE_URL, f"ai-interview-orchestration:{seed}:{label}"))


def _timestamp(seed: int, minutes: int) -> str:
    """Return a deterministic ISO-8601 timestamp anchored to the supplied seed."""
    base = DEMO_BASE_TIME + timedelta(days=seed % 11)
    return (base + timedelta(minutes=minutes)).isoformat()


def _message_metadata(seed: int, label: str, minutes: int, **metadata: Any) -> Dict[str, Any]:
    """Attach stable identifiers and timestamps to a seeded message payload."""
    return {
        "_id": _stable_id(seed, f"message:{label}"),
        "_created_at": _timestamp(seed, minutes),
        **metadata,
    }


def _add_message(
    repository: Repository,
    interview_id: str,
    seed: int,
    label: str,
    minutes: int,
    role: str,
    kind: str,
    content: str,
    question_index: int | None = None,
    **metadata: Any,
) -> None:
    """Persist one deterministic seeded transcript message."""
    repository.add_message(
        interview_id,
        role,
        kind,
        content,
        question_index=question_index,
        metadata=_message_metadata(seed, label, minutes, **metadata),
    )


def _seed_completed_trace_session(
    repository: Repository,
    seed: int,
    interview_id: str,
    prompt_version: str,
    questions: list[Dict[str, Any]],
) -> None:
    """Create a completed session that demonstrates clarify-then-advance behavior."""
    repository.create_interview(
        {
            "id": interview_id,
            "candidate_name": "Debugging Review Demo",
            "skill": "Problem Solving",
            "status": InterviewStatus.COMPLETED.value,
            "phase": InterviewPhase.COMPLETED.value,
            "current_question_index": 2,
            "clarification_count": 0,
            "prompt_version": prompt_version,
            "llm_backend": "MockBackend",
            "question_set": questions,
            "created_at": _timestamp(seed, 0),
            "updated_at": _timestamp(seed, 16),
            "completed_at": _timestamp(seed, 16),
            "latency_count": 4,
            "latency_total_ms": 214.0,
        }
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-welcome",
        0,
        MessageRole.AGENT.value,
        MessageKind.WELCOME.value,
        "Welcome to the interview workflow review. This session uses synthetic debugging and incident-response examples.",
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-question-1",
        1,
        MessageRole.AGENT.value,
        MessageKind.QUESTION.value,
        questions[0]["prompt"],
        question_index=0,
        question_id=questions[0]["id"],
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-answer-1a",
        2,
        MessageRole.CANDIDATE.value,
        MessageKind.ANSWER.value,
        "I traced a checkout bug, patched the service, and restored the workflow quickly.",
        question_index=0,
    )
    follow_up = "Can you add the constraints, the options you considered, and what changed after the fix shipped?"
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-evaluation-1a",
        3,
        MessageRole.SYSTEM.value,
        MessageKind.EVALUATION.value,
        "The response identifies the incident but does not yet show the trade-offs, validation steps, or outcome.",
        question_index=0,
        verdict="clarify",
        score=2,
        backend="mock",
        used_fallback=False,
        missing_points=["context", "trade-offs", "result"],
        follow_up=follow_up,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-clarification-1",
        4,
        MessageRole.AGENT.value,
        MessageKind.CLARIFICATION.value,
        follow_up,
        question_index=0,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-answer-1b",
        5,
        MessageRole.CANDIDATE.value,
        MessageKind.ANSWER.value,
        (
            "The bug came from a pricing cache that kept stale region data after a deployment. I compared failing "
            "checkout logs with the cache key diff, considered a hot patch versus a targeted rollback, chose the "
            "rollback because it restored consistency faster, and confirmed the fix with conversion metrics plus a "
            "regression test before we re-enabled the new path."
        ),
        question_index=0,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-evaluation-1b",
        6,
        MessageRole.SYSTEM.value,
        MessageKind.EVALUATION.value,
        "The answer now includes context, trade-offs, validation, and a measurable result, so the workflow can advance.",
        question_index=0,
        verdict="complete",
        score=4,
        backend="mock",
        used_fallback=False,
        missing_points=[],
        follow_up=None,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-question-2",
        7,
        MessageRole.AGENT.value,
        MessageKind.QUESTION.value,
        questions[1]["prompt"],
        question_index=1,
        question_id=questions[1]["id"],
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-answer-2",
        8,
        MessageRole.CANDIDATE.value,
        MessageKind.ANSWER.value,
        (
            "My first fix focused on retries, but the logs still showed a schema mismatch. I switched to reproducing "
            "the issue in staging, traced the serializer contract, corrected the payload mapping, and added a replay "
            "test so the same failure would surface before deployment."
        ),
        question_index=1,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-evaluation-2",
        9,
        MessageRole.SYSTEM.value,
        MessageKind.EVALUATION.value,
        "The response is specific about the failed first attempt, the recovery path, and the learning outcome.",
        question_index=1,
        verdict="complete",
        score=4,
        backend="mock",
        used_fallback=False,
        missing_points=[],
        follow_up=None,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-question-3",
        10,
        MessageRole.AGENT.value,
        MessageKind.QUESTION.value,
        questions[2]["prompt"],
        question_index=2,
        question_id=questions[2]["id"],
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-answer-3",
        11,
        MessageRole.CANDIDATE.value,
        MessageKind.ANSWER.value,
        (
            "During urgent incidents I restore the critical path first, then protect correctness with feature flags, "
            "rollback checkpoints, and explicit owners for verification. I narrate the risk trade-offs in the incident "
            "channel and close only after user-impact metrics show the system is stable again."
        ),
        question_index=2,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-evaluation-3",
        12,
        MessageRole.SYSTEM.value,
        MessageKind.EVALUATION.value,
        "The answer balances urgency, workflow control, and validation in a way that supports progression and review.",
        question_index=2,
        verdict="complete",
        score=5,
        backend="mock",
        used_fallback=False,
        missing_points=[],
        follow_up=None,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "trace-wrap-up",
        16,
        MessageRole.AGENT.value,
        MessageKind.WRAP_UP.value,
        "Thanks for completing the production-style prototype session. The evaluation summary and trace are ready for review.",
        question_index=2,
    )
    repository.create_feedback(
        {
            "id": _stable_id(seed, "feedback:trace"),
            "interview_id": interview_id,
            "evaluator_id": "portfolio-review",
            "overall_quality": 4,
            "fairness": 5,
            "relevance": 4,
            "flags": ["clarification_was_helpful"],
            "notes": "The clarification made the state transition and evaluation summary easy to inspect.",
            "created_at": _timestamp(seed, 18),
        }
    )


def _seed_fallback_session(
    repository: Repository,
    seed: int,
    interview_id: str,
    prompt_version: str,
    questions: list[Dict[str, Any]],
) -> None:
    """Create a completed session that records a fallback evaluation path."""
    repository.create_interview(
        {
            "id": interview_id,
            "candidate_name": "Fallback Review Demo",
            "skill": "Communication",
            "status": InterviewStatus.COMPLETED.value,
            "phase": InterviewPhase.COMPLETED.value,
            "current_question_index": 2,
            "clarification_count": 0,
            "prompt_version": prompt_version,
            "llm_backend": "MockBackend",
            "question_set": questions,
            "created_at": _timestamp(seed, 24),
            "updated_at": _timestamp(seed, 38),
            "completed_at": _timestamp(seed, 38),
            "latency_count": 4,
            "latency_total_ms": 243.0,
        }
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-welcome",
        24,
        MessageRole.AGENT.value,
        MessageKind.WELCOME.value,
        "Welcome to a seeded review session that demonstrates a recorded fallback decision path.",
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-question-1",
        25,
        MessageRole.AGENT.value,
        MessageKind.QUESTION.value,
        questions[0]["prompt"],
        question_index=0,
        question_id=questions[0]["id"],
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-answer-1a",
        26,
        MessageRole.CANDIDATE.value,
        MessageKind.ANSWER.value,
        "I explained the rollout and it helped the team.",
        question_index=0,
    )
    fallback_follow_up = questions[0]["fallback_probe"]
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-evaluation-1a",
        27,
        MessageRole.SYSTEM.value,
        MessageKind.EVALUATION.value,
        "A deterministic fallback path was used because the stored answer did not contain enough evidence to advance.",
        question_index=0,
        verdict="clarify",
        score=2,
        backend="heuristic",
        used_fallback=True,
        missing_points=["audience adaptation", "feedback loop", "outcome"],
        follow_up=fallback_follow_up,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-clarification-1",
        28,
        MessageRole.AGENT.value,
        MessageKind.CLARIFICATION.value,
        fallback_follow_up,
        question_index=0,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-answer-1b",
        29,
        MessageRole.CANDIDATE.value,
        MessageKind.ANSWER.value,
        (
            "I translated the platform migration into the support team's workflow, paused after each step for questions, "
            "and updated the launch FAQ based on what they repeated back to me. Ticket volume stayed flat during rollout, "
            "which showed the explanation landed."
        ),
        question_index=0,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-evaluation-1b",
        30,
        MessageRole.SYSTEM.value,
        MessageKind.EVALUATION.value,
        "The improved answer now includes audience adaptation, a feedback loop, and a measurable result.",
        question_index=0,
        verdict="complete",
        score=4,
        backend="mock",
        used_fallback=False,
        missing_points=[],
        follow_up=None,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-question-2",
        31,
        MessageRole.AGENT.value,
        MessageKind.QUESTION.value,
        questions[1]["prompt"],
        question_index=1,
        question_id=questions[1]["id"],
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-answer-2",
        32,
        MessageRole.CANDIDATE.value,
        MessageKind.ANSWER.value,
        (
            "During a rollout disagreement I summarized the support team's concern about customer confusion, reframed the "
            "discussion around ticket risk and rollback cost, and helped the group agree on a phased launch with clear "
            "checkpoints."
        ),
        question_index=1,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-evaluation-2",
        33,
        MessageRole.SYSTEM.value,
        MessageKind.EVALUATION.value,
        "The response is concrete about the communication tactic and the evidence that it changed the outcome.",
        question_index=1,
        verdict="complete",
        score=4,
        backend="mock",
        used_fallback=False,
        missing_points=[],
        follow_up=None,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-question-3",
        34,
        MessageRole.AGENT.value,
        MessageKind.QUESTION.value,
        questions[2]["prompt"],
        question_index=2,
        question_id=questions[2]["id"],
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-answer-3",
        35,
        MessageRole.CANDIDATE.value,
        MessageKind.ANSWER.value,
        (
            "When I deliver difficult feedback I use concrete examples, separate impact from intent, and agree on one "
            "follow-up checkpoint so the discussion leads to a measurable change instead of a vague reminder."
        ),
        question_index=2,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-evaluation-3",
        36,
        MessageRole.SYSTEM.value,
        MessageKind.EVALUATION.value,
        "The final answer is detailed enough to complete the session and supports a clear evaluation summary.",
        question_index=2,
        verdict="complete",
        score=4,
        backend="mock",
        used_fallback=False,
        missing_points=[],
        follow_up=None,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "fallback-wrap-up",
        38,
        MessageRole.AGENT.value,
        MessageKind.WRAP_UP.value,
        "Session complete. Reviewers can inspect the fallback activation and the later recovery in the trace panel.",
        question_index=2,
    )
    repository.create_feedback(
        {
            "id": _stable_id(seed, "feedback:fallback"),
            "interview_id": interview_id,
            "evaluator_id": "portfolio-review",
            "overall_quality": 3,
            "fairness": 4,
            "relevance": 3,
            "flags": ["weak_followup"],
            "notes": "The fallback path is clear, but one follow-up could ask for stronger evidence.",
            "created_at": _timestamp(seed, 40),
        }
    )


def _seed_active_session(
    repository: Repository,
    seed: int,
    interview_id: str,
    prompt_version: str,
    questions: list[Dict[str, Any]],
) -> None:
    """Create an in-progress session for the live demo tab."""
    repository.create_interview(
        {
            "id": interview_id,
            "candidate_name": "Open Clarification Demo",
            "skill": "Collaboration & Teamwork",
            "status": InterviewStatus.ACTIVE.value,
            "phase": InterviewPhase.CLARIFYING.value,
            "current_question_index": 0,
            "clarification_count": 1,
            "prompt_version": prompt_version,
            "llm_backend": "MockBackend",
            "question_set": questions,
            "created_at": _timestamp(seed, 44),
            "updated_at": _timestamp(seed, 48),
            "completed_at": None,
            "latency_count": 1,
            "latency_total_ms": 52.0,
        }
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "active-welcome",
        44,
        MessageRole.AGENT.value,
        MessageKind.WELCOME.value,
        "Welcome to a live seeded session. This one pauses on a clarification so you can continue the workflow manually.",
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "active-question-1",
        45,
        MessageRole.AGENT.value,
        MessageKind.QUESTION.value,
        questions[0]["prompt"],
        question_index=0,
        question_id=questions[0]["id"],
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "active-answer-1",
        46,
        MessageRole.CANDIDATE.value,
        MessageKind.ANSWER.value,
        "I kept the launch team aligned by sharing updates and resolving blockers as they came up.",
        question_index=0,
    )
    follow_up = "What operating rhythm kept the group aligned, and how did you respond when priorities conflicted?"
    _add_message(
        repository,
        interview_id,
        seed,
        "active-evaluation-1",
        47,
        MessageRole.SYSTEM.value,
        MessageKind.EVALUATION.value,
        "The answer hints at collaboration but still needs the operating rhythm, conflict handling, and outcome evidence.",
        question_index=0,
        verdict="clarify",
        score=2,
        backend="mock",
        used_fallback=False,
        missing_points=["alignment rhythm", "conflict handling", "outcome"],
        follow_up=follow_up,
    )
    _add_message(
        repository,
        interview_id,
        seed,
        "active-clarification-1",
        48,
        MessageRole.AGENT.value,
        MessageKind.CLARIFICATION.value,
        follow_up,
        question_index=0,
    )


def seed_demo_sessions(settings: Settings, repository: Repository, prompt_store: PromptStore) -> None:
    """Reset prompt state and insert deterministic demo interviews plus reviewer feedback."""
    prompt_store.activate("v2")
    prompt_v2 = prompt_store.load_version("v2")
    prompt_v1 = prompt_store.load_version("v1")
    _seed_completed_trace_session(
        repository,
        settings.demo_seed,
        _stable_id(settings.demo_seed, "interview:review-trace"),
        prompt_v2.version,
        prompt_v2.skill_questions("Problem Solving")[:3],
    )
    _seed_fallback_session(
        repository,
        settings.demo_seed,
        _stable_id(settings.demo_seed, "interview:fallback-path"),
        prompt_v1.version,
        prompt_v1.skill_questions("Communication")[:3],
    )
    _seed_active_session(
        repository,
        settings.demo_seed,
        _stable_id(settings.demo_seed, "interview:active-flow"),
        prompt_v2.version,
        prompt_v2.skill_questions("Collaboration & Teamwork")[:3],
    )


def ensure_demo_sessions(settings: Settings, repository: Repository, prompt_store: PromptStore) -> None:
    """Create demo data on first run, or rebuild it when reset-on-start is enabled."""
    if not settings.demo_mode:
        return
    if settings.demo_reset_on_start:
        repository.reset_db()
        seed_demo_sessions(settings, repository, prompt_store)
        return

    repository.init_db()
    if repository.list_interviews():
        return
    seed_demo_sessions(settings, repository, prompt_store)


def reset_demo_sessions(settings: Settings, repository: Repository, prompt_store: PromptStore) -> None:
    """Recreate the deterministic demo database and synthetic seed content."""
    repository.reset_db()
    seed_demo_sessions(settings, repository, prompt_store)


def demo_session_ids(seed: int) -> Iterable[str]:
    """Return stable public session identifiers for docs and scripted walkthroughs."""
    return (
        _stable_id(seed, "interview:review-trace"),
        _stable_id(seed, "interview:fallback-path"),
        _stable_id(seed, "interview:active-flow"),
    )
