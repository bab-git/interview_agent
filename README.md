# AI Interview Orchestration Prototype

## Overview

This project is a production-style prototype for orchestrating AI-led interviews with explicit conversation state, evaluator feedback persistence, prompt versioning, and human review support. The focus is not autonomous hiring decisions, but making conversational evaluation workflows more controllable, inspectable, and replayable.

## What it demonstrates

- explicit state transitions instead of freeform agent drift
- persisted evaluator feedback and evaluation summary data
- prompt version tracking and prompt governance surfaces
- deterministic demoability for local walkthroughs and screenshots
- review-oriented workflow design with human-in-the-loop inspection

## Core features

- FastAPI API for session start, reply handling, replay, review, comparison, and feedback aggregation
- Browser UI with a session metadata bar, evaluation summary, prompt version surface, and review trace
- SQLite persistence for transcript turns, evaluator metadata, reviewer feedback, and prompt-version linkage
- Admin-gated prompt mutation endpoints with read-only prompt version visibility in the public UI
- Deterministic demo mode with seeded synthetic sessions and stable mock evaluation behavior

## Architecture at a glance

- Browser UI mounted at `/ui`
- FastAPI application and workflow endpoints in `app/main.py`
- Interview engine and state transitions in `app/services/interview_engine.py`
- SQLite repository and persisted workflow metadata in `app/db.py`
- Versioned prompt files plus active-prompt selection in `prompts/`
- Review analytics and prompt suggestions in `app/services/review_analytics.py`

## Running locally

```bash
cp .env.example .env
make install
make demo-reset
make run
```

The UI is available at [http://127.0.0.1:8000/ui](http://127.0.0.1:8000/ui). API docs are available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## Demo mode

`APP_MODE=demo` and `DEMO_MODE=true` seed synthetic sessions, force deterministic mock evaluation by default, and keep the public walkthrough stable. To disable demo mode, set `APP_MODE=normal` and `DEMO_MODE=false` in `.env`, then restart the app. `DEMO_RESET_ON_START=true` recreates the seeded database every time the server boots.

## Project structure

```text
app/              API, workflow engine, persistence, logging, UI mounting
docs/             Case study, architecture notes, demo script, public screenshots
playwright/       Screenshot capture test for the public portfolio assets
prompts/          Active prompt pointer plus versioned prompt definitions
scripts/          Demo reset, smoke tests, and local workflow helpers
tests/            Workflow, API, UI, feedback, and prompt-governance coverage
```

## Limitations

- This is a workflow/control prototype, not a validated hiring product.
- It is not intended for autonomous candidate judgment.
- Fairness, psychometric validity, and production-grade security are out of scope.
- Prompt-improvement features are assistive and exploratory.

## Case study link

Read the main narrative in [docs/case-study.md](docs/case-study.md). The supporting diagrams live in [docs/architecture.md](docs/architecture.md).
