"""Stateful interview orchestration for asking, evaluating, and advancing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.db import Repository, utc_now_text
from app.logging_utils import log_event
from app.models import InterviewPhase, InterviewStatus, MessageKind, MessageRole
from app.prompts import PromptStore, PromptVersion
from app.services.llm import LLMBackend


@dataclass
class EvaluationResult:
    """Normalized evaluation output used by the engine and API layer."""

    verdict: str
    score: int
    reasoning: str
    missing_points: List[str]
    follow_up: Optional[str]
    backend: str
    used_fallback: bool


class InterviewEngine:
    """Coordinate interview state transitions, transcript storage, and evaluation."""

    def __init__(
        self,
        repository: Repository,
        prompt_store: PromptStore,
        llm_backend: LLMBackend,
    ):
        self.repository = repository
        self.prompt_store = prompt_store
        self.llm_backend = llm_backend

    def _log_transition(
        self,
        *,
        session_id: str,
        current_state: str,
        next_state: str,
        prompt_version: str,
        evaluator_source: str,
        fallback_used: bool,
        clarification_count: int,
        question_index: int,
        action_taken: str,
    ) -> None:
        """Emit one structured workflow log entry for a session transition."""
        log_event(
            "session_transition",
            session_id=session_id,
            current_state=current_state,
            next_state=next_state,
            prompt_version=prompt_version,
            evaluator_source=evaluator_source,
            fallback_used=fallback_used,
            clarification_count=clarification_count,
            question_index=question_index,
            action_taken=action_taken,
        )

    def start_interview(self, skill: str, candidate_name: Optional[str] = None) -> Dict[str, Any]:
        """Create a new interview, persist its initial state, and ask question one."""
        prompt = self.prompt_store.load_active()
        questions = prompt.skill_questions(skill)[:3]
        interview = self.repository.create_interview(
            {
                "candidate_name": candidate_name,
                "skill": skill,
                "status": InterviewStatus.ACTIVE.value,
                "phase": InterviewPhase.ASKING.value,
                "current_question_index": 0,
                "clarification_count": 0,
                "prompt_version": prompt.version,
                "llm_backend": self.llm_backend.__class__.__name__,
                "question_set": questions,
            }
        )
        self.repository.add_message(
            interview["id"],
            MessageRole.AGENT.value,
            MessageKind.WELCOME.value,
            prompt.welcome_message(skill),
        )
        self.repository.add_message(
            interview["id"],
            MessageRole.AGENT.value,
            MessageKind.QUESTION.value,
            questions[0]["prompt"],
            question_index=0,
            metadata={"question_id": questions[0]["id"]},
        )
        self._log_transition(
            session_id=interview["id"],
            current_state="initialized",
            next_state=InterviewPhase.ASKING.value,
            prompt_version=prompt.version,
            evaluator_source=self.llm_backend.__class__.__name__,
            fallback_used=False,
            clarification_count=0,
            question_index=0,
            action_taken="start_session",
        )
        return self.get_interview(interview["id"])

    def get_interview(self, interview_id: str) -> Dict[str, Any]:
        """Load an interview together with its transcript and feedback count."""
        interview = self.repository.get_interview(interview_id)
        interview["messages"] = self.repository.list_messages(interview_id)
        interview["feedback_count"] = self.repository.feedback_count(interview_id)
        return interview

    def reply(self, interview_id: str, content: str) -> Dict[str, Any]:
        """Store a candidate reply, evaluate it, and advance the state machine."""
        interview = self.repository.get_interview(interview_id)
        if interview["status"] != InterviewStatus.ACTIVE.value:
            raise ValueError("interview is not active")

        question_index = interview["current_question_index"]
        current_question = interview["question_set"][question_index]
        prompt = self.prompt_store.load_version(interview["prompt_version"])

        self.repository.add_message(
            interview_id,
            MessageRole.CANDIDATE.value,
            MessageKind.ANSWER.value,
            content.strip(),
            question_index=question_index,
        )

        import time

        started = time.perf_counter()
        evaluation = self.evaluate_answer(prompt, current_question, content)
        latency_ms = (time.perf_counter() - started) * 1000
        self.repository.append_latency(interview_id, latency_ms)

        self.repository.add_message(
            interview_id,
            MessageRole.SYSTEM.value,
            MessageKind.EVALUATION.value,
            evaluation.reasoning,
            question_index=question_index,
            metadata={
                "verdict": evaluation.verdict,
                "score": evaluation.score,
                "missing_points": evaluation.missing_points,
                "follow_up": evaluation.follow_up,
                "backend": evaluation.backend,
                "used_fallback": evaluation.used_fallback,
            },
        )

        if evaluation.verdict == "clarify" and interview["clarification_count"] < prompt.max_clarifications:
            clarification = evaluation.follow_up or current_question["fallback_probe"]
            next_clarification_count = interview["clarification_count"] + 1
            self.repository.update_interview(
                interview_id,
                phase=InterviewPhase.CLARIFYING.value,
                clarification_count=next_clarification_count,
            )
            agent_message = self.repository.add_message(
                interview_id,
                MessageRole.AGENT.value,
                MessageKind.CLARIFICATION.value,
                clarification,
                question_index=question_index,
            )
            self._log_transition(
                session_id=interview_id,
                current_state=interview["phase"],
                next_state=InterviewPhase.CLARIFYING.value,
                prompt_version=interview["prompt_version"],
                evaluator_source=evaluation.backend,
                fallback_used=evaluation.used_fallback,
                clarification_count=next_clarification_count,
                question_index=question_index,
                action_taken="clarify",
            )
        else:
            next_index = question_index + 1
            if next_index < len(interview["question_set"]):
                self.repository.update_interview(
                    interview_id,
                    phase=InterviewPhase.ASKING.value,
                    current_question_index=next_index,
                    clarification_count=0,
                )
                next_question = interview["question_set"][next_index]
                agent_message = self.repository.add_message(
                    interview_id,
                    MessageRole.AGENT.value,
                    MessageKind.QUESTION.value,
                    next_question["prompt"],
                    question_index=next_index,
                    metadata={"question_id": next_question["id"]},
                )
                self._log_transition(
                    session_id=interview_id,
                    current_state=interview["phase"],
                    next_state=InterviewPhase.ASKING.value,
                    prompt_version=interview["prompt_version"],
                    evaluator_source=evaluation.backend,
                    fallback_used=evaluation.used_fallback,
                    clarification_count=0,
                    question_index=next_index,
                    action_taken="advance",
                )
            else:
                self.repository.update_interview(
                    interview_id,
                    phase=InterviewPhase.COMPLETED.value,
                    status=InterviewStatus.COMPLETED.value,
                    completed_at=utc_now_text(),
                    clarification_count=interview["clarification_count"],
                )
                agent_message = self.repository.add_message(
                    interview_id,
                    MessageRole.AGENT.value,
                    MessageKind.WRAP_UP.value,
                    prompt.wrap_up_message(interview["skill"]),
                    question_index=question_index,
                )
                self._log_transition(
                    session_id=interview_id,
                    current_state=interview["phase"],
                    next_state=InterviewPhase.COMPLETED.value,
                    prompt_version=interview["prompt_version"],
                    evaluator_source=evaluation.backend,
                    fallback_used=evaluation.used_fallback,
                    clarification_count=interview["clarification_count"],
                    question_index=question_index,
                    action_taken="complete_session",
                )

        return {
            "interview": self.get_interview(interview_id),
            "evaluation": evaluation,
            "agent_message": agent_message,
        }

    def evaluate_answer(
        self,
        prompt: PromptVersion,
        question: Dict[str, Any],
        answer: str,
    ) -> EvaluationResult:
        """Evaluate one answer with the configured LLM and a heuristic fallback."""
        heuristic = self._heuristic_evaluation(question, answer)
        system_prompt = prompt.raw["evaluation"]["system_prompt"]
        user_prompt = json.dumps(
            {
                "question": question["prompt"],
                "evaluation_focus": question["evaluation_focus"],
                "fallback_probe": question["fallback_probe"],
                "answer": answer,
                "clarification_policy": prompt.raw["clarification"],
                "heuristic_hint": heuristic,
            }
        )
        try:
            result = self.llm_backend.complete(system_prompt, user_prompt)
            data = json.loads(result.content)
            evaluation = EvaluationResult(
                verdict=data["verdict"],
                score=int(data["score"]),
                reasoning=data["reasoning"],
                missing_points=list(data.get("missing_points", [])),
                follow_up=data.get("follow_up"),
                backend=result.backend,
                used_fallback=False,
            )
            return evaluation
        except Exception as exc:
            log_event("evaluation_fallback_used", error=str(exc), question_id=question["id"])
            return EvaluationResult(
                verdict=heuristic["verdict"],
                score=heuristic["score"],
                reasoning=heuristic["reasoning"],
                missing_points=heuristic["missing_points"],
                follow_up=heuristic["follow_up"],
                backend="heuristic",
                used_fallback=True,
            )

    def _heuristic_evaluation(self, question: Dict[str, Any], answer: str) -> Dict[str, Any]:
        """Provide a deterministic backup evaluator when the LLM path fails."""
        stripped = answer.strip()
        word_count = len([token for token in stripped.split() if token])
        focus = question["evaluation_focus"]
        missing_points: List[str] = []
        if word_count < 30:
            missing_points.extend(focus[:3])
        if "because" not in stripped.lower() and "so" not in stripped.lower():
            missing_points.append("reasoning")
        if missing_points:
            deduped = list(dict.fromkeys(missing_points))
            return {
                "verdict": "clarify",
                "score": 2 if word_count < 30 else 3,
                "reasoning": "The answer needs more specifics before moving on.",
                "missing_points": deduped,
                "follow_up": question["fallback_probe"],
            }
        return {
            "verdict": "complete",
            "score": 4,
            "reasoning": "The answer includes enough detail to continue.",
            "missing_points": [],
            "follow_up": None,
        }
