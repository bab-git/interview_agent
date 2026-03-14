from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models import InterviewPhase, InterviewStatus, Skill


class StartInterviewRequest(BaseModel):
    skill: Skill
    candidate_name: Optional[str] = None


class ReplyRequest(BaseModel):
    content: str = Field(min_length=1)


class ActivatePromptRequest(BaseModel):
    version: str = Field(min_length=1)


class MessageResponse(BaseModel):
    id: str
    role: str
    kind: str
    content: str
    question_index: Optional[int] = None
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvaluationResponse(BaseModel):
    verdict: str
    score: int
    reasoning: str
    missing_points: List[str] = Field(default_factory=list)
    follow_up: Optional[str] = None
    backend: str
    used_fallback: bool = False


class InterviewResponse(BaseModel):
    id: str
    candidate_name: Optional[str] = None
    skill: Skill
    status: InterviewStatus
    phase: InterviewPhase
    current_question_index: int
    clarification_count: int
    prompt_version: str
    llm_backend: str
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    question_set: List[Dict[str, Any]]
    messages: List[MessageResponse] = Field(default_factory=list)
    feedback_count: int = 0
    error_message: Optional[str] = None


class ReplyResponse(BaseModel):
    interview: InterviewResponse
    evaluation: EvaluationResponse
    agent_message: MessageResponse


class FeedbackSubmissionRequest(BaseModel):
    interview_id: str
    evaluator_id: Optional[str] = None
    overall_quality: int = Field(ge=1, le=5)
    fairness: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    flags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    comparison_target_id: Optional[str] = None
    preferred_conversation_id: Optional[str] = None


class FeedbackResponse(BaseModel):
    id: str
    interview_id: str
    evaluator_id: Optional[str] = None
    overall_quality: int
    fairness: int
    relevance: int
    flags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    comparison_target_id: Optional[str] = None
    preferred_conversation_id: Optional[str] = None
    created_at: datetime


class PromptVersionResponse(BaseModel):
    version: str
    description: str
    is_active: bool


class MetricsResponse(BaseModel):
    total_interviews: int
    completed_interviews: int
    active_interviews: int
    completion_rate: float
    average_reply_latency_ms: float


class HealthResponse(BaseModel):
    status: str
    database_path: str
    prompt_version: str
    llm_backend: str
    llm_reachable: Optional[bool] = None
