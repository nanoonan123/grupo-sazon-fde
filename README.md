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
grouped under **ATS**, **Conversations**, **Recruiter**, **Developer**, and
**Operations**. Production deployments must protect or disable interactive
documentation.

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
conversation identifier. The roughly three-minute invitation asks for the full
name as the opt-in action. A valid bare name or affirmative name response grants
continuation consent and stores the name in the same turn:

```bash
curl -X POST \
  http://127.0.0.1:8000/api/conversations/<conversation_id>/start

curl -X POST \
  http://127.0.0.1:8000/api/conversations/<conversation_id>/messages \
  -H "Content-Type: application/json" \
  -d '{"text":"Sí, soy Alex Rivera."}'
```

`/start` is idempotent. Explicit refusal stops the conversation without a
disqualification. Each message response includes the persisted assistant message,
selected conversation language, deterministic progress, missing fields, and a
terminal outcome when applicable.

Progress covers seven screening criteria: full name, driver's license, service
area, availability, preferred schedule, delivery experience, and start date.
Language and consent are process metadata, not selection criteria. Zero years of
delivery experience is complete without a platform; positive experience requires
at least one platform name.

Configured demo locations use canonical country codes `ES` and `MX`. City and zone
can identify a supported area without asking for country when the pair is unique.
For example, `Madrid Centro`, `madrid city center`, `Madrid city centre`,
`downtown Madrid`, and `España, Madrid centro` resolve to canonical
`ES / Madrid / Centro`. `CDMX centro` and `downtown Mexico City` resolve to the
configured Mexico demo area. Partial answers combine with validated location state;
close spellings require explicit confirmation before persistence. Spain or Mexico
alone never constitutes a supported service area.

## Demo web surfaces

With the API running, open:

- Candidate mobile chat: `http://127.0.0.1:8000/screen/<conversation_id>`
- Candidate voice page: `http://127.0.0.1:8000/voice/<conversation_id>`
- Simulated ATS launcher: `http://127.0.0.1:8000/demo`
- Recruiter operations dashboard: `http://127.0.0.1:8000/recruiter`
- Optional post-turn technical trace:
  `http://127.0.0.1:8000/debug/conversations/<conversation_id>`
- Developer API documentation: `http://127.0.0.1:8000/docs`

Suggested demo walkthrough:

1. Open `/demo`, review the pre-filled ATS fields, and create a demo application.
2. Copy or open the candidate screening link returned by the launcher.
3. Enter a full name to opt in, then answer the remaining screening criteria.
4. Refresh the candidate page to verify that the complete transcript is restored.
5. Open the technical trace to see the real LangGraph nodes after each completed
   turn; the development page polls for a newer completed turn and refreshes.
6. Open `/recruiter` to review measured demo KPIs, filters, candidate details,
   structured fields, transcript, and provider operations metadata.

The launcher is explicitly a simulated ATS delivery, not a recruiter workflow.
The dashboard separates metrics calculated from persisted synthetic records from
the client-stated baseline of approximately 200 weekly applications, 60% missed
phone contact, and 80% recruiter time spent on unqualified candidates. The demo
does not claim ROI or business improvement.

The optional trace uses actual LangGraph `updates` stream events. It shows the
static graph, latest executed nodes, route, stage, status, provider/model, latency,
and recoverable error code. It excludes candidate messages, phone/name, structured
screening data, prompts, and model explanations. This is a post-turn trace—not a
live stream—and its routes are omitted when `APP_ENVIRONMENT=production`.
The development page uses lightweight polling only to notice a newly completed
turn; it does not stream in-progress model or graph activity.

### Demo security limitations

The pages are intentionally unauthenticated for local evaluation. Production
requires recruiter authentication and role-based access control, signed expiring
candidate links, webhook signatures or scoped ATS credentials, protected or
disabled Swagger access, transport security, and normal web hardening. None of
those controls should be inferred from the local demo.

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
tests. The current slice also includes server-rendered candidate, ATS-demo, and
recruiter surfaces, read-only database-backed analytics, and a development-only
privacy-safe LangGraph trace. Tests use
`FakeScreeningProvider` and never call external APIs.

Planned but not implemented: database migrations and production PostgreSQL
deployment, production authentication, signed candidate links, retrieval-augmented
generation (RAG), re-engagement scheduling, telephony, and deployment automation.

The minimal ElevenLabs widget and webhook-tool adapter is configured using
[`docs/ELEVENLABS_CONFIGURATION.md`](docs/ELEVENLABS_CONFIGURATION.md). It delegates
every transcript to the same database-backed conversation service used by text.

The Phase 1 process specification remains in `docs/PROCESS_DESIGN.docx`. Technical
boundaries and provisional choices are recorded in
`docs/ARCHITECTURE_AND_DECISIONS.md`. The focused Spanish usability diagnosis and
corrections are recorded in `docs/MANUAL_TEST_REPORT.md`.
