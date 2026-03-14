from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from app.db import Repository


def _average(total: float, count: int) -> float:
    return round((total / count) if count else 0.0, 2)


class ReviewAnalyticsService:
    def __init__(self, repository: Repository):
        self.repository = repository

    def feedback_summary(
        self,
        skill: Optional[str] = None,
        prompt_version: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows = self.repository.list_feedback_with_context(
            skill=skill,
            prompt_version=prompt_version,
            date_from=date_from,
            date_to=date_to,
        )
        total_feedback = len(rows)
        reviewed_interviews = len({row["interview_id"] for row in rows})

        flag_counter: Counter[str] = Counter()
        totals = {"overall_quality": 0.0, "fairness": 0.0, "relevance": 0.0}
        by_skill: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"count": 0, "overall_quality": 0.0, "fairness": 0.0, "relevance": 0.0}
        )
        by_prompt: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"count": 0, "overall_quality": 0.0, "fairness": 0.0, "relevance": 0.0}
        )

        for row in rows:
            totals["overall_quality"] += row["overall_quality"]
            totals["fairness"] += row["fairness"]
            totals["relevance"] += row["relevance"]
            for flag in row.get("flags", []):
                flag_counter[flag] += 1

            skill_bucket = by_skill[row["skill"]]
            skill_bucket["count"] += 1
            skill_bucket["overall_quality"] += row["overall_quality"]
            skill_bucket["fairness"] += row["fairness"]
            skill_bucket["relevance"] += row["relevance"]

            prompt_bucket = by_prompt[row["prompt_version"]]
            prompt_bucket["count"] += 1
            prompt_bucket["overall_quality"] += row["overall_quality"]
            prompt_bucket["fairness"] += row["fairness"]
            prompt_bucket["relevance"] += row["relevance"]

        return {
            "total_feedback": total_feedback,
            "reviewed_interviews": reviewed_interviews,
            "average_quality": _average(totals["overall_quality"], total_feedback),
            "average_fairness": _average(totals["fairness"], total_feedback),
            "average_relevance": _average(totals["relevance"], total_feedback),
            "common_flags": [
                {"flag": flag, "count": count} for flag, count in flag_counter.most_common(10)
            ],
            "by_skill": [
                {
                    "key": key,
                    "feedback_count": int(bucket["count"]),
                    "average_quality": _average(bucket["overall_quality"], int(bucket["count"])),
                    "average_fairness": _average(bucket["fairness"], int(bucket["count"])),
                    "average_relevance": _average(bucket["relevance"], int(bucket["count"])),
                }
                for key, bucket in sorted(by_skill.items())
            ],
            "by_prompt_version": [
                {
                    "key": key,
                    "feedback_count": int(bucket["count"]),
                    "average_quality": _average(bucket["overall_quality"], int(bucket["count"])),
                    "average_fairness": _average(bucket["fairness"], int(bucket["count"])),
                    "average_relevance": _average(bucket["relevance"], int(bucket["count"])),
                }
                for key, bucket in sorted(by_prompt.items())
            ],
        }

    def prompt_suggestions(
        self,
        skill: Optional[str] = None,
        prompt_version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        summary = self.feedback_summary(skill=skill, prompt_version=prompt_version)
        scope = skill or prompt_version or "global"
        suggestions: List[Dict[str, Any]] = []
        flags = {item["flag"]: item["count"] for item in summary["common_flags"]}

        if summary["total_feedback"] == 0:
            return [
                {
                    "title": "Collect more evaluator data",
                    "priority": "low",
                    "target_scope": scope,
                    "evidence": ["No feedback records are available yet."],
                    "suggested_change": "Run more reviewed interviews before drafting prompt changes.",
                }
            ]

        if summary["average_quality"] < 4.0 or flags.get("weak_followup", 0) > 0:
            suggestions.append(
                {
                    "title": "Strengthen clarification guidance",
                    "priority": "high",
                    "target_scope": scope,
                    "evidence": [
                        f"Average quality is {summary['average_quality']}.",
                        f"Weak follow-up flags observed: {flags.get('weak_followup', 0)}.",
                    ],
                    "suggested_change": (
                        "Update the evaluation prompt so clarifications explicitly ask for context, "
                        "decision process, and outcome before moving on."
                    ),
                }
            )

        if summary["average_fairness"] < 4.0 or flags.get("bias", 0) > 0 or flags.get("fairness_concern", 0) > 0:
            suggestions.append(
                {
                    "title": "Tighten fairness criteria",
                    "priority": "high",
                    "target_scope": scope,
                    "evidence": [
                        f"Average fairness is {summary['average_fairness']}.",
                        f"Bias-related flags observed: {flags.get('bias', 0) + flags.get('fairness_concern', 0)}.",
                    ],
                    "suggested_change": (
                        "Add prompt instructions requiring objective, behavior-based evaluation and "
                        "explicitly prohibiting assumptions about background, personality, or identity."
                    ),
                }
            )

        if summary["average_relevance"] < 4.0 or flags.get("irrelevant_question", 0) > 0:
            suggestions.append(
                {
                    "title": "Improve skill-to-question relevance",
                    "priority": "medium",
                    "target_scope": scope,
                    "evidence": [
                        f"Average relevance is {summary['average_relevance']}.",
                        f"Irrelevant question flags observed: {flags.get('irrelevant_question', 0)}.",
                    ],
                    "suggested_change": (
                        "Revise the skill question set so each prompt more directly targets the selected skill "
                        "and reminds the evaluator what evidence a strong answer should include."
                    ),
                }
            )

        if not suggestions:
            suggestions.append(
                {
                    "title": "No urgent prompt change detected",
                    "priority": "low",
                    "target_scope": scope,
                    "evidence": [
                        f"Average quality is {summary['average_quality']}.",
                        f"Average fairness is {summary['average_fairness']}.",
                        f"Average relevance is {summary['average_relevance']}.",
                    ],
                    "suggested_change": (
                        "Keep the current prompt as the baseline and continue collecting evaluator feedback."
                    ),
                }
            )

        return suggestions
