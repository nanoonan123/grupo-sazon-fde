# Manual Conversation Test Report

## Scope

This report records the focused bilingual conversation review and the follow-up
regression for service-area resolution. It complements the Process Design and the
automated suite.

## Original observations

The first real Spanish run exposed consent/progress and location problems:

- The opening collected a name before explaining duration and language options.
- Common `España / Madrid / Centro` wording did not match the original synthetic
  catalogue representation.
- Location clarification repeated country, city, and zone instead of asking only
  for the missing component.
- Language was incorrectly included in an eight-field progress denominator.

Those issues were corrected by the earlier consent, seven-criterion progress, and
canonical catalogue work. A later English typo regression exposed a narrower
failure:

1. Candidate: `madird city center`.
2. The provider proposed canonical city `Madrid`, but the deterministic catalogue
   did not have `city center` as an exact zone alias.
3. The resolver therefore saved Madrid as partial state and asked for its zone.
4. Candidate: `city center`.
5. The alias was still unknown, and both the initial internal incomplete state and
   the follow-up incremented the clarification counter. At the configured limit of
   two, the conversation incorrectly ended in `needs_review`.

The outcome was conservative—it did not silently accept a location—but the retry
accounting and alias coverage made a valid configured area fail.

## Corrections implemented

- The opening now combines the short invitation and full-name question. A valid
  name is the opt-in action and is stored in the same turn; explicit refusal remains
  stopped/incomplete rather than disqualified.
- Progress remains seven criteria; consent and language are process metadata.
- The catalogue contains explicit Spanish/English aliases and word orders for the
  fictional Madrid/Centro and Mexico City/Central areas, including `city center`,
  `city centre`, `downtown`, `CDMX`, and `centro` forms.
- Raw candidate wording is the evidence for each new location turn. Previously
  validated partial state can complete it, but an LLM-proposed normalized field
  cannot silently turn candidate typo text into an exact match.
- `Madrid` followed by `city center` resolves to `ES / Madrid / Centro`.
- A strong typo such as `madird city center` creates a canonical suggestion and
  requires confirmation. Approximate matches are never automatically accepted.
- Unknown locations require explicit confirmation before the deterministic
  `outside_service_area` outcome.
- The service-area clarification counter starts only after a requested follow-up
  fails. Initial deterministic incomplete/suggestion creation does not consume a
  retry.

## Acceptance examples

| Candidate input | Deterministic result |
| --- | --- |
| `Madrid centro` | Supported; `ES / Madrid / Centro` |
| `madrid city center` | Supported; `ES / Madrid / Centro` |
| `Madrid city centre` | Supported; `ES / Madrid / Centro` |
| `downtown Madrid` | Supported; `ES / Madrid / Centro` |
| `madird city center` | Suggest Madrid/Centro; confirmation required |
| `Madrid`, then `city center` | Combine partial state; supported |
| `madrid` | Incomplete; ask only for zone |
| `España` or `Mexico` | Incomplete; ask for city and zone |
| `CDMX centro` / `downtown Mexico City` | Supported; `MX / Mexico City / Central` |
| Confirmed `Barcelona, Norte` | Deterministic outside-service-area outcome |

## Current demo surfaces

Frontend and analytics are implemented in this slice. The candidate page restores
persisted history and follows the authoritative conversation language without a
manual selector. The compact `/demo` launcher simulates ATS intake. The read-only
`/recruiter` dashboard separates synthetic measured data from the client-supplied
baseline. A development-only technical page shows the latest real LangGraph node
updates without transcript or structured candidate data.

## Verification and remaining limitations

Automated tests cover the aliases, typo confirmation, partial-state merge, unknown
confirmation, retry semantics, combined opt-in/name, language switching, terminal
copy and UI boundaries. Tests use the fake provider and
make no external model calls.

- Service areas remain fictional curated demo data, not researched Grupo Sazón
  operating sites; there is no geocoding or broad fuzzy acceptance.
- Data deletion records a deleted status but does not physically anonymize PII.
- RAG, backend-connected voice, re-engagement, production authentication,
  deployment, and production analytics remain unimplemented.
