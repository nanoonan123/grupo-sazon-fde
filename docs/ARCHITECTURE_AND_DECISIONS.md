# Architecture and Decisions

## Scope

This document records the initial technical boundaries and provisional choices for
the candidate screening application. It complements, rather than repeats, the
Phase 1 Process Design in `PROCESS_DESIGN.docx`.

The current foundation provides configuration, structured domain contracts,
deterministic eligibility rules, a health endpoint, synthetic service-area data,
and tests. Conversation orchestration, model calls, persistence, retrieval,
voice, and user-facing pages remain planned.

## Five-layer separation

| Layer | Responsibility | Boundary |
| --- | --- | --- |
| LLM | Understand candidate language, extract proposed values, and draft responses. | It does not decide eligibility or write authoritative state directly. |
| LangGraph | Manage conversation state and explicit transitions between screening stages. | It coordinates work but does not replace domain validation. |
| Pydantic | Define and validate the structured contract shared by application layers. | It guarantees shape and basic constraints, not business outcomes. |
| Domain rules | Validate completion and determine qualification from structured inputs. | It is deterministic and has no model dependency. |
| Database | Hold authoritative application state, decisions, and audit history. | It is the source of truth; chat or graph memory is not. |

This separation keeps probabilistic interpretation outside the decision boundary.
Extracted values must pass through the structured contract and deterministic rules
before they can affect an outcome.

## Provisional technology decisions

| Concern | Provisional choice | Rationale | Status |
| --- | --- | --- | --- |
| Runtime | Python 3.12 or 3.13 | Current language features and broad library support | Adopted |
| HTTP API | FastAPI with Uvicorn | Typed async API with simple operational tooling | Foundation only |
| Configuration | Pydantic Settings | Typed environment-based configuration | Adopted |
| Data contracts | Pydantic | Explicit validation at layer boundaries | Adopted |
| Domain logic | Plain Python functions | Easy to test, audit, and keep deterministic | Adopted |
| Orchestration | LangGraph | Explicit conversational state and transitions | Planned |
| Model provider | OpenAI API | Language understanding and response generation | Planned |
| Persistence | SQLAlchemy async with SQLite initially | Portable local demo path with an upgrade route | Planned |
| Server-rendered UI | Jinja2 plus HTML/CSS/JavaScript | Lightweight mobile web experience | Planned |
| Retrieval | To be selected after approved content is available | Avoid premature knowledge architecture | Planned |
| Voice | ElevenLabs integration | Candidate-initiated browser voice | Planned |
| Testing and linting | pytest, pytest-asyncio, and Ruff | Fast automated feedback | Adopted |

These choices are intentionally provisional where integration behavior, scale, or
client requirements have not yet been validated.

## Frontend and agent language boundary

The browser experience may use HTML, CSS, and JavaScript because those are the
native technologies for accessible interaction, responsive layout, and optional
browser media controls. This does not move agent policy into the browser. The core
agent, structured validation, orchestration, and eligibility rules remain in
Python behind the API. The frontend exchanges explicit request and response
contracts with that backend and must not independently determine qualification.

## Immediate constraints

- Service-area entries are synthetic demo configuration, not researched business
  locations.
- Domain rules must remain independent of LLMs and orchestration frameworks.
- Secrets belong in local environment variables and must never be committed.
- A database will become the source of truth when persistence is implemented; no
  persistence exists in this foundation.
