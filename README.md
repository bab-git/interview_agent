# Production Interview Agent

This repository contains a complete take-home solution for a production conversational interview agent with a human feedback loop and prompt versioning. The system exposes a deployable FastAPI API, persists interview conversations and evaluator feedback in SQLite, supports prompt activation for future interviews, and includes automated tests plus reviewer demo scripts.

A browser-based Gradio test UI is also available at `/ui`, so reviewers can run the interview loop, inspect state transitions, and submit evaluator feedback without using `curl`.

## Contents

- [Assignment Coverage](#assignment-coverage)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Assumptions](#assumptions)
- [Setup](#setup)
- [Running the Service](#running-the-service)
- [Visual Inspection](#visual-inspection)
- [Gradio Live UI](#gradio-live-ui)
- [API Walkthrough](#api-walkthrough)
- [Closing the Loop Workflow](#closing-the-loop-workflow)
- [Reviewer Demo](#reviewer-demo)
- [Prompt Update Path](#prompt-update-path)
- [Testing](#testing)
- [Endpoints](#endpoints)
- [Resilience Notes](#resilience-notes)
- [What a Reviewer Can Quickly Verify](#what-a-reviewer-can-quickly-verify)
- [GitHub Actions Pipeline](#github-actions-pipeline)
- [Notes](#notes)

Bonus features are also implemented locally in this branch:

- A/B comparison support for completed conversations
- feedback aggregation across conversations
- prompt update API for creating new prompt versions
- automated prompt-improvement suggestions from evaluator feedback
- a GitHub Actions pipeline that runs CI, publishes container images, and includes an optional deployment stage

The implementation is intentionally built around an explicit interview state machine rather than a single LLM call. Each interview follows:

1. Start interview with one selected skill.
2. Ask question 1.
3. Evaluate the candidate answer.
4. Ask a clarification if the answer is incomplete or ambiguous.
5. Advance to the next question.
6. Repeat until all 3 questions are complete.
7. Wrap up and persist the final conversation state.

## Assignment Coverage

### Required (Must Have)

1. Stateful interview flow
   Covered by [app/services/interview_engine.py](app/services/interview_engine.py).
   The engine tracks `phase`, `status`, `current_question_index`, and `clarification_count`, and implements `ask -> evaluate -> clarify -> next question`.
   Verified by [tests/test_interview_engine.py](tests/test_interview_engine.py) and [tests/test_api_flow.py](tests/test_api_flow.py).

2. Deployable interface
   Covered by the FastAPI service in [app/main.py](app/main.py).
   The agent is callable over HTTP through `POST /api/interviews` and `POST /api/interviews/{interview_id}/reply`.
   Verified by [scripts/live_smoke_test.py](scripts/live_smoke_test.py).

3. Feedback submission with persistence
   Covered by `POST /api/feedback` and SQLite persistence in [app/db.py](app/db.py).
   Feedback is stored and can later be retrieved for a given conversation.
   Verified by [tests/test_feedback_api.py](tests/test_feedback_api.py).

4. Conversation retrieval
   Covered by `GET /api/interviews/{interview_id}` and `GET /api/interviews`.
   Evaluators can retrieve a completed interview by ID and inspect the full transcript and metadata.
   Verified by [tests/test_api_flow.py](tests/test_api_flow.py).

5. Prompt loading from configuration
   Covered by [app/prompts.py](app/prompts.py) using versioned files under [prompts/versions](prompts/versions) and an active prompt selector in [prompts/active_prompt.json](prompts/active_prompt.json).
   New interviews use the active prompt version at the time they start.
   Verified by [tests/test_prompt_loading.py](tests/test_prompt_loading.py).

6. Tests
   Included:
   - [tests/test_interview_engine.py](tests/test_interview_engine.py)
   - [tests/test_feedback_api.py](tests/test_feedback_api.py)
   - [tests/test_prompt_loading.py](tests/test_prompt_loading.py)
   - [tests/test_api_flow.py](tests/test_api_flow.py)

7. README
   This file documents setup, running, assumptions, feedback submission, prompt updates, testing, and the reviewer walkthrough.

8. Demo walkthrough
   Covered by `make demo` and [scripts/demo_flow.py](scripts/demo_flow.py).
   The demo walks through: start interview -> complete interview -> retrieve conversation -> submit feedback -> activate prompt -> start new interview with the updated prompt.

### Expected

1. Containerized deployment
   Covered by [Dockerfile](Dockerfile) and [docker-compose.yml](docker-compose.yml).

2. Conversation discovery and filtering
   Covered by `GET /api/interviews` filters for `skill`, `status`, `reviewed`, `date_from`, `date_to`, and `prompt_version`.
   Implemented in [app/main.py](app/main.py) and [app/db.py](app/db.py).

3. Prompt versioning
   Covered by YAML prompt versions in [prompts/versions](prompts/versions), activation through `POST /api/prompts/activate`, and `prompt_version` persisted on every interview.

4. Error handling and resilience
   Covered by:
   - heuristic fallback if the local LLM is unavailable or returns invalid JSON
   - HTTP `409` for invalid interview state transitions
   - HTTP `409` for feedback submitted before completion
   - health reporting for backend reachability

5. Basic observability
   Covered by:
   - `GET /health`
   - `GET /api/metrics`
   - structured JSON event logs through [app/logging_utils.py](app/logging_utils.py)

### Bonus (Nice to Have)

1. A/B comparison
   Covered by `GET /api/comparisons` and `POST /api/comparisons/feedback`.
   Evaluators can compare two completed interviews side by side and submit a preference.
   Verified by [tests/test_bonus_features.py](tests/test_bonus_features.py).

2. Feedback aggregation
   Covered by `GET /api/feedback/summary`.
   The API returns aggregate averages, common flags, and grouped summaries by skill and prompt version.
   Verified by [tests/test_bonus_features.py](tests/test_bonus_features.py).

3. CI pipeline plus optional CD scaffold
   Covered by [ci.yml](.github/workflows/ci.yml).
   The workflow runs tests, validates the Docker build, publishes the app image to GHCR, and includes an optional SSH-based deployment stage.
   The deployment stage is gated behind the `ENABLE_CD=true` repository variable plus the required GitHub secrets, so the repository remains usable without provisioning a real target host.

4. Prompt update API
   Covered by `POST /api/prompts`.
   A new prompt version can be created from an existing base version, optionally activated immediately, and stored in [prompts/versions](prompts/versions).
   Verified by [tests/test_bonus_features.py](tests/test_bonus_features.py).

5. Automated prompt improvement suggestions
   Covered by `GET /api/prompts/suggestions`.
   Suggestions are derived from persisted evaluator feedback and common issue flags.
   Verified by [tests/test_bonus_features.py](tests/test_bonus_features.py).

## Architecture

### Why this design

- The interview flow is implemented as a state machine in [app/services/interview_engine.py](app/services/interview_engine.py), which keeps transitions explicit and testable.
- Prompt instructions are file-backed and versioned, which makes prompt changes auditable and easy to review.
- SQLite keeps the solution simple to run locally while still providing durable persistence for interviews and evaluator feedback.
- FastAPI provides a deployable interface and auto-generated API documentation at `/docs`.
- Local LLM support is implemented with Ollama in [app/services/llm.py](app/services/llm.py). The default model is `llama3.2:1b`, which is small enough for modest local hardware.
- A deterministic `mock` backend is included for tests and reviewer verification, so the system can be validated even when a local model is not running.

### Supported skills

- `Problem Solving`
- `Communication`
- `Collaboration & Teamwork`

### High-level components

- [app/main.py](app/main.py): API routes and request handling
- [app/gradio_ui.py](app/gradio_ui.py): mounted Gradio browser UI for live interview testing
- [app/services/interview_engine.py](app/services/interview_engine.py): interview state machine and evaluation loop
- [app/services/llm.py](app/services/llm.py): Ollama and mock backends
- [app/db.py](app/db.py): SQLite persistence layer
- [app/prompts.py](app/prompts.py): prompt version loading and activation
- [app/services/review_analytics.py](app/services/review_analytics.py): aggregated feedback reporting and prompt suggestions
- [prompts/versions](prompts/versions): editable prompt definitions

## Project Structure

```text
app/
  config.py
  db.py
  gradio_ui.py
  logging_utils.py
  main.py
  models.py
  prompts.py
  schemas.py
  services/
    interview_engine.py
    llm.py
prompts/
  active_prompt.json
  versions/
    v1.yaml
    v2.yaml
scripts/
  bonus_demo.py
  demo_flow.py
  live_smoke_test.py
tests/
  test_gradio_ui.py
Dockerfile
docker-compose.yml
Makefile
requirements.txt
```

## Assumptions

- One prompt version is active for new interviews at a time.
- Each question allows at most one clarification before the agent moves on.
- Evaluators can use either the API/scripts or the mounted Gradio UI, depending on whether they want a browser-based workflow.
- The local-model path is meant for Ollama.
- Automated tests use the deterministic mock backend for repeatability.

## Setup

### Local Python setup

```bash
make install
```

### Environment variables

Defaults are already wired in code, but you can override them with environment variables:

- `APP_DB_PATH`
- `APP_DATA_DIR`
- `LLM_BACKEND`
- `OLLAMA_HOST`
- `OLLAMA_MODEL`
- `PROMPT_ACTIVE_FILE`
- `PROMPT_VERSIONS_DIR`

Reference values are provided in [.env.example](.env.example).

## Running the Service

### Option 1: Deterministic reviewer mode

This mode does not require a real local model and is the easiest way to test the full flow:

```bash
LLM_BACKEND=mock make run
```

The API will be available at [http://127.0.0.1:8000](http://127.0.0.1:8000).
The mounted Gradio UI will be available at [http://127.0.0.1:8000/ui](http://127.0.0.1:8000/ui).

### Option 2: Real local LLM with Ollama

1. Start Ollama:

```bash
ollama serve
```

2. Pull a small local model:

```bash
ollama pull llama3.2:1b
```

3. Run the app:

```bash
LLM_BACKEND=ollama OLLAMA_MODEL=llama3.2:1b make run
```

Then open [http://127.0.0.1:8000/ui](http://127.0.0.1:8000/ui) for the live browser UI.

### Option 3: Containerized stack

If Docker is available:

```bash
docker compose up --build
```

This starts:

- an Ollama service
- a one-time model pull job for `llama3.2:1b`
- the FastAPI app

## Visual Inspection

Once the service is running, open:

- [http://127.0.0.1:8000/ui](http://127.0.0.1:8000/ui)
- [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

The Gradio page gives you a browser-based live test harness for the interview pipeline. The FastAPI docs pages let a reviewer inspect and call the raw API directly.

The bonus endpoints also appear in the API docs, so you can inspect comparison, summary, and prompt-suggestion responses visually.

## Gradio Live UI

The mounted Gradio UI at [http://127.0.0.1:8000/ui](http://127.0.0.1:8000/ui) is the fastest way to live-test the interview pipeline end to end.

It includes:

- a chat-style interview runner for starting an interview and replying turn by turn
- a live state panel showing phase, question index, clarifications used, prompt version, and backend
- a latest-evaluation panel showing verdict, score, follow-up, and fallback usage
- a full transcript panel including evaluation messages
- a reviewer workbench for loading completed conversations and submitting feedback without leaving the browser

### Step-by-step live UI test

1. Install dependencies:

```bash
make install
```

2. Start the service in deterministic mock mode:

```bash
LLM_BACKEND=mock make run
```

3. Open the UI:

- [http://127.0.0.1:8000/ui](http://127.0.0.1:8000/ui)

4. In the `Live Interview` tab:

- optionally enter a candidate name
- choose one of the supported skills
- click `Start Interview`

5. Confirm the initial interview state:

- the chat shows the welcome message and first question
- `Current Interview ID` is populated
- the right-side state panel shows the interview as `active`

6. Trigger the clarification branch:

- send a short answer such as `I fixed an outage quickly.`
- confirm the chat shows a clarification prompt
- confirm the latest evaluation panel shows verdict `clarify`

7. Continue the interview:

- reply with a more complete answer containing context, decision process, and outcome
- confirm the next question appears
- repeat until all 3 questions are completed

8. Confirm completion:

- the wrap-up message appears in chat
- the state panel shows `completed`
- the completion timestamp is populated

9. Test interview reload:

- copy the interview ID
- refresh the page
- paste the ID into `Load Interview By ID`
- click `Load`
- confirm the transcript and state reload correctly

10. Test the reviewer flow:

- open the `Reviewer Workbench` tab
- click `Refresh Interviews`
- select the completed interview from the dropdown
- confirm the conversation replay and transcript load

11. Submit evaluator feedback:

- enter an optional evaluator ID
- choose quality, fairness, and relevance scores
- optionally add flags and notes
- click `Submit Feedback`

12. Confirm feedback persistence:

- a success message appears
- the feedback summary panel updates
- the prompt suggestion panel updates

13. Optional API cross-check:

- open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- call `GET /api/interviews/{interview_id}` using the same interview ID
- verify the stored conversation matches the UI transcript

## API Walkthrough

### 1. Start an interview

```bash
curl -s http://127.0.0.1:8000/api/interviews \
  -H 'Content-Type: application/json' \
  -d '{"skill":"Problem Solving","candidate_name":"Taylor"}'
```

### 2. Reply to the current question

```bash
curl -s http://127.0.0.1:8000/api/interviews/<INTERVIEW_ID>/reply \
  -H 'Content-Type: application/json' \
  -d '{"content":"I solved a production issue by tracing an indexing regression, rolling back safely, and validating recovery with latency metrics."}'
```

### 3. Retrieve a conversation by ID

```bash
curl -s http://127.0.0.1:8000/api/interviews/<INTERVIEW_ID>
```

### 4. Discover conversations with filters

```bash
curl -s 'http://127.0.0.1:8000/api/interviews?skill=Problem%20Solving&reviewed=false'
```

### 5. Submit evaluator feedback

```bash
curl -s http://127.0.0.1:8000/api/feedback \
  -H 'Content-Type: application/json' \
  -d '{
    "interview_id":"<INTERVIEW_ID>",
    "evaluator_id":"reviewer-1",
    "overall_quality":4,
    "fairness":5,
    "relevance":4,
    "flags":["weak_followup"],
    "notes":"The interview was solid overall but one probe could be sharper."
  }'
```

### 6. Retrieve feedback for a conversation

```bash
curl -s http://127.0.0.1:8000/api/interviews/<INTERVIEW_ID>/feedback
```

### 7. List prompt versions

```bash
curl -s http://127.0.0.1:8000/api/prompts
```

### 8. Activate a new prompt version

```bash
curl -s http://127.0.0.1:8000/api/prompts/activate \
  -H 'Content-Type: application/json' \
  -d '{"version":"v2"}'
```

Every new interview started after activation records `prompt_version: "v2"`.

### 9. Create a new prompt version through the API

```bash
curl -s http://127.0.0.1:8000/api/prompts \
  -H 'Content-Type: application/json' \
  -d '{
    "version":"v3",
    "description":"Prompt created through the API",
    "base_version":"v2",
    "activate":true,
    "skill_question_overrides":{
      "Problem Solving":[
        {
          "id":"ps1",
          "prompt":"Tell me about a hard technical problem and the trade-offs you weighed."
        }
      ]
    }
  }'
```

### 10. Compare two completed conversations

```bash
curl -s 'http://127.0.0.1:8000/api/comparisons?left_id=<LEFT_ID>&right_id=<RIGHT_ID>'
```

### 11. Submit A/B comparison feedback

```bash
curl -s http://127.0.0.1:8000/api/comparisons/feedback \
  -H 'Content-Type: application/json' \
  -d '{
    "left_interview_id":"<LEFT_ID>",
    "right_interview_id":"<RIGHT_ID>",
    "preferred_conversation_id":"<RIGHT_ID>",
    "evaluator_id":"reviewer-compare",
    "overall_quality":4,
    "fairness":4,
    "relevance":5,
    "flags":["weak_followup"],
    "notes":"The right-hand interview felt more precise."
  }'
```

### 12. View aggregated evaluator feedback

```bash
curl -s http://127.0.0.1:8000/api/feedback/summary
```

### 13. Generate prompt improvement suggestions

```bash
curl -s http://127.0.0.1:8000/api/prompts/suggestions
```

### 14. Check health and metrics

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/metrics
```

## Closing the Loop Workflow

The assignment asks for more than collecting feedback. A reviewer should be able to inspect a finished conversation, record evaluation feedback, use that feedback to update prompts, and then confirm that new interviews pick up the change.

This repository supports that full loop over HTTP:

1. Run and complete an interview

   Start an interview with `POST /api/interviews`, answer all 3 questions through `POST /api/interviews/{interview_id}/reply`, and keep the returned `interview_id`.

2. Retrieve the completed conversation

   Use `GET /api/interviews/{interview_id}` to inspect the stored transcript, evaluation messages, selected skill, and recorded `prompt_version`.

3. Submit evaluator feedback

   Use `POST /api/feedback` to persist reviewer scores, issue flags, and notes for that completed conversation.

4. Review the accumulated evaluator signal

   Use `GET /api/interviews/{interview_id}/feedback` to inspect feedback for one conversation.
   Use `GET /api/feedback/summary` to see aggregate quality/fairness/relevance and common flags across conversations.
   Use `GET /api/prompts/suggestions` to generate prompt-improvement suggestions from stored evaluator feedback.

5. Create or activate an updated prompt version

   Use `POST /api/prompts` to create a new prompt version derived from an existing one, or update a prompt file under [prompts/versions](prompts/versions) and activate it with `POST /api/prompts/activate`.

6. Run a new interview and verify the prompt change is live

   Start another interview with `POST /api/interviews` and confirm the response now shows the new `prompt_version`.
   This provides a traceable link between evaluator feedback, prompt changes, and the next generation of interviews.

If you want the fastest proof of this end-to-end loop, run:

```bash
make install
make demo
```

[scripts/demo_flow.py](scripts/demo_flow.py) demonstrates the full sequence in one pass:

- start interview
- trigger clarification
- complete interview
- retrieve conversation
- submit feedback
- activate updated prompt
- start a new interview that records the new prompt version

## Reviewer Demo

### Fastest guided walkthrough

```bash
make install
make demo
```

[scripts/demo_flow.py](scripts/demo_flow.py) runs an end-to-end in-process demonstration with the mock backend and prints:

- prompt discovery
- interview start
- clarification turn
- interview completion
- conversation retrieval
- feedback submission
- prompt activation
- a second interview proving the new prompt version is in use

### Live deployed-interface walkthrough

1. Start the server:

```bash
LLM_BACKEND=mock make run
```

2. In another terminal, run:

```bash
python scripts/live_smoke_test.py --base-url http://127.0.0.1:8000
```

This validates the actual HTTP interface rather than the in-process test client.

## Prompt Update Path

Prompt behavior is controlled by files in [prompts/versions](prompts/versions). The currently active prompt is selected in [prompts/active_prompt.json](prompts/active_prompt.json).

To update prompts:

1. Add or edit a version file in [prompts/versions](prompts/versions).
2. Activate the target version:

```bash
curl -s http://127.0.0.1:8000/api/prompts/activate \
  -H 'Content-Type: application/json' \
  -d '{"version":"v2"}'
```

3. Start a new interview.
4. Confirm the new `prompt_version` in the interview response.

This makes prompt usage traceable per conversation.

## Testing

### Automated tests

```bash
make test
```

### Test coverage map

- Core state transitions: [tests/test_interview_engine.py](tests/test_interview_engine.py)
- Feedback persistence and retrieval: [tests/test_feedback_api.py](tests/test_feedback_api.py)
- Prompt activation and loading: [tests/test_prompt_loading.py](tests/test_prompt_loading.py)
- Full API flow, retrieval, discovery, and metrics: [tests/test_api_flow.py](tests/test_api_flow.py)
- Bonus features: [tests/test_bonus_features.py](tests/test_bonus_features.py)

### Live smoke test

Start the service:

```bash
LLM_BACKEND=mock make run
```

Then run:

```bash
python scripts/live_smoke_test.py --base-url http://127.0.0.1:8000
```

Or, if using the Makefile shortcut:

```bash
make smoke
```

## Endpoints

- `GET /health`
- `GET /api/metrics`
- `GET /api/prompts`
- `POST /api/prompts`
- `POST /api/prompts/activate`
- `GET /api/prompts/suggestions`
- `POST /api/interviews`
- `GET /api/interviews`
- `GET /api/interviews/{interview_id}`
- `POST /api/interviews/{interview_id}/reply`
- `POST /api/feedback`
- `GET /api/feedback/summary`
- `GET /api/interviews/{interview_id}/feedback`
- `GET /api/comparisons`
- `POST /api/comparisons/feedback`

## Resilience Notes

- If Ollama is unavailable or returns malformed output, the engine falls back to a heuristic evaluator so the interview can continue.
- Invalid workflow transitions return meaningful HTTP errors instead of silently corrupting state.
- Feedback submission is blocked until the interview is complete.
- The health endpoint reports backend reachability.

## What a Reviewer Can Quickly Verify

1. The interview is multi-step and stateful, not a single LLM call.
2. The API is deployable and callable.
3. Feedback is stored and retrievable.
4. Conversations are retrievable and filterable.
5. Prompt versions are configurable and recorded per conversation.
6. The system includes tests, a demo script, health checks, and metrics.

## GitHub Actions Pipeline

All required assignment features still work locally without GitHub. The GitHub-specific addition is an optional Actions pipeline in [ci.yml](.github/workflows/ci.yml).

### What the workflow now does

On every push or pull request, GitHub Actions will:

- install dependencies
- run the test suite
- validate that the Docker image builds successfully

On pushes, GitHub Actions will also:

- publish the image to GitHub Container Registry as `ghcr.io/<owner>/<repo>:<sha>`
- tag `ghcr.io/<owner>/<repo>:latest` on `main`

On pushes to `main`, GitHub Actions can additionally run the optional deploy stage if CD is enabled:

- copy [docker-compose.production.yml](deploy/docker-compose.production.yml) to the target server
- write a deployment env file with the exact image tag being released
- pull the published image from GHCR
- restart the production stack with Docker Compose
- verify the deployment through `GET /health`

### What you would need to enable CD

Repository variable:

- `ENABLE_CD=true`
- optional `DEPLOY_PATH` default is `/opt/production-interview-agent`
- optional `APP_PORT` default is `8000`
- optional `LLM_BACKEND` default is `ollama`
- optional `OLLAMA_MODEL` default is `llama3.2:1b`
- optional `REQUEST_TIMEOUT_SECONDS` default is `30`

Repository secrets:

- `DEPLOY_HOST`: hostname or IP of the Docker server
- `DEPLOY_USER`: SSH user on the target host
- `DEPLOY_SSH_KEY`: private key for that host
- `GHCR_USERNAME`: GitHub username that can read the package
- `GHCR_TOKEN`: GitHub token or PAT with package read access on the target host

Target host prerequisites:

- Docker with the Compose plugin installed
- `curl` available for the post-deploy health check
- network access to pull images from `ghcr.io`

### Optional deployment model

If you choose to enable the deploy stage later, it uses [docker-compose.production.yml](deploy/docker-compose.production.yml), which starts:

- the interview app from the GHCR-published image
- an Ollama container
- a one-time model pull job for `llama3.2:1b`

The production stack persists:

- SQLite interview and feedback data in a Docker volume
- prompt versions and the active prompt selection in a Docker volume
- Ollama model data in a Docker volume

The container entrypoint seeds the prompt volume from the bundled prompt files on first boot, so prompt versioning continues to work after redeploys.

At the moment, this repository includes the deployment automation and documentation, but it does not assume that a live target host has been provisioned for review.

## Notes

- The solution intentionally focuses on the required and expected items rather than the bonus features.
- The feedback schema already includes optional comparison fields so A/B review can be expanded later without redesigning the data model.
