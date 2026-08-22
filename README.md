# Grupo Sazón Candidate Screening

Initial Python foundation for a bilingual candidate screening service. The current
scope includes a FastAPI health endpoint, Pydantic domain contracts, deterministic
eligibility rules, synthetic demo service areas, and automated tests.

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
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/health`; it returns `{"status":"ok"}`.

Run checks:

```powershell
pytest
ruff check .
```

## Current and planned scope

Implemented now: project packaging, environment configuration, health endpoint,
domain models, deterministic rules, synthetic data, and tests.

Planned but not implemented: LLM calls, LangGraph orchestration, database
persistence, frontend pages, retrieval-augmented generation (RAG), and ElevenLabs
voice integration. Dependency declarations reserve the intended integration path;
they do not imply those components are active.

The Phase 1 process specification remains in `docs/PROCESS_DESIGN.docx`. Technical
boundaries and provisional choices are recorded in
`docs/ARCHITECTURE_AND_DECISIONS.md`.
