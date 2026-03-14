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
    ComparisonFeedbackRequest,
    ComparisonResponse,
    CreatePromptVersionRequest,
    FeedbackSummaryResponse,
    FeedbackResponse,
    FeedbackSubmissionRequest,
    HealthResponse,
    InterviewResponse,
    MessageResponse,
    MetricsResponse,
    PreferenceCountsResponse,
    PromptVersionResponse,
    PromptSuggestionResponse,
    ReplyRequest,
    ReplyResponse,
    StartInterviewRequest,
)
from app.services.interview_engine import EvaluationResult, InterviewEngine
from app.services.llm import build_llm_backend
from app.services.review_analytics import ReviewAnalyticsService


configure_logging()

repository = Repository(settings)
prompt_store = PromptStore(settings)
llm_backend = build_llm_backend(settings)
engine = InterviewEngine(repository, prompt_store, llm_backend)
review_analytics = ReviewAnalyticsService(repository)

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


def _ensure_interview_exists(interview_id: str) -> Dict[str, Any]:
    try:
        return repository.get_interview(interview_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="interview not found") from exc


def _ensure_completed_interview(interview_id: str) -> Dict[str, Any]:
    interview = _ensure_interview_exists(interview_id)
    if interview["status"] != "completed":
        raise HTTPException(status_code=409, detail="interview must be completed for this action")
    return interview


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


@app.post("/api/prompts", response_model=PromptVersionResponse)
def create_prompt(request: CreatePromptVersionRequest) -> PromptVersionResponse:
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    try:
        prompt = prompt_store.create_version(payload)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PromptVersionResponse(
        version=prompt.version,
        description=prompt.description,
        is_active=prompt.version == prompt_store.active_version_name(),
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
    interview = _ensure_completed_interview(request.interview_id)
    if bool(request.comparison_target_id) != bool(request.preferred_conversation_id):
        raise HTTPException(
            status_code=400,
            detail="comparison_target_id and preferred_conversation_id must be provided together",
        )
    if request.comparison_target_id:
        _ensure_completed_interview(request.comparison_target_id)
        valid_preferences = {request.interview_id, request.comparison_target_id}
        if request.preferred_conversation_id not in valid_preferences:
            raise HTTPException(
                status_code=400,
                detail="preferred_conversation_id must match one of the compared interviews",
            )
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    feedback = repository.create_feedback(payload)
    return _feedback_response(feedback)


@app.get("/api/interviews/{interview_id}/feedback", response_model=List[FeedbackResponse])
def list_feedback(interview_id: str) -> List[FeedbackResponse]:
    _ensure_interview_exists(interview_id)
    feedback_items = repository.list_feedback(interview_id)
    return [_feedback_response(item) for item in feedback_items]


@app.get("/api/comparisons", response_model=ComparisonResponse)
def compare_interviews(
    left_id: str = Query(...),
    right_id: str = Query(...),
) -> ComparisonResponse:
    left = engine.get_interview(_ensure_completed_interview(left_id)["id"])
    right = engine.get_interview(_ensure_completed_interview(right_id)["id"])
    counts = repository.comparison_preference_counts(left_id, right_id)
    return ComparisonResponse(
        left=_interview_response(left),
        right=_interview_response(right),
        same_skill=left["skill"] == right["skill"],
        same_prompt_version=left["prompt_version"] == right["prompt_version"],
        preference_counts=PreferenceCountsResponse(**counts),
    )


@app.post("/api/comparisons/feedback", response_model=FeedbackResponse)
def submit_comparison_feedback(request: ComparisonFeedbackRequest) -> FeedbackResponse:
    left = _ensure_completed_interview(request.left_interview_id)
    _ensure_completed_interview(request.right_interview_id)
    if request.preferred_conversation_id not in {
        request.left_interview_id,
        request.right_interview_id,
    }:
        raise HTTPException(
            status_code=400,
            detail="preferred_conversation_id must match one of the compared interviews",
        )
    payload = {
        "interview_id": left["id"],
        "comparison_target_id": request.right_interview_id,
        "preferred_conversation_id": request.preferred_conversation_id,
        "evaluator_id": request.evaluator_id,
        "overall_quality": request.overall_quality,
        "fairness": request.fairness,
        "relevance": request.relevance,
        "flags": request.flags,
        "notes": request.notes,
    }
    feedback = repository.create_feedback(payload)
    return _feedback_response(feedback)


@app.get("/api/feedback/summary", response_model=FeedbackSummaryResponse)
def feedback_summary(
    skill: Optional[str] = Query(default=None),
    prompt_version: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
) -> FeedbackSummaryResponse:
    return FeedbackSummaryResponse(
        **review_analytics.feedback_summary(
            skill=skill,
            prompt_version=prompt_version,
            date_from=date_from,
            date_to=date_to,
        )
    )


@app.get("/api/prompts/suggestions", response_model=List[PromptSuggestionResponse])
def prompt_suggestions(
    skill: Optional[str] = Query(default=None),
    prompt_version: Optional[str] = Query(default=None),
) -> List[PromptSuggestionResponse]:
    suggestions = review_analytics.prompt_suggestions(skill=skill, prompt_version=prompt_version)
    return [PromptSuggestionResponse(**item) for item in suggestions]
