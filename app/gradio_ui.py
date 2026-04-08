"""Mounted Gradio interface for interview sessions and review workflows."""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml
from fastapi import FastAPI

from app.config import settings
from app.db import Repository
from app.models import InterviewPhase, InterviewStatus, MessageKind, MessageRole, Skill
from app.prompts import PromptStore
from app.services.interview_engine import InterviewEngine
from app.services.review_analytics import ReviewAnalyticsService


FLAG_OPTIONS = [
    "unclear clarification",
    "weak evaluation",
    "bias risk",
    "low relevance",
    "insufficient evidence",
]


def _skill_options() -> List[str]:
    """Return display labels for all supported skills."""
    return [skill.value for skill in Skill]


def _format_timestamp(value: Optional[str]) -> str:
    """Render timestamps in a readable UTC format."""
    if not value:
        return "-"
    return value.replace("T", " ").replace("+00:00", " UTC")


def _backend_label(name: Optional[str]) -> str:
    """Map backend identifiers to user-facing labels."""
    labels = {
        "mock": "Deterministic mock evaluator",
        "MockBackend": "Deterministic mock evaluator",
        "ollama": "Local model evaluator",
        "heuristic": "Rule-based fallback",
    }
    if not name:
        return "n/a"
    return labels.get(name, name)


def _chat_history(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Convert stored transcript messages into Gradio chat history items."""
    history: List[Dict[str, str]] = []
    for message in messages:
        if message["role"] == MessageRole.CANDIDATE.value:
            history.append({"role": "user", "content": message["content"]})
        elif message["role"] == MessageRole.AGENT.value:
            history.append({"role": "assistant", "content": message["content"]})
    return history


def _last_evaluation_message(messages: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the latest evaluation event in a transcript."""
    for message in reversed(messages):
        if message["role"] == MessageRole.SYSTEM.value and message["kind"] == MessageKind.EVALUATION.value:
            return message
    return None


def _clarification_total(messages: Sequence[Dict[str, Any]]) -> int:
    """Count clarifications issued across the full transcript."""
    return sum(1 for message in messages if message["kind"] == MessageKind.CLARIFICATION.value)


def _latest_decision_context(messages: Sequence[Dict[str, Any]]) -> Tuple[str, bool]:
    """Return the most recent decision source and fallback flag."""
    evaluation = _last_evaluation_message(messages)
    if evaluation is None:
        return ("n/a", False)
    metadata = evaluation.get("metadata", {})
    source = _backend_label(metadata.get("backend"))
    if metadata.get("used_fallback"):
        source = "Rule-based fallback"
    return (source, bool(metadata.get("used_fallback", False)))


def _next_action_label(interview: Dict[str, Any]) -> str:
    """Describe the workflow's current next action in plain language."""
    if interview["status"] == InterviewStatus.COMPLETED.value:
        return "Session complete"
    if interview["phase"] == InterviewPhase.CLARIFYING.value:
        return "Await clarification response"
    return "Await answer for current prompt"


def _empty_metadata_bar() -> str:
    """Return a placeholder metadata bar before a session is loaded."""
    return """
    <div class="metadata-bar empty">
      <div class="metadata-pill"><span class="label">Session ID</span><span class="value">Not loaded</span></div>
      <div class="metadata-pill"><span class="label">Current Stage</span><span class="value">n/a</span></div>
      <div class="metadata-pill"><span class="label">Prompt Version</span><span class="value">n/a</span></div>
      <div class="metadata-pill"><span class="label">Last Updated</span><span class="value">n/a</span></div>
      <div class="metadata-pill"><span class="label">Clarifications Used</span><span class="value">0</span></div>
      <div class="metadata-pill"><span class="label">Decision Source</span><span class="value">n/a</span></div>
      <div class="metadata-pill"><span class="label">Fallback Activated</span><span class="value">No</span></div>
    </div>
    """


def _format_metadata_bar(interview: Dict[str, Any]) -> str:
    """Render a compact metadata bar for workflow governance context."""
    messages = interview.get("messages", [])
    decision_source, fallback_activated = _latest_decision_context(messages)
    items = [
        ("Session ID", interview["id"]),
        ("Current Stage", interview["phase"]),
        ("Prompt Version", interview["prompt_version"]),
        ("Last Updated", _format_timestamp(interview.get("updated_at"))),
        ("Clarifications Used", str(_clarification_total(messages))),
        ("Decision Source", decision_source),
        ("Fallback Activated", "Yes" if fallback_activated else "No"),
    ]
    pills = []
    for label, value in items:
        pills.append(
            "<div class=\"metadata-pill\">"
            f"<span class=\"label\">{html.escape(label)}</span>"
            f"<span class=\"value\">{html.escape(value)}</span>"
            "</div>"
        )
    return f"<div class=\"metadata-bar\">{''.join(pills)}</div>"


def _format_state(interview: Dict[str, Any]) -> str:
    """Build the markdown block summarizing workflow control information."""
    total_questions = len(interview["question_set"])
    current_index = min(interview["current_question_index"] + 1, max(total_questions, 1))
    lines = [
        "### Workflow Control",
        f"- **Skill Track:** {interview['skill']}",
        f"- **Session Status:** `{interview['status']}`",
        f"- **Current Stage:** `{interview['phase']}`",
        f"- **Question Progress:** {current_index} / {total_questions}",
        f"- **Next Action:** {_next_action_label(interview)}",
        f"- **Reviewer Entries:** {interview.get('feedback_count', 0)}",
        f"- **Started At:** {_format_timestamp(interview.get('created_at'))}",
        f"- **Completed At:** {_format_timestamp(interview.get('completed_at'))}",
    ]
    return "\n".join(lines)


def _format_transcript(messages: Sequence[Dict[str, Any]]) -> str:
    """Render the transcript, including stored evaluation metadata."""
    if not messages:
        return "_No messages yet._"
    blocks: List[str] = []
    role_labels = {
        MessageRole.AGENT.value: "Agent",
        MessageRole.CANDIDATE.value: "Candidate",
        MessageRole.SYSTEM.value: "Evaluation",
    }
    for message in messages:
        header = f"**{role_labels.get(message['role'], message['role'].title())} · {message['kind']}**"
        content = message["content"].strip() or "_Empty message_"
        if message["role"] == MessageRole.SYSTEM.value and message.get("metadata"):
            metadata = message["metadata"]
            missing_evidence = ", ".join(metadata.get("missing_points") or []) or "none"
            content += (
                f"\n\nVerdict: `{metadata.get('verdict', 'n/a')}`"
                f" | Assessment Score: `{metadata.get('score', 'n/a')}`"
                f" | Missing Evidence: {missing_evidence}"
            )
        blocks.append(f"{header}\n\n{content}")
    return "\n\n---\n\n".join(blocks)


def _format_evaluation(messages: Sequence[Dict[str, Any]]) -> str:
    """Render the latest evaluation decision for the side panel."""
    evaluation = _last_evaluation_message(messages)
    if evaluation is None:
        return "_No evaluation yet. Submit an answer to see the latest evaluation summary._"
    metadata = evaluation.get("metadata", {})
    missing_evidence = metadata.get("missing_points") or []
    decision_source, fallback_activated = _latest_decision_context(messages)
    lines = [
        "### Evaluation Summary",
        f"- **Verdict:** `{metadata.get('verdict', 'n/a')}`",
        f"- **Assessment Score:** `{metadata.get('score', 'n/a')}`",
        f"- **Decision Source:** {decision_source}",
        f"- **Fallback Activated:** {'Yes' if fallback_activated else 'No'}",
        f"- **Evaluation Rationale:** {evaluation['content']}",
        f"- **Missing Evidence:** {', '.join(missing_evidence) if missing_evidence else 'none'}",
    ]
    if metadata.get("follow_up"):
        lines.append(f"- **Next Action:** {metadata['follow_up']}")
    return "\n".join(lines)


def _review_trace_entries(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Build a reviewer-oriented trace from persisted answers and evaluation steps."""
    entries: List[Dict[str, str]] = []
    current_stage = InterviewPhase.ASKING.value
    pending_answer = ""
    for index, message in enumerate(messages):
        if message["role"] == MessageRole.CANDIDATE.value and message["kind"] == MessageKind.ANSWER.value:
            pending_answer = message["content"]
            continue
        if message["role"] != MessageRole.SYSTEM.value or message["kind"] != MessageKind.EVALUATION.value:
            continue

        metadata = message.get("metadata", {})
        next_agent = next(
            (
                item
                for item in messages[index + 1 :]
                if item["role"] == MessageRole.AGENT.value
                and item["kind"] in {
                    MessageKind.CLARIFICATION.value,
                    MessageKind.QUESTION.value,
                    MessageKind.WRAP_UP.value,
                }
            ),
            None,
        )
        if next_agent and next_agent["kind"] == MessageKind.CLARIFICATION.value:
            next_stage = InterviewPhase.CLARIFYING.value
            action_taken = "Clarify"
        elif next_agent and next_agent["kind"] == MessageKind.WRAP_UP.value:
            next_stage = InterviewPhase.COMPLETED.value
            action_taken = "Complete session"
        elif next_agent and next_agent["kind"] == MessageKind.QUESTION.value:
            next_stage = InterviewPhase.ASKING.value
            action_taken = "Advance"
        else:
            next_stage = current_stage
            action_taken = "Await next action"

        entries.append(
            {
                "candidate_answer": pending_answer or "No recorded answer found.",
                "evaluation_summary": message["content"],
                "missing_evidence": ", ".join(metadata.get("missing_points") or []) or "none",
                "action_taken": action_taken,
                "state_transition": f"{current_stage} -> {next_stage}",
            }
        )
        current_stage = next_stage

    return entries


def _format_review_trace(messages: Sequence[Dict[str, Any]]) -> str:
    """Render a compact reviewer trace that explains why the workflow moved."""
    entries = _review_trace_entries(messages)
    if not entries:
        return "_No review trace yet. Submit an answer to record the next transition._"
    blocks: List[str] = ["### Review Trace"]
    for index, entry in enumerate(entries, start=1):
        blocks.extend(
            [
                f"#### Interaction {index}",
                f"- **Candidate Answer:** {entry['candidate_answer']}",
                f"- **Evaluation Summary:** {entry['evaluation_summary']}",
                f"- **Missing Evidence:** {entry['missing_evidence']}",
                f"- **Action Taken:** {entry['action_taken']}",
                f"- **State Transition:** `{entry['state_transition']}`",
                "",
            ]
        )
    return "\n".join(blocks).strip()


def _format_prompt_summary(prompt_store: PromptStore, interview: Optional[Dict[str, Any]] = None) -> str:
    """Render a compact prompt-version summary without dumping full prompt text."""
    prompt = prompt_store.load_version(interview["prompt_version"]) if interview else prompt_store.load_active()
    active_version = prompt_store.active_version_name()
    lines = [
        "### Prompt Version",
        f"- **Prompt Version:** `{prompt.version}`",
        f"- **Description:** {prompt.description}",
        f"- **Active For New Sessions:** {'Yes' if prompt.version == active_version else 'No'}",
        f"- **Clarification Limit:** {prompt.max_clarifications}",
        f"- **Question Sets Available:** {len(prompt.raw.get('skills', {}))}",
    ]
    return "\n".join(lines)


def _format_prompt_catalog(prompt_store: PromptStore) -> str:
    """Render the visible prompt-version history for governance review."""
    active_version = prompt_store.active_version_name()
    blocks = ["### Prompt Version History"]
    for prompt in prompt_store.list_versions():
        status = "active" if prompt.version == active_version else "available"
        blocks.append(
            f"- `{prompt.version}` ({status}) — {prompt.description}"
        )
    if not prompt_store.list_versions():
        blocks.append("- No prompt versions found.")
    return "\n".join(blocks)


def _prompt_details_dump(prompt_store: PromptStore, version: Optional[str] = None) -> str:
    """Return the full prompt definition for the expanded governance view."""
    prompt = prompt_store.load_version(version or prompt_store.active_version_name())
    return yaml.safe_dump(prompt.raw, sort_keys=False)


def _format_system_snapshot(prompt_store: PromptStore, review_analytics: ReviewAnalyticsService) -> str:
    """Render a brief system summary for the review console."""
    review_analytics.repository.init_db()
    prompt = prompt_store.load_active()
    metrics = review_analytics.repository.metrics()
    mode_label = "demo" if settings.demo_mode else settings.app_mode
    return "\n".join(
        [
            "### Prototype Overview",
            f"- **Application Mode:** `{mode_label}`",
            f"- **Active Prompt Version:** `{prompt.version}`",
            f"- **Prompt Editing:** {'Enabled locally' if settings.prompt_admin_enabled else 'Disabled by default'}",
            f"- **Seeded Demo Mode:** {'On' if settings.demo_mode else 'Off'}",
            f"- **Stored Sessions:** {metrics['total_interviews']}",
            f"- **Completed Sessions:** {metrics['completed_interviews']}",
            f"- **Average Reply Latency (ms):** {metrics['average_reply_latency_ms']:.2f}",
        ]
    )


def _interview_label(interview: Dict[str, Any]) -> str:
    """Build a compact dropdown label for a stored session."""
    return (
        f"{interview['id'][:8]} | {interview['skill']} | {interview['phase']} | "
        f"{interview['prompt_version']} | reviews {interview.get('feedback_count', 0)}"
    )


def _reviewed_filter_value(selection: str) -> Optional[bool]:
    """Map UI filter labels to the reviewed query parameter values."""
    if selection == "reviewed":
        return True
    if selection == "unreviewed":
        return False
    return None


def _feedback_summary_markdown(review_analytics: ReviewAnalyticsService) -> str:
    """Render aggregate feedback metrics as markdown for the UI."""
    summary = review_analytics.feedback_summary()
    common_flags = ", ".join(f"{item['flag']} ({item['count']})" for item in summary["common_flags"]) or "none"
    return "\n".join(
        [
            "### Feedback Summary",
            f"- **Total Feedback:** {summary['total_feedback']}",
            f"- **Reviewed Sessions:** {summary['reviewed_interviews']}",
            f"- **Average Quality:** {summary['average_quality']:.2f}",
            f"- **Average Fairness:** {summary['average_fairness']:.2f}",
            f"- **Average Relevance:** {summary['average_relevance']:.2f}",
            f"- **Common Flags:** {common_flags}",
        ]
    )


def _prompt_suggestions_markdown(review_analytics: ReviewAnalyticsService) -> str:
    """Render prompt suggestions as reviewer-friendly markdown."""
    suggestions = review_analytics.prompt_suggestions()
    if not suggestions:
        return "_No prompt suggestions yet. Add reviewer feedback to unlock improvement ideas._"
    blocks: List[str] = []
    for item in suggestions:
        evidence = "; ".join(item["evidence"]) if item.get("evidence") else "No evidence collected yet."
        blocks.append(
            "\n".join(
                [
                    f"**{item['title']}**",
                    f"- Priority: `{item['priority']}`",
                    f"- Scope: `{item['target_scope']}`",
                    f"- Evidence: {evidence}",
                    f"- Suggested Change: {item['suggested_change']}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _live_snapshot(
    interview: Dict[str, Any],
    prompt_store: PromptStore,
) -> Tuple[List[Dict[str, str]], str, str, str, str, str, str]:
    """Assemble all UI fragments needed to display a live interview session."""
    messages = interview.get("messages", [])
    return (
        _chat_history(messages),
        interview["id"],
        _format_metadata_bar(interview),
        _format_state(interview),
        _format_prompt_summary(prompt_store, interview),
        _format_evaluation(messages),
        _format_review_trace(messages),
    )


def _review_snapshot(interview: Dict[str, Any]) -> Tuple[List[Dict[str, str]], str, str, str, str, str]:
    """Assemble the reviewer-facing snapshot for a stored session."""
    messages = interview.get("messages", [])
    return (
        _chat_history(messages),
        interview["id"],
        _format_metadata_bar(interview),
        _format_state(interview),
        _format_evaluation(messages),
        _format_review_trace(messages),
    )


def _default_interview(engine: InterviewEngine, repository: Repository, status: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the newest interview matching a preferred status, if any exist."""
    interviews = repository.list_interviews(status=status)
    if not interviews and status is not None:
        interviews = repository.list_interviews()
    if not interviews:
        return None
    return engine.get_interview(interviews[0]["id"])


def _interview_choices(engine: InterviewEngine, repository: Repository) -> List[Tuple[str, str]]:
    """Return a small list of recent stored sessions for dropdown display."""
    interviews = repository.list_interviews(status=InterviewStatus.COMPLETED.value)[:25]
    return [(_interview_label(engine.get_interview(item["id"])), item["id"]) for item in interviews]


def mount_gradio_ui(
    fastapi_app: FastAPI,
    engine: InterviewEngine,
    prompt_store: PromptStore,
    review_analytics: ReviewAnalyticsService,
) -> FastAPI:
    """Mount the Gradio demo and reviewer UI onto the FastAPI application."""
    import gradio as gr

    repository = review_analytics.repository
    repository.init_db()
    prompt_store.active_version_name()

    def start_live_interview(skill, candidate_name):
        interview = engine.start_interview(skill, candidate_name.strip() or None)
        return (
            *_live_snapshot(interview, prompt_store),
            _format_system_snapshot(prompt_store, review_analytics),
        )

    def send_live_reply(interview_id, answer):
        if not interview_id.strip():
            raise gr.Error("Start or load a session first.")
        if not answer.strip():
            raise gr.Error("Please provide a response before sending.")
        response = engine.reply(interview_id.strip(), answer.strip())
        interview = response["interview"]
        return (
            *_live_snapshot(interview, prompt_store),
            _format_system_snapshot(prompt_store, review_analytics),
            "",
        )

    def load_interview(interview_id):
        if not interview_id or not interview_id.strip():
            raise gr.Error("Enter a session ID to load.")
        interview = engine.get_interview(interview_id.strip())
        return (
            *_live_snapshot(interview, prompt_store),
            _format_system_snapshot(prompt_store, review_analytics),
        )

    def list_interviews(skill_filter, status_filter, reviewed_filter):
        interviews = repository.list_interviews(
            skill=skill_filter or None,
            status=status_filter or None,
            reviewed=_reviewed_filter_value(reviewed_filter),
        )
        choices = [(_interview_label(engine.get_interview(item["id"])), item["id"]) for item in interviews[:25]]
        summary = f"Showing {len(choices)} sessions matching the current filters."
        return gr.Dropdown(choices=choices, value=choices[0][1] if choices else None), summary

    def load_review_session(selected_interview_id):
        if not selected_interview_id:
            raise gr.Error("Choose a session from the list first.")
        interview = engine.get_interview(selected_interview_id)
        return (
            *_review_snapshot(interview),
            _format_system_snapshot(prompt_store, review_analytics),
        )

    def submit_feedback(
        interview_id,
        evaluator_id,
        overall_quality,
        fairness,
        relevance,
        flags,
        notes,
    ):
        if not interview_id.strip():
            raise gr.Error("Load a completed session before submitting feedback.")
        interview = engine.get_interview(interview_id.strip())
        if interview["status"] != InterviewStatus.COMPLETED.value:
            raise gr.Error("Feedback can only be submitted after the session is completed.")
        feedback = repository.create_feedback(
            {
                "interview_id": interview_id.strip(),
                "evaluator_id": evaluator_id.strip() or None,
                "overall_quality": overall_quality,
                "fairness": fairness,
                "relevance": relevance,
                "flags": flags,
                "notes": notes.strip() or None,
            }
        )
        return (
            f"Feedback stored for session `{feedback['interview_id']}` at {_format_timestamp(feedback['created_at'])}.",
            _feedback_summary_markdown(review_analytics),
            _prompt_suggestions_markdown(review_analytics),
        )

    initial_live = _default_interview(engine, repository, InterviewStatus.ACTIVE.value)
    initial_review = _default_interview(engine, repository, InterviewStatus.COMPLETED.value)
    initial_choices = _interview_choices(engine, repository)

    live_history, live_session_id, live_metadata, live_state, live_prompt, live_evaluation, live_trace = (
        _live_snapshot(initial_live, prompt_store)
        if initial_live is not None
        else (
            [],
            "",
            _empty_metadata_bar(),
            "Start or load a session to inspect workflow control and evaluation updates.",
            _format_prompt_summary(prompt_store),
            "_No evaluation yet. Submit an answer to see the latest evaluation summary._",
            "_No review trace yet. Submit an answer to record the next transition._",
        )
    )
    review_history, review_session_id, review_metadata, review_state, review_evaluation, review_trace = (
        _review_snapshot(initial_review)
        if initial_review is not None
        else (
            [],
            "",
            _empty_metadata_bar(),
            "_No session selected._",
            "_No evaluation loaded yet._",
            "_No review trace loaded yet._",
        )
    )

    system_snapshot = _format_system_snapshot(prompt_store, review_analytics)
    feedback_snapshot = _feedback_summary_markdown(review_analytics)
    suggestion_snapshot = _prompt_suggestions_markdown(review_analytics)
    prompt_catalog = _format_prompt_catalog(prompt_store)
    prompt_summary = _format_prompt_summary(prompt_store)
    prompt_dump = _prompt_details_dump(prompt_store)

    css = """
    .gradio-container {
      background:
        radial-gradient(circle at top left, rgba(255, 208, 138, 0.25), transparent 28%),
        radial-gradient(circle at top right, rgba(95, 177, 255, 0.22), transparent 30%),
        linear-gradient(180deg, #fff8ef 0%, #f7f2ea 100%);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: #2d241d;
    }
    #hero-card, .panel-card {
      background: rgba(255, 255, 255, 0.88);
      border: 1px solid rgba(145, 106, 68, 0.14);
      border-radius: 22px;
      box-shadow: 0 18px 45px rgba(112, 84, 54, 0.08);
      backdrop-filter: blur(10px);
    }
    #hero-card {
      padding: 22px 24px 8px 24px;
      margin-bottom: 16px;
    }
    .panel-card {
      padding: 12px;
    }
    #hero-card,
    #hero-card .prose,
    #hero-card .prose h1,
    #hero-card .prose h2,
    #hero-card .prose h3,
    #hero-card .prose p,
    .panel-card,
    .panel-card .prose,
    .panel-card .prose h1,
    .panel-card .prose h2,
    .panel-card .prose h3,
    .panel-card .prose p,
    .panel-card .prose li,
    .gradio-container label,
    .gradio-container legend {
      color: #2d241d !important;
    }
    #hero-card .prose p,
    .panel-card .prose p,
    .panel-card .prose li {
      color: #4e4033 !important;
    }
    .gradio-container input,
    .gradio-container textarea,
    .gradio-container select {
      color: #2d241d !important;
      background: rgba(255, 255, 255, 0.94) !important;
    }
    .metadata-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 8px;
    }
    .metadata-pill {
      background: rgba(255, 248, 239, 0.92);
      border: 1px solid rgba(145, 106, 68, 0.14);
      border-radius: 16px;
      padding: 10px 12px;
      min-width: 150px;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.45);
    }
    .metadata-pill .label {
      display: block;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #7a6451;
      margin-bottom: 4px;
    }
    .metadata-pill .value {
      display: block;
      font-size: 13px;
      color: #2d241d;
      word-break: break-word;
    }
    .metadata-bar.empty .metadata-pill {
      opacity: 0.85;
    }
    """

    with gr.Blocks(css=css, title="AI Interview Orchestration Prototype") as demo:
        with gr.Column(elem_id="hero-card"):
            gr.Markdown(
                """
                # AI Interview Orchestration Prototype
                Browser-based workspace for running a production-style prototype with explicit state transitions,
                evaluation summary persistence, prompt versioning, and human-in-the-loop review.
                """
            )
            system_status = gr.Markdown(system_snapshot)

        with gr.Tabs():
            with gr.Tab("Interview View"):
                with gr.Row():
                    with gr.Column(scale=7):
                        with gr.Group(elem_classes=["panel-card"]):
                            gr.Markdown("### Start a new session")
                            with gr.Row():
                                candidate_name = gr.Textbox(label="Session Label", placeholder="Optional")
                                skill = gr.Dropdown(
                                    choices=_skill_options(),
                                    value=Skill.PROBLEM_SOLVING.value,
                                    label="Skill Track",
                                )
                            with gr.Row():
                                start_button = gr.Button("Start Session", variant="primary")
                                interview_id = gr.Textbox(label="Session ID", value=live_session_id, interactive=False)
                                load_id = gr.Textbox(label="Load Session ID")
                                load_button = gr.Button("Load")

                        chatbot = gr.Chatbot(
                            label="Interview Flow",
                            value=live_history,
                            type="messages",
                            height=520,
                            placeholder="The live session transcript will appear here.",
                            elem_classes=["panel-card"],
                        )

                        with gr.Group(elem_classes=["panel-card"]):
                            answer_box = gr.Textbox(
                                label="Interview Response",
                                lines=4,
                                placeholder="Write the next response here, then send it through the workflow.",
                            )
                            send_button = gr.Button("Send Response", variant="primary")

                    with gr.Column(scale=5):
                        live_metadata_html = gr.HTML(live_metadata, elem_classes=["panel-card"])
                        state_markdown = gr.Markdown(live_state, elem_classes=["panel-card"])
                        prompt_markdown = gr.Markdown(live_prompt, elem_classes=["panel-card"])
                        evaluation_markdown = gr.Markdown(live_evaluation, elem_classes=["panel-card"])
                        trace_markdown = gr.Markdown(live_trace, elem_classes=["panel-card"])

                start_button.click(
                    fn=start_live_interview,
                    inputs=[skill, candidate_name],
                    outputs=[
                        chatbot,
                        interview_id,
                        live_metadata_html,
                        state_markdown,
                        prompt_markdown,
                        evaluation_markdown,
                        trace_markdown,
                        system_status,
                    ],
                    show_api=False,
                )
                send_button.click(
                    fn=send_live_reply,
                    inputs=[interview_id, answer_box],
                    outputs=[
                        chatbot,
                        interview_id,
                        live_metadata_html,
                        state_markdown,
                        prompt_markdown,
                        evaluation_markdown,
                        trace_markdown,
                        system_status,
                        answer_box,
                    ],
                    show_api=False,
                )
                answer_box.submit(
                    fn=send_live_reply,
                    inputs=[interview_id, answer_box],
                    outputs=[
                        chatbot,
                        interview_id,
                        live_metadata_html,
                        state_markdown,
                        prompt_markdown,
                        evaluation_markdown,
                        trace_markdown,
                        system_status,
                        answer_box,
                    ],
                    show_api=False,
                )
                load_button.click(
                    fn=load_interview,
                    inputs=[load_id],
                    outputs=[
                        chatbot,
                        interview_id,
                        live_metadata_html,
                        state_markdown,
                        prompt_markdown,
                        evaluation_markdown,
                        trace_markdown,
                        system_status,
                    ],
                    show_api=False,
                )

            with gr.Tab("Review Console"):
                with gr.Row():
                    with gr.Column(scale=4):
                        with gr.Group(elem_classes=["panel-card"]):
                            gr.Markdown("### Discover sessions")
                            review_skill_filter = gr.Dropdown(
                                choices=[""] + _skill_options(),
                                value="",
                                label="Skill Filter",
                            )
                            review_status_filter = gr.Dropdown(
                                choices=["", InterviewStatus.ACTIVE.value, InterviewStatus.COMPLETED.value],
                                value=InterviewStatus.COMPLETED.value,
                                label="Session Status",
                            )
                            reviewed_filter = gr.Radio(
                                choices=["all", "reviewed", "unreviewed"],
                                value="all",
                                label="Review Status",
                            )
                            refresh_interviews_button = gr.Button("Refresh Sessions")
                            interview_list = gr.Dropdown(
                                label="Recent Sessions",
                                choices=initial_choices,
                                value=initial_choices[0][1] if initial_choices else None,
                            )
                            interview_list_summary = gr.Markdown(
                                f"Showing {len(initial_choices)} completed sessions."
                                if initial_choices
                                else "Refresh to load sessions."
                            )

                        with gr.Group(elem_classes=["panel-card"]):
                            gr.Markdown("### Submit evaluation")
                            review_interview_id = gr.Textbox(label="Session ID", value=review_session_id, interactive=False)
                            reviewer_id = gr.Textbox(label="Reviewer ID", placeholder="Optional")
                            quality = gr.Slider(1, 5, value=4, step=1, label="Overall Quality")
                            fairness = gr.Slider(1, 5, value=4, step=1, label="Fairness")
                            relevance = gr.Slider(1, 5, value=4, step=1, label="Relevance")
                            feedback_flags = gr.CheckboxGroup(choices=FLAG_OPTIONS, label="Flags")
                            feedback_notes = gr.Textbox(label="Notes", lines=4)
                            submit_feedback_button = gr.Button("Submit Evaluation", variant="primary")
                            feedback_status = gr.Markdown("_Load a completed session and submit an evaluation._")

                    with gr.Column(scale=6):
                        review_chatbot = gr.Chatbot(
                            label="Session Replay",
                            value=review_history,
                            type="messages",
                            height=360,
                            placeholder="Load a completed session to inspect it here.",
                            elem_classes=["panel-card"],
                        )
                        review_metadata_html = gr.HTML(review_metadata, elem_classes=["panel-card"])
                        review_state = gr.Markdown(review_state, elem_classes=["panel-card"])
                        review_evaluation = gr.Markdown(review_evaluation, elem_classes=["panel-card"])
                        review_trace = gr.Markdown(review_trace, elem_classes=["panel-card"])
                        feedback_summary = gr.Markdown(feedback_snapshot, elem_classes=["panel-card"])
                        prompt_suggestions = gr.Markdown(suggestion_snapshot, elem_classes=["panel-card"])

                refresh_interviews_button.click(
                    fn=list_interviews,
                    inputs=[review_skill_filter, review_status_filter, reviewed_filter],
                    outputs=[interview_list, interview_list_summary],
                    show_api=False,
                )
                interview_list.change(
                    fn=load_review_session,
                    inputs=[interview_list],
                    outputs=[
                        review_chatbot,
                        review_interview_id,
                        review_metadata_html,
                        review_state,
                        review_evaluation,
                        review_trace,
                        system_status,
                    ],
                    show_api=False,
                )
                submit_feedback_button.click(
                    fn=submit_feedback,
                    inputs=[review_interview_id, reviewer_id, quality, fairness, relevance, feedback_flags, feedback_notes],
                    outputs=[feedback_status, feedback_summary, prompt_suggestions],
                    show_api=False,
                )

            with gr.Tab("Prompt Governance"):
                with gr.Row():
                    with gr.Column(scale=5):
                        gr.Markdown(prompt_summary, elem_classes=["panel-card"])
                        gr.Markdown(prompt_catalog, elem_classes=["panel-card"])
                        gr.Markdown(
                            "_Prompt editing is intentionally disabled in the public demo surface. Read-only version history and prompt metadata remain visible for governance review._",
                            elem_classes=["panel-card"],
                        )
                    with gr.Column(scale=5):
                        with gr.Accordion("Expand active prompt definition", open=False):
                            gr.Code(prompt_dump, language="yaml")

    return gr.mount_gradio_app(fastapi_app, demo, path="/ui")
