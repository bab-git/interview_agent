from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI

from app.models import InterviewStatus, MessageKind, MessageRole, Skill
from app.prompts import PromptStore
from app.services.interview_engine import InterviewEngine
from app.services.review_analytics import ReviewAnalyticsService


FLAG_OPTIONS = [
    "inappropriate question",
    "weak evaluation",
    "bias risk",
    "low relevance",
    "unclear clarification",
]


def _skill_options() -> List[str]:
    return [skill.value for skill in Skill]


def _format_timestamp(value: Optional[str]) -> str:
    if not value:
        return "-"
    return value.replace("T", " ").replace("+00:00", " UTC")


def _chat_history(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    history: List[Dict[str, str]] = []
    for message in messages:
        if message["role"] == MessageRole.CANDIDATE.value:
            history.append({"role": "user", "content": message["content"]})
        elif message["role"] == MessageRole.AGENT.value:
            history.append({"role": "assistant", "content": message["content"]})
    return history


def _last_evaluation_message(messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for message in reversed(messages):
        if message["role"] == MessageRole.SYSTEM.value and message["kind"] == MessageKind.EVALUATION.value:
            return message
    return None


def _format_state(interview: Dict[str, Any]) -> str:
    total_questions = len(interview["question_set"])
    current_index = interview["current_question_index"] + 1
    current_prompt = ""
    if interview["status"] == InterviewStatus.ACTIVE.value and interview["current_question_index"] < total_questions:
        current_prompt = interview["question_set"][interview["current_question_index"]]["prompt"]
    lines = [
        "### Live State",
        f"- **Interview ID:** `{interview['id']}`",
        f"- **Candidate:** {interview.get('candidate_name') or 'Anonymous candidate'}",
        f"- **Skill:** {interview['skill']}",
        f"- **Status:** `{interview['status']}`",
        f"- **Phase:** `{interview['phase']}`",
        f"- **Question:** {current_index} / {total_questions}",
        f"- **Clarifications Used:** {interview['clarification_count']}",
        f"- **Prompt Version:** `{interview['prompt_version']}`",
        f"- **LLM Backend:** `{interview['llm_backend']}`",
        f"- **Feedback Count:** {interview.get('feedback_count', 0)}",
        f"- **Created At:** {_format_timestamp(interview.get('created_at'))}",
        f"- **Completed At:** {_format_timestamp(interview.get('completed_at'))}",
    ]
    if current_prompt:
        lines.extend(["", "### Current Prompt", current_prompt])
    return "\n".join(lines)


def _format_transcript(messages: List[Dict[str, Any]]) -> str:
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
            verdict = metadata.get("verdict", "n/a")
            score = metadata.get("score", "n/a")
            missing_points = ", ".join(metadata.get("missing_points") or []) or "none"
            content += f"\n\nVerdict: `{verdict}` | Score: `{score}` | Missing: {missing_points}"
        blocks.append(f"{header}\n\n{content}")
    return "\n\n---\n\n".join(blocks)


def _format_evaluation(messages: List[Dict[str, Any]]) -> str:
    evaluation = _last_evaluation_message(messages)
    if evaluation is None:
        return "_No evaluation yet. Submit an answer to see the latest scoring decision._"
    metadata = evaluation.get("metadata", {})
    missing_points = metadata.get("missing_points") or []
    lines = [
        "### Latest Evaluation",
        f"- **Verdict:** `{metadata.get('verdict', 'n/a')}`",
        f"- **Score:** `{metadata.get('score', 'n/a')}`",
        f"- **Backend:** `{metadata.get('backend', 'n/a')}`",
        f"- **Fallback Used:** `{metadata.get('used_fallback', False)}`",
        f"- **Reasoning:** {evaluation['content']}",
        f"- **Missing Points:** {', '.join(missing_points) if missing_points else 'none'}",
    ]
    if metadata.get("follow_up"):
        lines.append(f"- **Follow-up:** {metadata['follow_up']}")
    return "\n".join(lines)


def _format_system_snapshot(prompt_store: PromptStore, review_analytics: ReviewAnalyticsService) -> str:
    review_analytics.repository.init_db()
    prompt = prompt_store.load_active()
    metrics = review_analytics.repository.metrics()
    return "\n".join(
        [
            "### System Snapshot",
            f"- **Active Prompt:** `{prompt.version}`",
            f"- **Prompt Description:** {prompt.description}",
            f"- **Total Interviews:** {metrics['total_interviews']}",
            f"- **Completed Interviews:** {metrics['completed_interviews']}",
            f"- **Completion Rate:** {metrics['completion_rate']:.2f}",
            f"- **Average Reply Latency (ms):** {metrics['average_reply_latency_ms']:.2f}",
        ]
    )


def _interview_label(interview: Dict[str, Any]) -> str:
    return (
        f"{interview['id'][:8]} | {interview['skill']} | {interview['status']} | "
        f"{interview['prompt_version']} | feedback {interview.get('feedback_count', 0)}"
    )


def _reviewed_filter_value(selection: str) -> Optional[bool]:
    if selection == "reviewed":
        return True
    if selection == "unreviewed":
        return False
    return None


def _feedback_summary_markdown(review_analytics: ReviewAnalyticsService) -> str:
    summary = review_analytics.feedback_summary()
    common_flags = ", ".join(f"{item['flag']} ({item['count']})" for item in summary["common_flags"]) or "none"
    return "\n".join(
        [
            "### Feedback Summary",
            f"- **Total Feedback:** {summary['total_feedback']}",
            f"- **Reviewed Interviews:** {summary['reviewed_interviews']}",
            f"- **Average Quality:** {summary['average_quality']:.2f}",
            f"- **Average Fairness:** {summary['average_fairness']:.2f}",
            f"- **Average Relevance:** {summary['average_relevance']:.2f}",
            f"- **Common Flags:** {common_flags}",
        ]
    )


def _prompt_suggestions_markdown(review_analytics: ReviewAnalyticsService) -> str:
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


def _interview_snapshot(
    interview: Dict[str, Any],
    prompt_store: PromptStore,
    review_analytics: ReviewAnalyticsService,
) -> Tuple[List[Dict[str, str]], str, str, str, str]:
    messages = interview.get("messages", [])
    return (
        _chat_history(messages),
        interview["id"],
        _format_state(interview),
        _format_evaluation(messages),
        _format_transcript(messages),
    )


def mount_gradio_ui(
    fastapi_app: FastAPI,
    engine: InterviewEngine,
    prompt_store: PromptStore,
    review_analytics: ReviewAnalyticsService,
) -> FastAPI:
    import gradio as gr

    def start_live_interview(skill, candidate_name):
        interview = engine.start_interview(skill, candidate_name.strip() or None)
        chat_history, interview_id, state_md, evaluation_md, transcript_md = _interview_snapshot(
            interview,
            prompt_store,
            review_analytics,
        )
        return (
            chat_history,
            interview_id,
            state_md,
            evaluation_md,
            transcript_md,
            _format_system_snapshot(prompt_store, review_analytics),
        )

    def send_live_reply(interview_id, answer):
        if not interview_id.strip():
            raise gr.Error("Start or load an interview first.")
        if not answer.strip():
            raise gr.Error("Please provide a candidate answer before sending.")
        response = engine.reply(interview_id.strip(), answer.strip())
        interview = response["interview"]
        chat_history, _, state_md, evaluation_md, transcript_md = _interview_snapshot(
            interview,
            prompt_store,
            review_analytics,
        )
        return (
            chat_history,
            "",
            state_md,
            evaluation_md,
            transcript_md,
            _format_system_snapshot(prompt_store, review_analytics),
        )

    def load_interview(interview_id):
        if not interview_id.strip():
            raise gr.Error("Enter an interview ID to load.")
        interview = engine.get_interview(interview_id.strip())
        chat_history, interview_id_value, state_md, evaluation_md, transcript_md = _interview_snapshot(
            interview,
            prompt_store,
            review_analytics,
        )
        return (
            chat_history,
            interview_id_value,
            state_md,
            evaluation_md,
            transcript_md,
            _format_system_snapshot(prompt_store, review_analytics),
        )

    def list_interviews(skill_filter, status_filter, reviewed_filter):
        interviews = review_analytics.repository.list_interviews(
            skill=skill_filter or None,
            status=status_filter or None,
            reviewed=_reviewed_filter_value(reviewed_filter),
        )
        choices = [(_interview_label(engine.get_interview(item["id"])), item["id"]) for item in interviews[:25]]
        summary = f"Showing {len(choices)} interviews matching the current filters."
        return gr.Dropdown(choices=choices, value=choices[0][1] if choices else None), summary

    def load_selected_interview(selected_interview_id):
        return load_interview(selected_interview_id)

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
            raise gr.Error("Load a completed interview before submitting feedback.")
        interview = engine.get_interview(interview_id.strip())
        if interview["status"] != InterviewStatus.COMPLETED.value:
            raise gr.Error("Feedback can only be submitted after the interview is completed.")
        feedback = review_analytics.repository.create_feedback(
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
            f"Feedback stored for interview `{feedback['interview_id']}` at {_format_timestamp(feedback['created_at'])}.",
            _feedback_summary_markdown(review_analytics),
            _prompt_suggestions_markdown(review_analytics),
        )

    system_snapshot = _format_system_snapshot(prompt_store, review_analytics)
    feedback_snapshot = _feedback_summary_markdown(review_analytics)
    suggestion_snapshot = _prompt_suggestions_markdown(review_analytics)
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
      background: rgba(255, 255, 255, 0.86);
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
    .panel-card h3, #hero-card h1, #hero-card h3 {
      letter-spacing: 0.01em;
    }
    """

    with gr.Blocks(css=css, title="Interview Agent Live Test") as demo:
        with gr.Column(elem_id="hero-card"):
            gr.Markdown(
                """
                # Interview Agent Live Test
                Browser-based live testing for the stateful interview pipeline. Start an interview, answer in character
                as the candidate, and watch the evaluation and clarification loop update in real time.
                """
            )
            system_status = gr.Markdown(system_snapshot)

        with gr.Tabs():
            with gr.Tab("Live Interview"):
                with gr.Row():
                    with gr.Column(scale=7):
                        with gr.Group(elem_classes=["panel-card"]):
                            gr.Markdown("### Start a fresh interview")
                            with gr.Row():
                                candidate_name = gr.Textbox(label="Candidate Name", placeholder="Optional")
                                skill = gr.Dropdown(
                                    choices=_skill_options(),
                                    value=Skill.PROBLEM_SOLVING.value,
                                    label="Skill",
                                )
                            with gr.Row():
                                start_button = gr.Button("Start Interview", variant="primary")
                                interview_id = gr.Textbox(label="Current Interview ID", interactive=False)
                                load_id = gr.Textbox(label="Load Interview By ID")
                                load_button = gr.Button("Load")

                        chatbot = gr.Chatbot(
                            label="Interview Conversation",
                            type="messages",
                            height=520,
                            placeholder="The live interview transcript will appear here.",
                            elem_classes=["panel-card"],
                        )

                        with gr.Group(elem_classes=["panel-card"]):
                            answer_box = gr.Textbox(
                                label="Candidate Reply",
                                lines=4,
                                placeholder="Write the candidate answer here, then send it into the pipeline.",
                            )
                            send_button = gr.Button("Send Reply", variant="primary")

                    with gr.Column(scale=5):
                        state_markdown = gr.Markdown("Start an interview to see state transitions.", elem_classes=["panel-card"])
                        evaluation_markdown = gr.Markdown(
                            "_No evaluation yet. Submit an answer to see the latest scoring decision._",
                            elem_classes=["panel-card"],
                        )
                        transcript_markdown = gr.Markdown(
                            "_No messages yet._",
                            elem_classes=["panel-card"],
                        )

                start_button.click(
                    fn=start_live_interview,
                    inputs=[skill, candidate_name],
                    outputs=[chatbot, interview_id, state_markdown, evaluation_markdown, transcript_markdown, system_status],
                    show_api=False,
                )
                send_button.click(
                    fn=send_live_reply,
                    inputs=[interview_id, answer_box],
                    outputs=[chatbot, answer_box, state_markdown, evaluation_markdown, transcript_markdown, system_status],
                    show_api=False,
                )
                answer_box.submit(
                    fn=send_live_reply,
                    inputs=[interview_id, answer_box],
                    outputs=[chatbot, answer_box, state_markdown, evaluation_markdown, transcript_markdown, system_status],
                    show_api=False,
                )
                load_button.click(
                    fn=load_interview,
                    inputs=[load_id],
                    outputs=[chatbot, interview_id, state_markdown, evaluation_markdown, transcript_markdown, system_status],
                    show_api=False,
                )

            with gr.Tab("Reviewer Workbench"):
                with gr.Row():
                    with gr.Column(scale=4):
                        with gr.Group(elem_classes=["panel-card"]):
                            gr.Markdown("### Discover conversations")
                            review_skill_filter = gr.Dropdown(
                                choices=[""] + _skill_options(),
                                value="",
                                label="Skill Filter",
                            )
                            review_status_filter = gr.Dropdown(
                                choices=["", InterviewStatus.ACTIVE.value, InterviewStatus.COMPLETED.value],
                                value=InterviewStatus.COMPLETED.value,
                                label="Status Filter",
                            )
                            reviewed_filter = gr.Radio(
                                choices=["all", "reviewed", "unreviewed"],
                                value="all",
                                label="Review Status",
                            )
                            refresh_interviews_button = gr.Button("Refresh Interviews")
                            interview_list = gr.Dropdown(label="Recent Interviews", choices=[])
                            interview_list_summary = gr.Markdown("Refresh to load interviews.")

                        with gr.Group(elem_classes=["panel-card"]):
                            gr.Markdown("### Submit feedback")
                            review_interview_id = gr.Textbox(label="Review Interview ID", interactive=False)
                            reviewer_id = gr.Textbox(label="Evaluator ID", placeholder="Optional")
                            quality = gr.Slider(1, 5, value=4, step=1, label="Overall Quality")
                            fairness = gr.Slider(1, 5, value=4, step=1, label="Fairness")
                            relevance = gr.Slider(1, 5, value=4, step=1, label="Relevance")
                            feedback_flags = gr.CheckboxGroup(choices=FLAG_OPTIONS, label="Flags")
                            feedback_notes = gr.Textbox(label="Notes", lines=4)
                            submit_feedback_button = gr.Button("Submit Feedback", variant="primary")
                            feedback_status = gr.Markdown("_Load a completed interview and submit a review._")

                    with gr.Column(scale=6):
                        review_chatbot = gr.Chatbot(
                            label="Conversation Replay",
                            type="messages",
                            height=380,
                            placeholder="Load a completed interview to inspect it here.",
                            elem_classes=["panel-card"],
                        )
                        review_state = gr.Markdown("_No interview selected._", elem_classes=["panel-card"])
                        review_evaluation = gr.Markdown(
                            "_No evaluation loaded yet._",
                            elem_classes=["panel-card"],
                        )
                        review_transcript = gr.Markdown("_No transcript loaded._", elem_classes=["panel-card"])
                        feedback_summary = gr.Markdown(feedback_snapshot, elem_classes=["panel-card"])
                        prompt_suggestions = gr.Markdown(suggestion_snapshot, elem_classes=["panel-card"])

                refresh_interviews_button.click(
                    fn=list_interviews,
                    inputs=[review_skill_filter, review_status_filter, reviewed_filter],
                    outputs=[interview_list, interview_list_summary],
                    show_api=False,
                )
                interview_list.change(
                    fn=load_selected_interview,
                    inputs=[interview_list],
                    outputs=[review_chatbot, review_interview_id, review_state, review_evaluation, review_transcript, system_status],
                    show_api=False,
                )
                submit_feedback_button.click(
                    fn=submit_feedback,
                    inputs=[review_interview_id, reviewer_id, quality, fairness, relevance, feedback_flags, feedback_notes],
                    outputs=[feedback_status, feedback_summary, prompt_suggestions],
                    show_api=False,
                )

    return gr.mount_gradio_app(fastapi_app, demo, path="/ui")
