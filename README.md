# Grupo Sazón Candidate Screening

A bilingual mobile-web screening demo for delivery-driver candidates. It collects
seven job-related fields, preserves partial answers and applies deterministic
eligibility rules before handing qualified candidates to recruiters.

## Setup and run

Requirements: Python 3.12 or 3.13 and an OpenAI API key for LLM-backed
conversation turns.

In Bash, from the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Open `.env` and set `OPENAI_API_KEY` to a valid key. Then start the application:

```bash
python -m uvicorn app.main:app --reload
```

Open these local URLs:

- Demo launcher: <http://127.0.0.1:8000/demo>
- Recruiter panel: <http://127.0.0.1:8000/recruiter>
- API reference: <http://127.0.0.1:8000/docs>

The launcher creates a simulated ATS application and opens its candidate chat
directly. To run checks:

```bash
python -m pytest -q
python -m ruff check .
```

## Architecture overview

FastAPI serves the candidate chat, demo launcher, recruiter panel and API.
Text messages use the persisted conversation service. A voice-turn adapter is available for the same workflow design, while end-to-end ElevenLabs synchronization requires a public HTTPS endpoint.
LangGraph coordinates stages; Pydantic defines the structured contract; the
database is authoritative; and deterministic rules—not the LLM—validate data and
select outcomes. SQLite is used for the local demo.

OpenAI interprets candidate language and proposes structured values. The initial
model choice, `gpt-5.6-luna`, is a hypothesis pending task-specific evaluation.
The optional ElevenLabs browser widget handles speech only: its authenticated
voice-turn adapter sends transcripts to the same backend workflow. End-to-end
voice synchronization needs a public HTTPS endpoint and is not enabled locally.
See [Architecture and Decisions](docs/ARCHITECTURE_AND_DECISIONS.md) for the
technical rationale, integration contract and production scaling design.

## Key design decisions

- **Database authority:** Every turn persists the transcript and current screening state. Terminal outcomes additionally persist the outcome reason, when applicable, and a concise recruiter summary..
- **Deterministic eligibility:** the LLM interprets language but never decides
  whether a candidate qualifies, is disqualified or needs review.
- **Safe conversation recovery:** useful partial answers are retained; targeted
  clarification precedes human review; ambiguity is never guessed.
- **Idempotent integrations:** ATS intake and voice provider turn IDs prevent
  duplicate applications or messages on retries.
- **Demo boundaries:** service areas, identities and metrics are synthetic.
  Browser voice is optional; production authentication, reminders, calendar
  synchronization and deployment are outside this local demo.

## Bonus feature scope

| Feature | Status | Scope note |
| --- | --- | --- |
| RAG | ❌ Not implemented | Approved-content retrieval is a planned improvement. |
| Multi-language | ✅ Implemented | Spanish/English detection, explicit switching and code-switching preserve state. |
| Sentiment analysis | ❌ Not implemented | A warm formal tone shall be mantained in an screening process. |
| Analytics | ✅ Implemented | Recruiter panel shows completion, drop-off, duration, turns and provider metrics. |
| Re-engagement | ❌ Not implemented | The 24h/72h reminder design is documented only. |
| Guardrails | ✅ Implemented | Deterministic eligibility, targeted clarification, abuse handling and deletion/stop paths. |
| ATS integration design | ✅ Defined | Idempotent intake endpoint and retry contract are documented and tested. |
| Tests | ✅ Implemented | Network-free unit and integration scenarios use a fake provider. |
| Deployment design | ✅ Defined | [Stateless scaling, PostgreSQL and operational monitoring](docs/ARCHITECTURE_AND_DECISIONS.md#production-deployment-and-10k-candidatesweek) are documented. |

For voice provider configuration, see
[ElevenLabs configuration](docs/ELEVENLABS_CONFIGURATION.md).

## Potential improvements

| Area | Technical improvement | Operational rationale |
| --- | --- | --- |
| Data platform | Migrate from SQLite to managed PostgreSQL with migrations, backups and connection pooling. | Supports concurrent recruiter and candidate traffic with durable recovery and production operations. |
| Public voice channel | Deploy behind a public HTTPS endpoint with webhook verification and managed secrets. | Lets ElevenLabs submit authoritative turns and keeps browser/voice state synchronized. |
| Recruiter security | Add recruiter login, RBAC, signed candidate links, audit controls and standard web hardening. | Limits personal-data access to authorized staff and supports accountable internal use. |
| Approved-content RAG | Retrieve versioned, recruiter-approved job and company FAQs with grounded answers. | Handles supported policy questions without invented information; retrieval remains outside eligibility decisions. |
| Re-engagement | Add an idempotent background job for 24h and 72h reminders, stopping on response, completion, opt-out or deletion. | Recovers paused conversations without treating silence as disqualification. |
| Interview operations | Integrate booking with a recruiter calendar, confirmations and cancellation handling. | Converts qualified handoff into a managed operational workflow without promising employment. |

Further production scaling, observability and deployment decisions are documented
in [Architecture and Decisions](docs/ARCHITECTURE_AND_DECISIONS.md).
