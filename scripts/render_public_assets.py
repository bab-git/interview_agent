"""Render deterministic public-facing portfolio images from seeded demo data."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import yaml
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_MODE", "demo")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("DEMO_SEED", "7")
os.environ.setdefault("DEMO_RESET_ON_START", "false")
os.environ.setdefault("PROMPT_ADMIN_ENABLED", "false")
os.environ.setdefault("APP_DATA_DIR", "/tmp/interview_agent_public_assets")
os.environ.setdefault("APP_DB_PATH", "/tmp/interview_agent_public_assets/demo.sqlite3")
os.environ.setdefault("PROMPT_ACTIVE_FILE", "/tmp/interview_agent_public_assets/active_prompt.json")
os.environ.setdefault("PROMPT_VERSIONS_DIR", str(ROOT / "prompts" / "versions"))
os.environ.setdefault("LLM_BACKEND", "mock")

from app.config import settings
from app.demo import demo_session_ids, reset_demo_sessions
from app.db import Repository
from app.gradio_ui import _review_trace_entries
from app.prompts import PromptStore
from app.services.review_analytics import ReviewAnalyticsService


WIDTH = 1600
HEIGHT = 1080
PADDING = 48

BG_TOP = "#FFF8EF"
BG_BOTTOM = "#F6F0E9"
INK = "#2D241D"
MUTED = "#6E5A4A"
CARD_BG = "#FFFDFC"
CARD_OUTLINE = "#E7D9CC"
ACCENT_WARM = "#D78E4A"
ACCENT_COOL = "#6FAED9"
SOFT_GREEN = "#E8F2EA"
SOFT_BLUE = "#EAF2FB"
SOFT_GOLD = "#FDF0E2"


def load_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    """Load a readable system font with sensible fallbacks."""
    if mono:
        candidates = [
            "/System/Library/Fonts/SFNSMono.ttf",
            "/System/Library/Fonts/Supplemental/Courier New.ttf",
        ]
    elif bold:
        candidates = [
            "/System/Library/Fonts/Supplemental/Avenir Next.ttc",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/System/Library/Fonts/SFNS.ttf",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/Supplemental/Avenir Next.ttc",
            "/System/Library/Fonts/SFNS.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica Neue.ttc",
        ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


TITLE_FONT = load_font(44, bold=True)
SUBTITLE_FONT = load_font(20)
CARD_TITLE_FONT = load_font(24, bold=True)
BODY_FONT = load_font(18)
BODY_BOLD_FONT = load_font(18, bold=True)
SMALL_FONT = load_font(15)
SMALL_BOLD_FONT = load_font(15, bold=True)
MONO_FONT = load_font(16, mono=True)


def blend(color_a: str, color_b: str, ratio: float) -> Tuple[int, int, int]:
    """Blend two colors by a ratio."""
    a = ImageColor.getrgb(color_a)
    b = ImageColor.getrgb(color_b)
    return tuple(int(a[index] + (b[index] - a[index]) * ratio) for index in range(3))


def gradient_background() -> Image.Image:
    """Create the shared portfolio background."""
    image = Image.new("RGBA", (WIDTH, HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio = y / max(1, HEIGHT - 1)
        draw.line((0, y, WIDTH, y), fill=blend(BG_TOP, BG_BOTTOM, ratio))

    for cx, cy, radius, color, alpha in [
        (220, 120, 280, ACCENT_WARM, 44),
        (1320, 110, 260, ACCENT_COOL, 36),
        (1240, 820, 360, "#EDDCCB", 72),
    ]:
        blob = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        blob_draw = ImageDraw.Draw(blob)
        blob_draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=ImageColor.getrgb(color) + (alpha,),
        )
        blob = blob.filter(ImageFilter.GaussianBlur(40))
        image.alpha_composite(blob)
    return image


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    """Wrap text to a target width."""
    words = text.split()
    if not words:
        return [""]
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def text_block_height(draw: ImageDraw.ImageDraw, lines: Sequence[str], font: ImageFont.ImageFont, spacing: int = 6) -> int:
    """Measure the height of a wrapped text block."""
    if not lines:
        return 0
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    line_height = bbox[3] - bbox[1]
    return len(lines) * line_height + (len(lines) - 1) * spacing


def draw_lines(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    lines: Sequence[str],
    font: ImageFont.ImageFont,
    fill: str,
    spacing: int = 6,
) -> int:
    """Draw a sequence of wrapped lines and return the next y position."""
    x, y = xy
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    line_height = bbox[3] - bbox[1]
    for index, line in enumerate(lines):
        draw.text((x, y + index * (line_height + spacing)), line, font=font, fill=fill)
    return y + text_block_height(draw, lines, font, spacing)


def rounded_card(
    canvas: Image.Image,
    rect: Tuple[int, int, int, int],
    fill: str = CARD_BG,
    outline: str = CARD_OUTLINE,
    radius: int = 28,
) -> None:
    """Draw a rounded card with a soft shadow."""
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    x1, y1, x2, y2 = rect
    shadow_draw.rounded_rectangle((x1, y1 + 10, x2, y2 + 10), radius=radius, fill=(96, 68, 42, 28))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.alpha_composite(shadow)
    ImageDraw.Draw(canvas).rounded_rectangle(rect, radius=radius, fill=fill, outline=outline, width=2)


def draw_chip(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    label: str,
    bg: str,
    fg: str,
    font: ImageFont.ImageFont = SMALL_BOLD_FONT,
) -> int:
    """Draw a pill chip and return its width."""
    x, y = xy
    bbox = draw.textbbox((0, 0), label, font=font)
    width = bbox[2] - bbox[0] + 24
    height = bbox[3] - bbox[1] + 16
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=bg)
    draw.text((x + 12, y + 7), label, font=font, fill=fg)
    return width


def format_timestamp(value: str | None) -> str:
    """Render ISO timestamps in a readable form."""
    if not value:
        return "-"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def backend_label(value: str | None) -> str:
    """Map backend identifiers to portfolio-friendly labels."""
    labels = {
        "mock": "Deterministic mock evaluator",
        "MockBackend": "Deterministic mock evaluator",
        "heuristic": "Rule-based fallback",
        "ollama": "Local model evaluator",
    }
    if not value:
        return "n/a"
    return labels.get(value, value)


def latest_evaluation(messages: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the latest evaluation message from a transcript."""
    evaluations = [message for message in messages if message["role"] == "system" and message["kind"] == "evaluation"]
    return evaluations[-1] if evaluations else {}


def clarification_total(messages: Sequence[Dict[str, Any]]) -> int:
    """Count clarifications across the session transcript."""
    return sum(1 for message in messages if message["kind"] == "clarification")


def transcript_excerpt(messages: Sequence[Dict[str, Any]], limit: int = 5) -> List[Tuple[str, str]]:
    """Return a small transcript excerpt for rendering."""
    selected: List[Tuple[str, str]] = []
    wanted = {"question", "answer", "clarification"}
    for message in messages:
        if message["kind"] not in wanted:
            continue
        role = "Candidate Answer" if message["role"] == "candidate" else "Workflow Prompt"
        selected.append((role, message["content"]))
    return selected[:limit]


def load_demo_context() -> Dict[str, Any]:
    """Reset the seeded demo content and return the main rendering inputs."""
    repository = Repository(settings)
    prompt_store = PromptStore(settings)
    reset_demo_sessions(settings, repository, prompt_store)
    review_analytics = ReviewAnalyticsService(repository)

    trace_id, fallback_id, active_id = list(demo_session_ids(settings.demo_seed))
    trace_session = repository.get_interview(trace_id)
    trace_session["messages"] = repository.list_messages(trace_id)
    trace_session["feedback_count"] = repository.feedback_count(trace_id)

    fallback_session = repository.get_interview(fallback_id)
    fallback_session["messages"] = repository.list_messages(fallback_id)
    fallback_session["feedback_count"] = repository.feedback_count(fallback_id)

    active_session = repository.get_interview(active_id)
    active_session["messages"] = repository.list_messages(active_id)
    active_session["feedback_count"] = repository.feedback_count(active_id)

    return {
        "prompt_store": prompt_store,
        "trace_session": trace_session,
        "fallback_session": fallback_session,
        "active_session": active_session,
        "feedback_summary": review_analytics.feedback_summary(),
        "prompt_suggestions": review_analytics.prompt_suggestions(),
    }


def draw_header(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    """Draw a shared page header."""
    draw.text((PADDING, 42), title, font=TITLE_FONT, fill=INK)
    subtitle_lines = wrap_text(draw, subtitle, SUBTITLE_FONT, 980)
    draw_lines(draw, (PADDING, 102), subtitle_lines, SUBTITLE_FONT, MUTED)


def render_interview_view(snapshot: Dict[str, Any], output_path: Path) -> None:
    """Render the interview view asset with metadata and evaluation summary."""
    interview = snapshot["active_session"]
    messages = interview["messages"]
    evaluation = latest_evaluation(messages)
    metadata = evaluation.get("metadata", {})

    canvas = gradient_background()
    draw = ImageDraw.Draw(canvas)
    draw_header(
        draw,
        "Interview View",
        "Seeded session showing workflow control, prompt version context, and a clarification-triggering evaluation summary.",
    )

    rounded_card(canvas, (PADDING, 168, WIDTH - PADDING, 330))
    draw.text((PADDING + 24, 192), "Session Metadata", font=CARD_TITLE_FONT, fill=INK)
    items = [
        ("Session ID", interview["id"][:8] + "..." + interview["id"][-4:]),
        ("Current Stage", interview["phase"].capitalize()),
        ("Prompt Version", interview["prompt_version"]),
        ("Last Updated", format_timestamp(interview["updated_at"])),
        ("Clarifications Used", str(clarification_total(messages))),
        ("Decision Source", backend_label(metadata.get("backend"))),
        ("Fallback Activated", "Yes" if metadata.get("used_fallback") else "No"),
    ]
    x, y = PADDING + 24, 238
    for index, (label, value) in enumerate(items):
        rounded_card(canvas, (x, y, x + 200, y + 64), fill="#FFF8F1", outline="#F1DDCC", radius=18)
        draw.text((x + 14, y + 10), label.upper(), font=SMALL_BOLD_FONT, fill=MUTED)
        value_lines = wrap_text(draw, value, BODY_FONT, 172)
        draw_lines(draw, (x + 14, y + 30), value_lines, BODY_FONT, INK, spacing=4)
        x += 214
        if index == 3:
            x = PADDING + 24
            y += 74

    rounded_card(canvas, (PADDING, 360, 930, HEIGHT - 56))
    draw.text((PADDING + 24, 384), "Transcript Excerpt", font=CARD_TITLE_FONT, fill=INK)
    draw.text((PADDING + 24, 418), "Synthetic session paused on clarification for a deterministic demo walkthrough.", font=SMALL_FONT, fill=MUTED)

    bubble_y = 458
    for role, content in transcript_excerpt(messages):
        fill = "#FFF2E3" if role == "Candidate Answer" else "#FFFFFF"
        outline = "#EAC59E" if role == "Candidate Answer" else "#E0D8D0"
        max_width = 770
        lines = wrap_text(draw, content, BODY_FONT, max_width - 36)
        height = 54 + text_block_height(draw, lines, BODY_FONT, spacing=7)
        rounded_card(canvas, (PADDING + 24, bubble_y, PADDING + 24 + max_width, bubble_y + height), fill=fill, outline=outline, radius=24)
        draw.text((PADDING + 44, bubble_y + 16), role, font=SMALL_BOLD_FONT, fill="#8A5521" if role == "Candidate Answer" else "#5C4B3E")
        draw_lines(draw, (PADDING + 44, bubble_y + 38), lines, BODY_FONT, INK, spacing=7)
        bubble_y += height + 16

    rounded_card(canvas, (964, 360, WIDTH - PADDING, 694))
    draw.text((988, 384), "Evaluation Summary", font=CARD_TITLE_FONT, fill=INK)
    draw_chip(draw, (988, 428), f"Verdict {metadata.get('verdict', 'n/a').capitalize()}", SOFT_GOLD, "#8A5521")
    draw_chip(draw, (1138, 428), f"Assessment Score {metadata.get('score', 'n/a')}/5", SOFT_GREEN, "#2F6B40")
    rows = [
        ("Decision Source", backend_label(metadata.get("backend"))),
        ("Fallback Activated", "Yes" if metadata.get("used_fallback") else "No"),
        ("Evaluation Rationale", evaluation.get("content", "No evaluation available.")),
        ("Missing Evidence", ", ".join(metadata.get("missing_points") or []) or "none"),
        ("Next Action", metadata.get("follow_up") or "Continue to the next question"),
    ]
    row_y = 486
    for label, value in rows:
        draw.text((988, row_y), label, font=SMALL_BOLD_FONT, fill=MUTED)
        lines = wrap_text(draw, value, BODY_FONT, 520)
        row_y = draw_lines(draw, (988, row_y + 22), lines, BODY_FONT, INK, spacing=7) + 14

    rounded_card(canvas, (964, 724, WIDTH - PADDING, HEIGHT - 56))
    draw.text((988, 748), "Prompt Version", font=CARD_TITLE_FONT, fill=INK)
    prompt = snapshot["prompt_store"].load_version(interview["prompt_version"])
    prompt_lines = [
        f"Version: {prompt.version}",
        f"Description: {prompt.description}",
        f"Clarification Limit: {prompt.max_clarifications}",
        "Prompt editing is hidden from the public demo surface.",
    ]
    y = 790
    for line in prompt_lines:
        lines = wrap_text(draw, line, BODY_FONT, 520)
        y = draw_lines(draw, (988, y), lines, BODY_FONT, INK, spacing=7) + 14

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path)


def render_prompt_governance(snapshot: Dict[str, Any], output_path: Path) -> None:
    """Render the prompt governance asset."""
    prompt_store = snapshot["prompt_store"]
    active_prompt = prompt_store.load_active()
    prompt_versions = prompt_store.list_versions()
    prompt_yaml = yaml.safe_dump(active_prompt.raw, sort_keys=False).splitlines()

    canvas = gradient_background()
    draw = ImageDraw.Draw(canvas)
    draw_header(
        draw,
        "Prompt Governance",
        "Read-only prompt version visibility with an active version summary, history, and collapsed definition excerpt.",
    )

    rounded_card(canvas, (PADDING, 178, 720, 470))
    draw.text((PADDING + 24, 202), "Active Prompt Version", font=CARD_TITLE_FONT, fill=INK)
    draw_chip(draw, (PADDING + 24, 246), f"Prompt Version {active_prompt.version}", SOFT_BLUE, "#2A5B7F")
    draw_chip(draw, (PADDING + 220, 246), "Read-only surface", SOFT_GREEN, "#2F6B40")
    summary = [
        ("Description", active_prompt.description),
        ("Clarification Limit", str(active_prompt.max_clarifications)),
        ("Question Sets", str(len(active_prompt.raw.get("skills", {})))),
        ("Prompt Editing", "Disabled in public demo mode"),
    ]
    y = 304
    for label, value in summary:
        draw.text((PADDING + 24, y), label, font=SMALL_BOLD_FONT, fill=MUTED)
        lines = wrap_text(draw, value, BODY_FONT, 620)
        y = draw_lines(draw, (PADDING + 24, y + 22), lines, BODY_FONT, INK, spacing=7) + 14

    rounded_card(canvas, (750, 178, WIDTH - PADDING, 470))
    draw.text((774, 202), "Prompt Version History", font=CARD_TITLE_FONT, fill=INK)
    y = 250
    for prompt in prompt_versions:
        state = "active" if prompt.version == active_prompt.version else "available"
        rounded_card(canvas, (774, y, WIDTH - PADDING - 24, y + 74), fill="#FFF8F1", outline="#F1DDCC", radius=18)
        draw.text((792, y + 14), f"{prompt.version} ({state})", font=BODY_BOLD_FONT, fill=INK)
        lines = wrap_text(draw, prompt.description, BODY_FONT, 700)
        draw_lines(draw, (792, y + 38), lines, BODY_FONT, MUTED, spacing=6)
        y += 86

    rounded_card(canvas, (PADDING, 506, WIDTH - PADDING, HEIGHT - 56))
    draw.text((PADDING + 24, 530), "Collapsed Prompt Definition Excerpt", font=CARD_TITLE_FONT, fill=INK)
    draw.text((PADDING + 24, 564), "The full prompt is available behind an expand action in the public UI. This screenshot shows only a readable excerpt.", font=SMALL_FONT, fill=MUTED)
    excerpt = prompt_yaml[:18]
    y = 610
    for line in excerpt:
        draw.text((PADDING + 24, y), line, font=MONO_FONT, fill=INK)
        y += 24

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path)


def render_review_trace(snapshot: Dict[str, Any], output_path: Path) -> None:
    """Render the review trace asset with persisted workflow reasoning."""
    interview = snapshot["trace_session"]
    entries = _review_trace_entries(interview["messages"])
    summary = snapshot["feedback_summary"]
    suggestion = snapshot["prompt_suggestions"][0]
    common_flags = ", ".join(f"{item['flag']} ({item['count']})" for item in summary["common_flags"]) or "none"

    canvas = gradient_background()
    draw = ImageDraw.Draw(canvas)
    draw_header(
        draw,
        "Review Trace",
        "Stored answer-to-evaluation history showing why the workflow clarified, advanced, and remained replayable after reload.",
    )

    rounded_card(canvas, (PADDING, 178, 980, HEIGHT - 56))
    draw.text((PADDING + 24, 202), "Interaction Trace", font=CARD_TITLE_FONT, fill=INK)
    y = 248
    for index, entry in enumerate(entries[:3], start=1):
        rounded_card(canvas, (PADDING + 24, y, 948, y + 210), fill="#FFF8F1", outline="#F1DDCC", radius=20)
        draw.text((PADDING + 42, y + 16), f"Interaction {index}", font=BODY_BOLD_FONT, fill=INK)
        blocks = [
            ("Candidate Answer", entry["candidate_answer"]),
            ("Evaluation Summary", entry["evaluation_summary"]),
            ("Missing Evidence", entry["missing_evidence"]),
            ("Action Taken", entry["action_taken"]),
            ("State Transition", entry["state_transition"]),
        ]
        row_y = y + 48
        for label, value in blocks:
            draw.text((PADDING + 42, row_y), label, font=SMALL_BOLD_FONT, fill=MUTED)
            lines = wrap_text(draw, value, BODY_FONT, 840)
            row_y = draw_lines(draw, (PADDING + 42, row_y + 20), lines, BODY_FONT, INK, spacing=6) + 8
        y += 226

    rounded_card(canvas, (1014, 178, WIDTH - PADDING, 470))
    draw.text((1038, 202), "Feedback Summary", font=CARD_TITLE_FONT, fill=INK)
    chips = [
        (f"Quality {summary['average_quality']:.1f}", SOFT_GOLD, "#8A5521"),
        (f"Fairness {summary['average_fairness']:.1f}", SOFT_GREEN, "#2F6B40"),
        (f"Relevance {summary['average_relevance']:.1f}", SOFT_BLUE, "#2A5B7F"),
    ]
    chip_x = 1038
    for label, bg, fg in chips:
        chip_x += draw_chip(draw, (chip_x, 246), label, bg, fg) + 10
    feedback_lines = [
        f"Reviewed Sessions: {summary['reviewed_interviews']}",
        f"Common Flags: {common_flags}",
    ]
    y = 314
    for line in feedback_lines:
        lines = wrap_text(draw, line, BODY_FONT, 500)
        y = draw_lines(draw, (1038, y), lines, BODY_FONT, INK, spacing=7) + 14

    rounded_card(canvas, (1014, 500, WIDTH - PADDING, HEIGHT - 56))
    draw.text((1038, 524), "Prompt Suggestion", font=CARD_TITLE_FONT, fill=INK)
    draw.text((1038, 566), suggestion["title"], font=BODY_BOLD_FONT, fill=INK)
    draw.text((1038, 596), f"Priority: {suggestion['priority']}", font=SMALL_BOLD_FONT, fill=MUTED)
    evidence_text = "; ".join(suggestion["evidence"])
    blocks = [
        ("Evidence", evidence_text),
        ("Suggested Change", suggestion["suggested_change"]),
    ]
    y = 638
    for label, value in blocks:
        draw.text((1038, y), label, font=SMALL_BOLD_FONT, fill=MUTED)
        lines = wrap_text(draw, value, BODY_FONT, 500)
        y = draw_lines(draw, (1038, y + 20), lines, BODY_FONT, INK, spacing=7) + 14

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path)


def main() -> None:
    """Render the three public-facing image assets."""
    snapshot = load_demo_context()
    output_dir = ROOT / "docs" / "assets"
    render_interview_view(snapshot, output_dir / "interview-view.png")
    render_prompt_governance(snapshot, output_dir / "prompt-governance.png")
    render_review_trace(snapshot, output_dir / "review-trace.png")
    print(f"Rendered assets to {output_dir}")


if __name__ == "__main__":
    main()
