# ElevenLabs Voice Configuration

## Current configuration

- Agent: Grupo Sazón Screening — Demo
- Interaction: Browser-based voice
- LLM: Gemini 3.5 Flash-Lite
- Default language: Spanish
- Additional language: English
- Expressive mode: Disabled
- Voice: Eric — Smooth, Trustworthy
- Language detection: Enabled

## Language detection tool description

Switch language only when the candidate explicitly requests a language
change or speaks at least one complete sentence predominantly in another
supported language.

Do not switch because of isolated words such as yes, no, okay, names,
locations, slang, borrowed words, or short expressions.

If the candidate explicitly asks to remain in English or Spanish, keep that
language until they explicitly request another change.

## Initial manual test

- Date: 22 August 2026
- Duration: 4 minutes 18 seconds
- Total credits: 1,435
- LLM cost: approximately $0.034
- Result: Completed

### Successful behaviours

- Collected all required screening fields.
- Preserved conversational context.
- Handled Spanish and English.
- Rejected unrelated requests.
- Did not make the final eligibility decision.
- Recovered from repeated interruptions.

### Issues detected

- Incorrect language switching after short English expressions.
- Interpreted “yesterday” as immediate availability.
- Repeated parts of the final summary.
- Inferred an unconfirmed recruiter contact channel.

### Actions

- Tighten language-detection conditions.
- Require explicit valid start dates.
- Make the final summary atomic and concise.
- Prevent ungrounded claims about recruiter follow-up.