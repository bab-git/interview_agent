from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query

from app.config import settings
from app.db import Repository
from app.logging_utils import configure_logging
from app.prompts import PromptStore
from app.schemas import (
    ActivatePromptRequest,
    FeedbackResponse,
    FeedbackSubmissionRequest,
    HealthResponse,
    InterviewResponse,
    MessageResponse,
    MetricsResponse,
    PromptVersionResponse,
    ReplyRequest,
    ReplyResponse,
    StartInterviewRequest,
)
from app.services.interview_engine import EvaluationResult, InterviewEngine
from app.services.llm import build_llm_backend


configure_logging()

repository = Repository(settings)
prompt_store = PromptStore(settings)
llm_backend = build_llm_backend(settings)
engine = InterviewEngine(repository, prompt_store, llm_backend)

@asynccontextmanager
async def lifespan(_: FastAPI):
    repository.init_db()
    prompt_store.active_version_name()
    yield


app = FastAPI(title="Production Interview Agent", version="1.0.0", lifespan=lifespan)


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _message_response(message: Dict[str, Any]) -> MessageResponse:
    return MessageResponse(
        id=message["id"],
        role=message["role"],
        kind=message["kind"],
        content=message["content"],
        question_index=message["question_index"],
        created_at=_parse_datetime(message["created_at"]),
        metadata=message.get("metadata", {}),
    )


def _interview_response(interview: Dict[str, Any]) -> InterviewResponse:
    return InterviewResponse(
        id=interview["id"],
        candidate_name=interview.get("candidate_name"),
        skill=interview["skill"],
        status=interview["status"],
        phase=interview["phase"],
        current_question_index=interview["current_question_index"],
        clarification_count=interview["clarification_count"],
        prompt_version=interview["prompt_version"],
        llm_backend=interview["llm_backend"],
        created_at=_parse_datetime(interview["created_at"]),
        updated_at=_parse_datetime(interview["updated_at"]),
        completed_at=_parse_datetime(interview["completed_at"]),
        question_set=interview["question_set"],
        messages=[_message_response(message) for message in interview.get("messages", [])],
        feedback_count=interview.get("feedback_count", 0),
        error_message=interview.get("error_message"),
    )


def _feedback_response(feedback: Dict[str, Any]) -> FeedbackResponse:
    return FeedbackResponse(
        id=feedback["id"],
        interview_id=feedback["interview_id"],
        evaluator_id=feedback.get("evaluator_id"),
        overall_quality=feedback["overall_quality"],
        fairness=feedback["fairness"],
        relevance=feedback["relevance"],
        flags=feedback.get("flags", []),
        notes=feedback.get("notes"),
        comparison_target_id=feedback.get("comparison_target_id"),
        preferred_conversation_id=feedback.get("preferred_conversation_id"),
        created_at=_parse_datetime(feedback["created_at"]),
    )


def _evaluation_response(evaluation: EvaluationResult) -> Dict[str, Any]:
    return {
        "verdict": evaluation.verdict,
        "score": evaluation.score,
        "reasoning": evaluation.reasoning,
        "missing_points": evaluation.missing_points,
        "follow_up": evaluation.follow_up,
        "backend": evaluation.backend,
        "used_fallback": evaluation.used_fallback,
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    repository.init_db()
    prompt = prompt_store.load_active()
    return HealthResponse(
        status="ok",
        database_path=str(settings.db_path),
        prompt_version=prompt.version,
        llm_backend=settings.llm_backend,
        llm_reachable=llm_backend.is_reachable(),
    )


@app.get("/api/metrics", response_model=MetricsResponse)
def metrics() -> MetricsResponse:
    return MetricsResponse(**repository.metrics())


@app.get("/api/prompts", response_model=List[PromptVersionResponse])
def list_prompts() -> List[PromptVersionResponse]:
    active = prompt_store.active_version_name()
    return [
        PromptVersionResponse(
            version=prompt.version,
            description=prompt.description,
            is_active=prompt.version == active,
        )
        for prompt in prompt_store.list_versions()
    ]


@app.post("/api/prompts/activate", response_model=PromptVersionResponse)
def activate_prompt(request: ActivatePromptRequest) -> PromptVersionResponse:
    try:
        prompt = prompt_store.activate(request.version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PromptVersionResponse(
        version=prompt.version,
        description=prompt.description,
        is_active=True,
    )


@app.post("/api/interviews", response_model=InterviewResponse)
def start_interview(request: StartInterviewRequest) -> InterviewResponse:
    interview = engine.start_interview(request.skill.value, request.candidate_name)
    return _interview_response(interview)


@app.get("/api/interviews", response_model=List[InterviewResponse])
def list_interviews(
    skill: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    reviewed: Optional[bool] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    prompt_version: Optional[str] = Query(default=None),
) -> List[InterviewResponse]:
    interviews = repository.list_interviews(
        skill=skill,
        status=status,
        reviewed=reviewed,
        date_from=date_from,
        date_to=date_to,
        prompt_version=prompt_version,
    )
    return [_interview_response(engine.get_interview(interview["id"])) for interview in interviews]


@app.get("/api/interviews/{interview_id}", response_model=InterviewResponse)
def get_interview(interview_id: str) -> InterviewResponse:
    try:
        interview = engine.get_interview(interview_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="interview not found") from exc
    return _interview_response(interview)


@app.post("/api/interviews/{interview_id}/reply", response_model=ReplyResponse)
def reply(interview_id: str, request: ReplyRequest) -> ReplyResponse:
    try:
        response = engine.reply(interview_id, request.content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="interview not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ReplyResponse(
        interview=_interview_response(response["interview"]),
        evaluation=_evaluation_response(response["evaluation"]),
        agent_message=_message_response(response["agent_message"]),
    )


@app.post("/api/feedback", response_model=FeedbackResponse)
def submit_feedback(request: FeedbackSubmissionRequest) -> FeedbackResponse:
    try:
        interview = repository.get_interview(request.interview_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="interview not found") from exc
    if interview["status"] != "completed":
        raise HTTPException(status_code=409, detail="feedback is only allowed for completed interviews")
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    feedback = repository.create_feedback(payload)
    return _feedback_response(feedback)


@app.get("/api/interviews/{interview_id}/feedback", response_model=List[FeedbackResponse])
def list_feedback(interview_id: str) -> List[FeedbackResponse]:
    try:
        repository.get_interview(interview_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="interview not found") from exc
    feedback_items = repository.list_feedback(interview_id)
    return [_feedback_response(item) for item in feedback_items]
