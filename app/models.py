"""Shared enum types used by the API, engine, and persistence layers."""

from __future__ import annotations

from enum import Enum


class Skill(str, Enum):
    """Supported interview skill tracks."""

    PROBLEM_SOLVING = "Problem Solving"
    COMMUNICATION = "Communication"
    COLLABORATION = "Collaboration & Teamwork"


class InterviewStatus(str, Enum):
    """Lifecycle status for an interview session."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class InterviewPhase(str, Enum):
    """Fine-grained state inside the interview workflow."""

    ASKING = "asking"
    CLARIFYING = "clarifying"
    COMPLETED = "completed"


class MessageRole(str, Enum):
    """Actor responsible for a stored transcript message."""

    AGENT = "agent"
    CANDIDATE = "candidate"
    SYSTEM = "system"


class MessageKind(str, Enum):
    """Semantic category of a stored transcript message."""

    WELCOME = "welcome"
    QUESTION = "question"
    CLARIFICATION = "clarification"
    ANSWER = "answer"
    EVALUATION = "evaluation"
    WRAP_UP = "wrap_up"
