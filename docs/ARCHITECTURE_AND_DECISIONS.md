# Architecture and Decisions

## Scope

This document records the initial technical boundaries and provisional choices for
the candidate screening application. It complements, rather than repeats, the
Phase 1 Process Design in `PROCESS_DESIGN.docx`.

The current foundation provides configuration, structured domain contracts,
deterministic eligibility rules, a health endpoint, asynchronous persistence,
simulated ATS intake, synthetic service-area data, and tests. Conversation
orchestration, model calls, retrieval, voice, and user-facing pages remain
planned.

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
| Persistence | SQLAlchemy 2.x async with aiosqlite initially | Portable local demo path with a PostgreSQL upgrade route | Adopted for foundation |
| Server-rendered UI | Jinja2 plus HTML/CSS/JavaScript | Lightweight mobile web experience | Planned |
| Retrieval | To be selected after approved content is available | Avoid premature knowledge architecture | Planned |
| Voice | ElevenLabs integration | Candidate-initiated browser voice | Planned |
| Testing and linting | pytest, pytest-asyncio, and Ruff | Fast automated feedback | Adopted |

These choices are intentionally provisional where integration behavior, scale, or
client requirements have not yet been validated.

## Persistence and ATS intake

SQLite is the local runtime database and is accessed only through SQLAlchemy's
async engine and sessions. The schema uses portable SQLAlchemy types and UUID
strings so a later PostgreSQL migration does not require changing API identifiers
or domain contracts. Database URLs come from Pydantic Settings through the
`DATABASE_URL` environment variable.

The persistence boundary currently contains five records:

- `CandidateApplication` stores the external ATS identifier, phone number,
  source, preferred language, and application status.
- `Conversation` identifies the durable conversation associated one-to-one with
  an application.
- `Message` provides durable conversation history storage for a future slice.
- `ScreeningRecord` provides structured screening state independently of any LLM
  or orchestration context.
- `InboundEvent` stores the webhook idempotency receipt and its application link.

All identifiers are UUID strings. Application timestamps are generated as
timezone-aware UTC values. A small SQLAlchemy timestamp type restores UTC timezone
information after SQLite reads, because SQLite itself does not retain timezone
metadata.

ATS intake creates the candidate application, conversation, and inbound event in
one transaction. `InboundEvent.idempotency_key` has a unique database constraint.
Its payload digest is calculated from the validated, canonical JSON request:

- A new key creates the records and returns HTTP 201.
- The same key and digest returns the original identifiers with HTTP 200.
- The same key with a different digest returns HTTP 409.

The unique constraint remains the final concurrency guard even when two deliveries
race. The database is authoritative; LLM or future LangGraph state must never
replace these persisted records as the source of truth.

FastAPI lifespan handling creates the local schema before serving requests and
disposes the engine at shutdown. `create_all` is intentionally limited to this
foundation. Versioned migrations, expected to use Alembic, are required before a
production PostgreSQL deployment.

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
- The database is the source of truth for application, conversation, message,
  screening, and inbound-event records.


## LLM Model Selection

_Last reviewed: 22 August 2026._

### Decision principles

The screening agent does not require the most capable reasoning model available. Its main LLM responsibilities are:

1. Understand short and potentially informal candidate messages.
2. Extract screening information into a structured contract.
3. Ask concise and context-aware follow-up questions.
4. Support Spanish, English, and basic code-switching.
5. Call application tools reliably.
6. Operate with low latency and predictable cost at high volume.

Qualification is not delegated to the LLM. Deterministic domain rules validate the extracted data and produce the final outcome. Therefore, model selection should prioritize extraction reliability, tool-calling performance, multilingual quality, latency, and cost rather than maximum general reasoning capability.

Model recency is used as an initial quality filter, but being the newest or largest model is not sufficient justification. The final choice must be supported by task-specific evaluations.

### Candidate models

| Provider | Model | Decision | Rationale |
|---|---|---|---|
| OpenAI | GPT-5.6 Sol | Not selected | Designed for the most demanding coding and reasoning workloads. Its additional capability and higher cost are not justified for short screening conversations governed by deterministic business rules. |
| OpenAI | GPT-5.6 Terra | Benchmark finalist | A balanced model that may provide stronger instruction following and ambiguity handling than smaller alternatives while remaining suitable for production applications. |
| OpenAI | GPT-5.6 Luna | Benchmark finalist and initial production hypothesis | Optimized for fast, cost-sensitive workloads. It should be sufficient for short multilingual conversations, extraction, and tool calling if validated through evaluations. |
| Anthropic | Claude Opus family | Not selected | Strong reasoning capability, but excessive cost and latency for this narrow, high-volume workflow. |
| Anthropic | Claude Sonnet family | Viable alternative | A strong balanced option, particularly for instruction following and natural dialogue, but it does not add enough initial benchmark diversity to justify testing every provider. |
| Anthropic | Claude Haiku 4.5 | Viable future benchmark | A relevant low-latency alternative. It would be the first Anthropic model evaluated if the initial finalists fail quality or reliability thresholds. |
| Google | Gemini 3.5 Flash | Not selected for the initial benchmark | Its additional capability may be valuable for more complex agentic workflows, but it is not clearly necessary for this bounded collection process. |
| Google | Gemini 3.5 Flash-Lite | Benchmark finalist | Designed for high-throughput and latency-sensitive workloads. It provides a useful cross-provider comparison for multilingual extraction, conversational quality, and cost. |

The initial benchmark therefore compares:

- GPT-5.6 Luna: production-first cost and latency hypothesis.
- GPT-5.6 Terra: higher-capability OpenAI reference.
- Gemini 3.5 Flash-Lite: efficient cross-provider reference.

Anthropic is not considered unsuitable. Claude Haiku 4.5 is the next candidate if the initial benchmark reveals shortcomings or if additional provider diversity is required. Limiting the first experiment to three models keeps the evaluation focused and reproducible.

### Open-weight models

The term “open-weight” is more precise than “open-source” because model licences and permitted uses vary.

#### Self-hosted open-weight models

Self-hosting was not selected for this implementation because it would require:

- GPU infrastructure or an external inference cluster.
- Model serving, scaling, deployment, and version management.
- Monitoring inference latency, memory usage, and availability.
- Security hardening and ongoing operational ownership.
- Additional work to guarantee reliable structured output and tool calling.

Grupo Sazón processes approximately 200 applications per week. At this volume, managed APIs offer a better engineering and operational trade-off. There is also no stated on-premise or strict data-residency requirement that would justify operating dedicated inference infrastructure.

Self-hosting should be reconsidered if the client requires on-premise deployment, strict data localisation, model-level customisation, or sufficiently large sustained volume to justify the operational investment.

#### Hosted open-weight models

Hosted open-weight models run on infrastructure operated by providers such as managed inference platforms. They do not consume the application server's local CPU or GPU.

They are not excluded because of inherently lower quality. They are excluded from the initial benchmark because:

- Model behaviour and service reliability depend on the combination of model and hosting provider.
- Structured-output and tool-calling reliability must be validated separately for each host.
- Provider-specific SLAs, retention policies, observability, and regional availability must also be assessed.
- The expected volume does not currently provide a decisive cost or control advantage.
- Adding more providers would expand the evaluation matrix without answering a materially different question.

A hosted open-weight model would become attractive if it provided a measured cost advantage, better regional deployment, stronger portability, or equivalent extraction reliability under the project evaluation suite.

### Evaluation methodology

Each finalist will run the same simulated conversations, including:

- Spanish and English happy paths.
- Code-switching.
- Multiple fields supplied in one message.
- Ambiguous locations and dates.
- Misspellings and informal language.
- Missing or contradictory answers.
- Candidate questions during screening.
- Prompt-injection and off-topic attempts.
- Repeated abusive language.
- Provider timeouts and malformed structured responses.

The following metrics will be recorded:

- Field-level extraction accuracy.
- Complete-record accuracy.
- Validation and tool-call success rate.
- Incorrect qualification rate.
- Conversation completion rate.
- Average turns to completion.
- P50 and P95 response latency.
- Estimated cost per completed screening.
- Recovery rate after ambiguous input.

Incorrect qualification is a release-blocking failure. Cost and latency will only determine the winner among models that meet the required quality and reliability thresholds.

### Current decision

GPT-5.6 Luna is the initial production hypothesis because this is a bounded, high-volume workflow with deterministic qualification rules. GPT-5.6 Terra and Gemini 3.5 Flash-Lite will be used as comparison points.

The application will access models through a provider adapter so that model selection remains a configuration decision rather than a rewrite. The final production model will be selected from evaluation evidence, not brand preference or benchmark reputation.

### Official references

- [OpenAI model documentation](https://developers.openai.com/api/docs/models)
- [Anthropic model overview](https://platform.claude.com/docs/en/about-claude/models/overview)
- [Anthropic model selection guidance](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)
- [Gemini 3.5 Flash documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash)
- [Gemini 3.5 Flash-Lite documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)
- [ElevenLabs agent prompting guide](https://elevenlabs.io/docs/eleven-agents/best-practices/prompting-guide)
