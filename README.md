# Grupo Sazón Candidate Screening

Python foundation for a bilingual candidate screening service. The current scope
includes a FastAPI API, Pydantic domain contracts, deterministic eligibility
rules, asynchronous SQLite persistence, simulated ATS intake, synthetic demo
service areas, and automated tests.

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

Open `http://127.0.0.1:8000/health`; it returns `{"status":"ok"}`.

The local database defaults to `data/grupo_sazon.db`. Override `DATABASE_URL` in
`.env` when a different database is required.

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
HTTP 200 with the original result. Reusing the key with different data returns
HTTP 409.

Retrieve the identifiers returned by intake:

```bash
curl http://127.0.0.1:8000/api/applications/<application_id>
curl http://127.0.0.1:8000/api/conversations/<conversation_id>
```

Run checks:

```powershell
python -m pytest -q
python -m ruff check .
```

## Current and planned scope

Implemented now: project packaging, environment configuration, health endpoint,
domain models, deterministic rules, asynchronous persistence, idempotent ATS
application intake, resource retrieval, synthetic data, and tests.

Planned but not implemented: LLM calls, LangGraph orchestration, database
migrations and production PostgreSQL deployment, frontend pages,
retrieval-augmented generation (RAG), and ElevenLabs voice integration. Dependency
declarations reserve the intended integration path; they do not imply those
components are active.

The Phase 1 process specification remains in `docs/PROCESS_DESIGN.docx`. Technical
boundaries and provisional choices are recorded in
`docs/ARCHITECTURE_AND_DECISIONS.md`.
