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
In production, `ELEVENLABS_TOOL_SECRET` and `ELEVENLABS_AGENT_ID` will also be needed.

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

Python FastAPI serves the candidate chat, demo launcher, recruiter panel and API.
Text screening is fully implemented. The browser voice adapter follows the same
workflow design; authoritative end-to-end ElevenLabs synchronization requires a
public HTTPS endpoint and is not currently enabled locally.
LangGraph coordinates stages; Pydantic validated the structured data; the
database is authoritative; and deterministic rules (not the LLM) validate data and
select outcomes. SQLite is used for the local demo. PostgreSQL is recommended in PROD.

OpenAI interprets candidate language and proposes structured values. The initial
model choice is `gpt-5.6-luna`.

See [Architecture and Decisions](docs/ARCHITECTURE_AND_DECISIONS.md) for the full
technical rationale, integration rules and production scaling design.

## Key design decisions

- **Database authority:** Every turn persists the transcript and current screening state. Terminal outcomes additionally persist the outcome reason, when applicable, and a concise recruiter summary.
- **Deterministic eligibility:** the LLM interprets language but never decides
  whether a candidate qualifies.
- **Safe conversation recovery:** useful partial answers are retained; targeted
  clarification precedes human review; ambiguity is never guessed.
- **Idempotent integrations:** ATS intake and voice provider turn IDs prevent
  duplicate applications or messages on retries.
- **Demo boundaries:** service areas, identities and metrics are synthetic.
  Browser voice is optional; production authentication, reminders, calendar
  synchronization and deployment are outside this local demo.

### LLM choice and evaluation plan

`OPENAI_MODEL=gpt-5.6-luna` is the current cost/latency hypothesis for short
bilingual structured extraction, not a proven production winner. This was decided based on the official documentation. It is recommended to run a comparable benchmark.

The first round should be deliberately limited to four complementary finalists:

| Provider | Model | Evaluation position | Why it is included |
| --- | --- | --- | --- |
| OpenAI | GPT-5.6 Luna | Finalist: current hypothesis | Tests the configured OpenAI path for cost-sensitive bilingual extraction. |
| OpenAI | GPT-5.6 Terra | Finalist: higher-capability reference | Tests whether additional instruction following or ambiguity handling materially changes the result. |
| Google | Gemini 3.5 Flash-Lite | Finalist: efficient cross-provider reference | Google's stable, fastest and most cost-effective 3.5 model is a relevant high-throughput baseline for bounded multilingual extraction. Gemini 3.7 Flash is newer and more capable, but is positioned primarily for complex coding and agentic workflows rather than this deliberately narrow task. |
| Anthropic | Claude Sonnet 5 | Finalist: primary Anthropic reference | Tests Anthropic's current Sonnet balance of speed and intelligence against the same extraction and ambiguity scenarios. |
| Anthropic | Claude Haiku 4.5 | Optional cost/latency baseline | Tests whether Anthropic's faster, lower-cost model already meets the required quality threshold. |

This is not a provider selection. Two OpenAI models test the already integrated
provider at different capability levels, while Gemini and Claude Sonnet provide
focused external comparisons. 
GPT-5.6 Sol is excluded because its additional coding/reasoning capability is not
justified for this bounded, deterministic workflow.

The initial candidates are from current model generations as an initial quality
filter, not because newer automatically means better. Earlier options such as
GPT-5.4 are not in the first matrix because they add another comparison without a
specific expected advantage; they can be evaluated if evidence identifies a
quality, cost or reliability reason to do so.

Open-weight/self-hosted models are not rejected for quality. They are deferred
because the current volume does not justify GPU serving, model deployment and
operations, or separate structured-output and tool-reliability validation. Hosted
open-weight options add a model-and-provider stack without a measured cost or
control advantage.

Only Luna is configured locally today; the other finalists are evaluation
candidates. The provider adapter keeps a later production choice from requiring a
workflow rewrite.
See the [OpenAI model catalogue](https://developers.openai.com/api/docs/models),
the [Gemini model catalogue](https://ai.google.dev/gemini-api/docs/models),
the [Claude model catalogue](https://platform.claude.com/docs/en/models/overview),
and [LLM Model Selection](docs/ARCHITECTURE_AND_DECISIONS.md#llm-model-selection)
for detailed rationale.

## Bonus feature scope

| Feature | Status | Scope note |
| --- | --- | --- |
| RAG | ❌ Not implemented | Approved-content retrieval is a planned improvement. |
| Multi-language | ✅ Implemented | Spanish/English detection, explicit switching and code-switching preserve state. |
| Sentiment analysis | ❌ Not implemented | A warm formal tone shall be mantained in an screening process. |
| Analytics | ✅ Implemented | Recruiter panel shows completion, drop-off, duration, turns and provider metrics. |
| Re-engagement | ❌ Not implemented | The 24h/72h reminder design is documented only. |
| Guardrails | ✅ Implemented | Deterministic eligibility, targeted clarification, respectful stop handling and repeated-abuse control. Deletion requests are recorded; physical deletion is deferred. |
| ATS integration design | ✅ Defined | Idempotent intake endpoint and retry contract are documented and tested. |
| Tests | ✅ Implemented | Network-free unit and integration scenarios use a fake provider. |
| Deployment design | ✅ Defined | [Stateless scaling, PostgreSQL and operational monitoring](docs/ARCHITECTURE_AND_DECISIONS.md#production-deployment-and-10k-candidatesweek) are documented. |

For voice provider configuration, see
[ElevenLabs configuration](docs/ELEVENLABS_CONFIGURATION.md).

## Potential improvements

| Area | Technical improvement | Operational rationale |
| --- | --- | --- |
| Interview operations | Integrate booking with a recruiter Google calendar or similar, confirmations and cancellation handling. | Converts qualified handoff into a managed operational workflow. |
| Humanized assistant identity | Not currently implemented. Test a friendly human-style identity such as “María”, with an avatar, while retaining clear AI disclosure. | This is a UX/product hypothesis for trust, engagement and completion—not a proven improvement. Validate it through A/B tests measuring completion rate and drop-off before considering it successful. |
| WhatsApp transport | Not currently implemented. Add WhatsApp as another channel through Twilio or another WhatsApp Business provider, reusing `ConversationService`, `ScreeningRecord`, the LangGraph workflow and deterministic eligibility rules. Handle webhook intake, provider message IDs, idempotency and bounded retries. | Extends candidate reach without creating a separate screening workflow or duplicating business logic. |
| Model evaluation | Run the same multilingual scenario suite against GPT-5.6 Luna, GPT-5.6 Terra, Gemini 3.5 Flash-Lite and Claude Sonnet 5, optionally adding Claude Haiku 4.5 as a cost/latency baseline. Measure extraction accuracy, ambiguity handling, false qualification risk, latency and cost before selecting a production model. | Select the least expensive model that meets quality and reliability thresholds; an incorrect qualification is release-blocking. |
| Data platform | Migrate from SQLite to managed PostgreSQL with migrations, backups and connection pooling. | Supports concurrent recruiter and candidate traffic with durable recovery and production operations. |
| Public voice channel | Deploy behind a public HTTPS endpoint with webhook verification and managed secrets. | Lets ElevenLabs submit authoritative turns and keeps browser/voice state synchronized. |
| Recruiter security | Add recruiter login, and any internal security procedure of the company. | Limits personal-data access to authorized staff and supports accountable internal use. |
| RAG | Retrieve versioned, recruiter-approved job and company FAQs with grounded answers. | Handles supported policy questions without invented information; retrieval remains outside eligibility decisions. |
| Re-engagement | Add an idempotent background job for 24h and 72h reminders, stopping on response, completion, opt-out or deletion. | Recovers paused conversations without treating silence as disqualification. |
