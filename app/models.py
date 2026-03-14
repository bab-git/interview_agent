from __future__ import annotations

from enum import Enum


class Skill(str, Enum):
    PROBLEM_SOLVING = "Problem Solving"
    COMMUNICATION = "Communication"
    COLLABORATION = "Collaboration & Teamwork"


class InterviewStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class InterviewPhase(str, Enum):
    ASKING = "asking"
    CLARIFYING = "clarifying"
    COMPLETED = "completed"


class MessageRole(str, Enum):
    AGENT = "agent"
    CANDIDATE = "candidate"
    SYSTEM = "system"


class MessageKind(str, Enum):
    WELCOME = "welcome"
    QUESTION = "question"
    CLARIFICATION = "clarification"
    ANSWER = "answer"
    EVALUATION = "evaluation"
    WRAP_UP = "wrap_up"
