# Architecture At A Glance

## System shape

```mermaid
flowchart LR
    A["Browser UI"] --> B["FastAPI / API layer"]
    B --> C["Interview Engine / State Manager"]
    C --> D["Persistence (SQLite)"]
    C --> E["Prompt Version Manager"]
    D --> F["Review Summary / Analytics"]
    F --> A
```

## Runtime flow

```mermaid
flowchart LR
    A["Candidate response"] --> B["Evaluation"]
    B --> C{"Clarify or advance"}
    C --> D["Persist result"]
    D --> E["Render reviewer summary"]
```

## Notes

- The API layer exposes session, feedback, comparison, and prompt-version endpoints.
- The interview engine owns explicit `asking`, `clarifying`, and `completed` state transitions.
- SQLite stores transcript turns, evaluation summary metadata, reviewer feedback, and prompt-version linkage.
- Prompt mutation is admin-gated; prompt version visibility stays read-only in the public UI.
