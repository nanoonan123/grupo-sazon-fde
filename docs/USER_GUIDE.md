# Grupo Sazón demo: client guide

## What this demo does

It runs a short Spanish/English screening for delivery candidates. The assistant
collects seven job-related fields, preserves partial answers, and applies fixed
eligibility rules. It does not make hiring decisions from an LLM response.

## Run a demonstration

1. Open `/demo` and enter a phone number and preferred language.
2. Select **Crear screening demo**. The candidate chat opens immediately.
3. Reply as the candidate. A full name is required; a first name alone prompts
   for the surname. The chat saves progress after every completed turn.
4. Open `/recruiter` in another tab to review the application, transcript,
   structured data and outcome.

Qualified candidates can choose an available Wednesday/Thursday recruiter-contact
slot. Times show their market: Madrid or Mexico City.

## Outcomes and limits

The outcomes are qualified, disqualified, needs review, stopped, or deleted.
Service areas, identities and metrics are demonstration data. The local demo has
no production authentication, ATS connection, calendar connection, reminders or
public voice webhook. Browser voice is optional when configured; the backend still
owns the persisted conversation and eligibility rules.
