from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.config import Settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_text() -> str:
    return utc_now().isoformat()


class Repository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.settings.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS interviews (
                    id TEXT PRIMARY KEY,
                    candidate_name TEXT,
                    skill TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    current_question_index INTEGER NOT NULL,
                    clarification_count INTEGER NOT NULL,
                    prompt_version TEXT NOT NULL,
                    llm_backend TEXT NOT NULL,
                    question_set_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    error_message TEXT,
                    latency_count INTEGER NOT NULL DEFAULT 0,
                    latency_total_ms REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    question_index INTEGER,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY,
                    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
                    evaluator_id TEXT,
                    overall_quality INTEGER NOT NULL,
                    fairness INTEGER NOT NULL,
                    relevance INTEGER NOT NULL,
                    flags_json TEXT NOT NULL,
                    notes TEXT,
                    comparison_target_id TEXT,
                    preferred_conversation_id TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_interview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        interview_id = payload.get("id") or str(uuid.uuid4())
        now = utc_now_text()
        record = {
            "id": interview_id,
            "candidate_name": payload.get("candidate_name"),
            "skill": payload["skill"],
            "status": payload["status"],
            "phase": payload["phase"],
            "current_question_index": payload["current_question_index"],
            "clarification_count": payload["clarification_count"],
            "prompt_version": payload["prompt_version"],
            "llm_backend": payload["llm_backend"],
            "question_set_json": json.dumps(payload["question_set"]),
            "created_at": now,
            "updated_at": now,
            "completed_at": payload.get("completed_at"),
            "error_message": payload.get("error_message"),
            "latency_count": 0,
            "latency_total_ms": 0.0,
        }
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO interviews (
                    id, candidate_name, skill, status, phase, current_question_index,
                    clarification_count, prompt_version, llm_backend, question_set_json,
                    created_at, updated_at, completed_at, error_message, latency_count,
                    latency_total_ms
                )
                VALUES (
                    :id, :candidate_name, :skill, :status, :phase, :current_question_index,
                    :clarification_count, :prompt_version, :llm_backend, :question_set_json,
                    :created_at, :updated_at, :completed_at, :error_message, :latency_count,
                    :latency_total_ms
                )
                """,
                record,
            )
        return self.get_interview(interview_id)

    def update_interview(self, interview_id: str, **changes: Any) -> Dict[str, Any]:
        changes["updated_at"] = utc_now_text()
        assignments = ", ".join(f"{column} = :{column}" for column in changes)
        params = dict(changes)
        params["id"] = interview_id
        with self.connection() as conn:
            conn.execute(f"UPDATE interviews SET {assignments} WHERE id = :id", params)
        return self.get_interview(interview_id)

    def append_latency(self, interview_id: str, latency_ms: float) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE interviews
                SET latency_count = latency_count + 1,
                    latency_total_ms = latency_total_ms + ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (latency_ms, utc_now_text(), interview_id),
            )

    def add_message(
        self,
        interview_id: str,
        role: str,
        kind: str,
        content: str,
        question_index: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "interview_id": interview_id,
            "role": role,
            "kind": kind,
            "question_index": question_index,
            "content": content,
            "created_at": utc_now_text(),
            "metadata_json": json.dumps(metadata or {}),
        }
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    id, interview_id, role, kind, question_index, content, created_at, metadata_json
                ) VALUES (
                    :id, :interview_id, :role, :kind, :question_index, :content, :created_at, :metadata_json
                )
                """,
                record,
            )
        return self.get_message(record["id"])

    def get_message(self, message_id: str) -> Dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            raise KeyError("message not found")
        return self._message_row_to_dict(row)

    def get_interview(self, interview_id: str) -> Dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM interviews WHERE id = ?", (interview_id,)).fetchone()
        if row is None:
            raise KeyError("interview not found")
        return self._interview_row_to_dict(row)

    def list_messages(self, interview_id: str) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE interview_id = ? ORDER BY created_at ASC",
                (interview_id,),
            ).fetchall()
        return [self._message_row_to_dict(row) for row in rows]

    def list_interviews(
        self,
        skill: Optional[str] = None,
        status: Optional[str] = None,
        reviewed: Optional[bool] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        prompt_version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        conditions = []
        params: List[Any] = []
        if skill:
            conditions.append("skill = ?")
            params.append(skill)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if date_from:
            conditions.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("created_at <= ?")
            params.append(date_to)
        if prompt_version:
            conditions.append("prompt_version = ?")
            params.append(prompt_version)
        if reviewed is not None:
            operator = ">" if reviewed else "="
            conditions.append(
                f"(SELECT COUNT(*) FROM feedback WHERE feedback.interview_id = interviews.id) {operator} 0"
            )
        query = "SELECT * FROM interviews"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._interview_row_to_dict(row) for row in rows]

    def feedback_count(self, interview_id: str) -> int:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM feedback WHERE interview_id = ?",
                (interview_id,),
            ).fetchone()
        return int(row["count"])

    def create_feedback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "interview_id": payload["interview_id"],
            "evaluator_id": payload.get("evaluator_id"),
            "overall_quality": payload["overall_quality"],
            "fairness": payload["fairness"],
            "relevance": payload["relevance"],
            "flags_json": json.dumps(payload.get("flags", [])),
            "notes": payload.get("notes"),
            "comparison_target_id": payload.get("comparison_target_id"),
            "preferred_conversation_id": payload.get("preferred_conversation_id"),
            "created_at": utc_now_text(),
        }
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO feedback (
                    id, interview_id, evaluator_id, overall_quality, fairness, relevance,
                    flags_json, notes, comparison_target_id, preferred_conversation_id, created_at
                ) VALUES (
                    :id, :interview_id, :evaluator_id, :overall_quality, :fairness, :relevance,
                    :flags_json, :notes, :comparison_target_id, :preferred_conversation_id, :created_at
                )
                """,
                record,
            )
        return self.get_feedback(record["id"])

    def get_feedback(self, feedback_id: str) -> Dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        if row is None:
            raise KeyError("feedback not found")
        return self._feedback_row_to_dict(row)

    def list_feedback(self, interview_id: str) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM feedback WHERE interview_id = ? ORDER BY created_at DESC",
                (interview_id,),
            ).fetchall()
        return [self._feedback_row_to_dict(row) for row in rows]

    def list_feedback_with_context(
        self,
        skill: Optional[str] = None,
        prompt_version: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        conditions = []
        params: List[Any] = []
        if skill:
            conditions.append("interviews.skill = ?")
            params.append(skill)
        if prompt_version:
            conditions.append("interviews.prompt_version = ?")
            params.append(prompt_version)
        if date_from:
            conditions.append("feedback.created_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("feedback.created_at <= ?")
            params.append(date_to)
        query = """
            SELECT
                feedback.*,
                interviews.skill AS interview_skill,
                interviews.prompt_version AS interview_prompt_version,
                interviews.status AS interview_status
            FROM feedback
            JOIN interviews ON interviews.id = feedback.interview_id
        """
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY feedback.created_at DESC"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        items = []
        for row in rows:
            feedback = self._feedback_row_to_dict(row)
            feedback["skill"] = row["interview_skill"]
            feedback["prompt_version"] = row["interview_prompt_version"]
            feedback["interview_status"] = row["interview_status"]
            items.append(feedback)
        return items

    def comparison_preference_counts(self, left_id: str, right_id: str) -> Dict[str, int]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT preferred_conversation_id
                FROM feedback
                WHERE
                    (interview_id = ? AND comparison_target_id = ?)
                    OR
                    (interview_id = ? AND comparison_target_id = ?)
                """,
                (left_id, right_id, right_id, left_id),
            ).fetchall()
        counts = {
            "left_preferred": 0,
            "right_preferred": 0,
            "no_preference": 0,
            "total_comparisons": len(rows),
        }
        for row in rows:
            preferred = row["preferred_conversation_id"]
            if preferred == left_id:
                counts["left_preferred"] += 1
            elif preferred == right_id:
                counts["right_preferred"] += 1
            else:
                counts["no_preference"] += 1
        return counts

    def metrics(self) -> Dict[str, Any]:
        with self.connection() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_interviews,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_interviews,
                    SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_interviews,
                    COALESCE(SUM(latency_count), 0) AS latency_count,
                    COALESCE(SUM(latency_total_ms), 0) AS latency_total_ms
                FROM interviews
                """
            ).fetchone()
        total = int(totals["total_interviews"])
        completed = int(totals["completed_interviews"] or 0)
        active = int(totals["active_interviews"] or 0)
        latency_count = int(totals["latency_count"] or 0)
        latency_total_ms = float(totals["latency_total_ms"] or 0.0)
        return {
            "total_interviews": total,
            "completed_interviews": completed,
            "active_interviews": active,
            "completion_rate": round((completed / total) if total else 0.0, 3),
            "average_reply_latency_ms": round((latency_total_ms / latency_count) if latency_count else 0.0, 2),
        }

    def _interview_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "candidate_name": row["candidate_name"],
            "skill": row["skill"],
            "status": row["status"],
            "phase": row["phase"],
            "current_question_index": row["current_question_index"],
            "clarification_count": row["clarification_count"],
            "prompt_version": row["prompt_version"],
            "llm_backend": row["llm_backend"],
            "question_set": json.loads(row["question_set_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
            "error_message": row["error_message"],
        }

    def _message_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "interview_id": row["interview_id"],
            "role": row["role"],
            "kind": row["kind"],
            "question_index": row["question_index"],
            "content": row["content"],
            "created_at": row["created_at"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
        }

    def _feedback_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "interview_id": row["interview_id"],
            "evaluator_id": row["evaluator_id"],
            "overall_quality": row["overall_quality"],
            "fairness": row["fairness"],
            "relevance": row["relevance"],
            "flags": json.loads(row["flags_json"] or "[]"),
            "notes": row["notes"],
            "comparison_target_id": row["comparison_target_id"],
            "preferred_conversation_id": row["preferred_conversation_id"],
            "created_at": row["created_at"],
        }
