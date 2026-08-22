# Grupo Sazón Candidate Screening

Python foundation for a bilingual candidate screening service. The current scope
includes a FastAPI API, Pydantic domain contracts, deterministic eligibility
rules, asynchronous SQLite persistence, simulated ATS intake, synthetic demo
service areas, a transient LangGraph screening workflow, and automated tests.

## Requirements

- Python 3.12 or 3.13

## Local setup

Create and activate a virtual environment, then install the project with its
development dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Run the API:

```powershell
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/health`; it returns `{"status":"ok"}`. Local
interactive API documentation is available at `http://127.0.0.1:8000/docs`,
grouped under **ATS**, **Conversations**, and **Operations**. Production deployments
must protect or disable interactive documentation.

The local database defaults to `data/grupo_sazon.db`. Override `DATABASE_URL` in
`.env` when a different database is required.

Conversation endpoints use these settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | Required only when an actual LLM-backed message is processed |
| `OPENAI_MODEL` | `gpt-5.6-luna` | Responses API model used for interpretation and summaries |
| `OPENAI_TIMEOUT_SECONDS` | `8` | Short timeout applied to each provider attempt |
| `AMBIGUITY_RETRY_LIMIT` | `2` | Clarification attempts before human review |
| `SERVICE_AREAS_PATH` | `data/service_areas.json` | Deterministic service-area configuration |

The application and `/health` start without an OpenAI key. A message that needs
the production provider without a configured key is safely persisted and receives
a retry response; it does not crash the API.

## API endpoints

Create an application and its initial conversation using a unique idempotency
key:

```bash
curl -i -X POST http://127.0.0.1:8000/api/ats/applications \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-event-1001" \
  -d '{
    "external_application_id": "ats-application-1001",
    "phone_number": "+34600000000",
    "source": "demo-ats",
    "preferred_language": "es"
  }'
```

The first request returns HTTP 201. Repeating the same key and payload returns
HTTP 200 with the original result. The `(source, external_application_id)` pair is
also unique: an identical delivery under a new key returns the existing result,
while conflicting candidate data returns HTTP 409.

Retrieve the identifiers returned by intake:

```bash
curl http://127.0.0.1:8000/api/applications/<application_id>
curl http://127.0.0.1:8000/api/conversations/<conversation_id>
```

Start the conversation once, then send candidate messages using the returned
conversation identifier. The initial message explains the roughly three-minute
screening and asks for consent before collecting screening data:

```bash
curl -X POST \
  http://127.0.0.1:8000/api/conversations/<conversation_id>/start

curl -X POST \
  http://127.0.0.1:8000/api/conversations/<conversation_id>/messages \
  -H "Content-Type: application/json" \
  -d '{"text":"Sí, soy Alex Rivera."}'
```

`/start` is idempotent. Declining consent stops the conversation without a
disqualification. Each message response includes the persisted assistant message,
conversation status, deterministic progress, missing fields, and a terminal
outcome when applicable.

Progress covers seven screening criteria: full name, driver's license, service
area, availability, preferred schedule, delivery experience, and start date.
Language and consent are process metadata, not selection criteria. Zero years of
delivery experience is complete without a platform; positive experience requires
at least one platform name.

Configured demo locations use canonical country codes `ES` and `MX`. City and zone
can identify a supported area without asking for country when the pair is unique.
For example, `Madrid Centro`, `España, Madrid centro`, and the labelled equivalent
resolve to canonical `ES / Madrid / Centro`. Partial answers trigger targeted
questions, and close spellings require explicit confirmation before persistence.

Run checks:

```powershell
python -m pytest -q
python -m ruff check .
```

## Current and planned scope

Implemented now: project packaging, environment configuration, health endpoint,
domain models, deterministic rules, asynchronous persistence, idempotent ATS
application intake, resource retrieval, structured OpenAI interpretation, an
explicit LangGraph workflow, deterministic response routing, synthetic data, and
tests. Tests use `FakeScreeningProvider` and never call external APIs.

Planned but not implemented: database migrations and production PostgreSQL
deployment, frontend pages, retrieval-augmented generation (RAG), ElevenLabs
webhook tools, analytics, and deployment automation.

The Phase 1 process specification remains in `docs/PROCESS_DESIGN.docx`. Technical
boundaries and provisional choices are recorded in
`docs/ARCHITECTURE_AND_DECISIONS.md`. The focused Spanish usability diagnosis and
corrections are recorded in `docs/MANUAL_TEST_REPORT.md`.
