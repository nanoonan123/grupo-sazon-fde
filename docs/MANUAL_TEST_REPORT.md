# Manual Conversation Test Report

## Scope

This report records the focused usability review prompted by the latest real
Spanish conversation test. It does not replace the Phase 1 Process Design.

## Observed behavior

The test revealed four concrete problems:

1. The initial assistant message asked for the candidate's name immediately. It
   did not explain the screening purpose, expected duration, language options, or
   ask permission to continue.
2. Both `España, Madrid centro` and
   `País: España. Ciudad: Madrid. Zona: Centro.` were rejected even though
   Madrid/Centro is intended to be a supported fictional demo area.
3. Every location clarification repeated country, city, and zone instead of
   asking only for the unresolved component.
4. Progress showed 7/8 because selected language was counted as a screening
   field. The actual workflow has seven screening criteria.

The eventual `needs_review` result was safe because the system did not silently
accept an unresolved area, but it was avoidable for this valid configured demo
location.

## Exact root cause

| Problem | Root cause before correction |
| --- | --- |
| Madrid/Centro rejected | The JSON catalog stored the zone only as `Zona Centro Demo ES-01`, while `ServiceAreaCatalog.supports` required an exact normalized country/city/zone triple. `Centro` was therefore not equal to the configured value. |
| `España` rejected | Country matching included only `ES` and `Spain`; `España` was not a configured alias. |
| Country always required | Location merging required country, city, and zone to be non-null before attempting validation. It could not infer a country from a unique configured city+zone pair. |
| Common phrasing failed | The resolver compared already separated exact fields and had no deterministic parsing for labels, punctuation, commas, diacritics, or compact forms such as `Madrid centro`. |
| Clarification repeated all fields | Every partial, unknown, or approximate location collapsed into one `service_area` flag. No metadata described whether city, zone, or country was missing. |
| Progress denominator was eight | `language` appeared in required-field evaluation and the API used a hard-coded total of eight. |
| No consent stage | Conversation start selected either the language or full-name stage and immediately asked a screening question. |

## Corrections implemented

- Conversation start now explains purpose and duration, offers Spanish or
  English, and asks for consent. Consent is process metadata and is excluded from
  screening progress. Rejection stops the conversation without disqualification.
- Progress is calculated from seven criteria: full name, driver's license,
  service area, availability, preferred schedule, delivery experience, and start
  date. Delivery experience is complete with zero years, or with years plus at
  least one platform when years are greater than zero.
- The synthetic catalog now uses canonical `ES` and `MX` country codes and
  canonical user-facing city/zone names. Explicit country, city, and zone aliases
  are configured rather than guessed.
- Deterministic resolution ignores case, surrounding whitespace, diacritics, and
  common separators. A unique configured city+zone pair may infer country.
- Country alone remains insufficient. City alone asks only for zone. Country is
  requested only when an otherwise valid city+zone pair is configured in more
  than one country.
- A strong, unique close spelling match becomes a pending suggestion. It is not
  authoritative until the candidate confirms it. Unknown locations are not
  considered outside the service area until the candidate clearly confirms them.
- Clarification metadata now drives one targeted question. The configured retry
  limit still routes unresolved ambiguity to `needs_review`.

## Acceptance examples

| Candidate input | Deterministic result |
| --- | --- |
| `España, Madrid centro` | Supported; persist `ES / Madrid / Centro` |
| `País: España. Ciudad: Madrid. Zona: Centro.` | Supported; persist `ES / Madrid / Centro` |
| `Madrid Centro` | Supported; infer and persist country `ES` |
| `España` | Incomplete; ask for city and zone |
| `Madrid` | Incomplete; ask only for zone |
| `Madird centro` | Suggest `Madrid / Centro`; persist only after confirmation |
| `Barcelona, Norte` | Ask for confirmation; confirmed unknown area is outside |

## Verification

Automated coverage includes consent acceptance, rejection, and consent plus name
in one turn; 0/7 progress and language independence; exact and aliased location
forms; country-only and city-only clarification; spelling confirmation; confirmed
unknown areas; retry-limit review; and all earlier workflow and persistence tests.

## Remaining limitations

- The area list is explicitly fictional demo data and is not a researched Grupo
  Sazón operating-area catalog.
- Alias lists are curated configuration. The resolver deliberately avoids broad
  fuzzy acceptance and geocoding.
- Production schema migrations, frontend, RAG, analytics, voice integrations,
  and deployment remain outside this slice.
