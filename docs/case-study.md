# AI Interview Orchestration Prototype

## Overview

This repository is a production-style prototype for AI interview orchestration with explicit state transitions, persisted evaluator feedback, prompt versioning, and human-in-the-loop review. The intent was not to build a large interview product. The intent was to treat a conversational interview as a controllable workflow whose decisions can be inspected, replayed, and reviewed after the fact.

Conversational systems are often presented as if a single agent loop is enough: ask a question, read an answer, and decide what comes next. In practice, that approach makes it difficult to understand why the system advanced, when it should have paused for clarification, which prompt version shaped the interaction, and how a reviewer should assess the result later. This prototype focuses on those control points instead of on broad product scope.

The resulting system combines a browser UI, a FastAPI API layer, a small interview engine, SQLite persistence, versioned prompt files, and reviewer-facing analytics. The value of the prototype is in making the workflow legible. A session can be replayed with its current stage, its evaluation summary, its fallback path, and its prompt version intact.

## Problem

Freeform interview agents can drift. They can skip from one question to another without establishing whether the answer was sufficient, or they can generate follow-up questions that are inconsistent across sessions. That makes the interaction harder to audit and harder to test. For an interview workflow, progression needs clearer rules than “the model seemed satisfied.”

Weak answers often need clarification before progression. A short response may hint at experience without showing reasoning, constraints, evidence, or outcome. If the system advances too early, it loses the chance to collect the context that a reviewer would actually need. A useful workflow needs an explicit clarify-or-advance decision rather than a loose continuation.

Reviewer feedback also needs persistence. If evaluation summaries and review notes only exist in memory during a live session, they cannot be aggregated later, compared across prompt versions, or checked after a restart. The same is true for prompt changes: if prompts can change without traceability, it becomes difficult to explain why two similar sessions behaved differently.

## Design Goals

- controllable multi-turn flow
- inspectable decisions
- replayable review workflow
- prompt version traceability
- deterministic demo and testing behavior

## System Architecture

The Browser UI provides two main surfaces: an interview view for running or loading a session, and a review console for replaying a stored session with metadata, evaluation summary, and trace details. The UI is intentionally read-heavy. Prompt mutation is not surfaced in the public interface, while prompt version information stays visible.

The API layer is implemented with FastAPI. It exposes endpoints to start sessions, submit replies, retrieve stored sessions, list prompt versions, submit reviewer feedback, compare completed sessions, and retrieve aggregate review summaries. Prompt mutation endpoints still exist for local experimentation, but they are gated by an explicit admin flag so the public demo remains read-only by default.

The interview engine acts as the state manager. It owns the transition rules for `asking`, `clarifying`, and `completed`. Each reply is persisted before evaluation. The evaluator then decides whether the workflow should request clarification or advance to the next question. This keeps the progression logic compact, explicit, and testable.

The persistence layer uses SQLite. It stores session rows, transcript messages, evaluator metadata, reviewer feedback, and latency counters. The important design choice is that evaluation results are stored as part of the transcript rather than left as transient output. That makes the reviewer-visible summary reproducible after reload and keeps fallback activation inspectable.

Prompt/version management is separated from session data. Prompt files live on disk as named versions, and each session stores the version identifier that was active when the session began. That gives the workflow a clear audit trail without rewriting historical sessions when a prompt changes.

The review analytics layer reads persisted feedback and produces summary metrics plus prompt-improvement suggestions. Those suggestions are intentionally assistive. They point to patterns in reviewer feedback, but they do not automatically mutate prompt definitions.

## Example Walkthrough

1. An interview session begins on the problem-solving track.
2. The participant gives a vague answer such as “I fixed the issue quickly and moved on.”
3. The evaluator marks the response insufficient because it lacks context, trade-offs, and result evidence.
4. The system records that evaluation summary, stays on the same question, and asks a clarification instead of advancing.
5. The participant then gives a stronger answer with the incident context, the options considered, the path chosen, and the observed outcome.
6. The evaluator marks the answer sufficient, the state manager advances to the next question, and the updated stage is persisted.
7. A reviewer opens the stored session later and sees the current stage, prompt version, decision source, fallback status, clarification count, evaluation summary, and the trace of why the workflow clarified before it advanced.

This example is intentionally narrow. It shows the core behavior that matters for orchestration: the system does not treat the conversation as a single opaque agent loop. It records intermediate reasoning in a way that a reviewer can replay.

## Design Decisions

Explicit state transitions were chosen because a workflow with review requirements benefits from bounded behavior. Instead of asking the model to manage the entire conversation implicitly, the engine treats “asking,” “clarifying,” and “completed” as first-class states. That makes test coverage more meaningful and makes failure modes easier to reason about.

Persistence is first-class because the prototype is aimed at replayability, not only live interaction. The current stage, transcript, evaluation summary, reviewer feedback, and prompt version all need to survive restarts. Without that persistence layer, the review workflow would be mostly theatrical: visible during the session, but not durable enough to inspect later.

Prompt versioning is separated from session data so historical sessions remain stable. Each session stores only the prompt version identifier, while the prompt definition itself remains versioned configuration on disk. That separation supports prompt governance: a reviewer can tell which version shaped a session without rewriting the session when a new prompt becomes active.

Deterministic demo mode matters because portfolio review benefits from repeatability. A reviewer should be able to start the app, see seeded synthetic sessions, and walk through a stable scenario without external model dependencies. In demo mode the prototype uses deterministic mock evaluation by default, seeds known sessions, and can rebuild the same database from the same seed.

Fallback logic exists because controllable workflows still need graceful behavior when a model-backed evaluator fails. Rather than stopping the session entirely, the engine records that a fallback path was used and continues with a deterministic rule-based evaluation. That preserves the workflow while making the fallback visible in both logs and session replay.

## Extensions Beyond Core Scope

The repository also includes a comparison surface for reviewing two completed sessions side by side. That supports prompt-version comparison and reviewer preference tracking without changing the core state machine.

Feedback aggregation is implemented through reviewer feedback summary endpoints and UI panels. These summaries show average quality, fairness, relevance, and common flags across stored sessions.

A prompt update path exists for local experimentation. New prompt versions can be created and activated through the API, but that path is now admin-gated for public release so prompt mutation is not casually exposed.

Prompt-improvement suggestions are derived from stored reviewer feedback. These suggestions are assistive and exploratory; they summarize patterns in review data but do not act as automatic prompt governance.

## Limitations

- This is not a validated hiring product.
- It is not fairness-tested.
- It is not a psychometric tool.
- Storage and authentication assumptions are lightweight and oriented toward a local demo environment.

## Where This Could Go Next

The next practical step would be stronger reviewer tooling for interview platforms that need clearer session replay and workflow control rather than more autonomous behavior. A second direction would be regression testing for prompt changes so that prompt versioning is tied more directly to expected clarify-or-advance behavior. A third direction would be stronger auditability, including richer transition history and more explicit reviewer sign-off around prompt updates. More broadly, the same control model could be applied to other conversational workflows that need inspectable and replayable governance rather than freeform agent drift.
