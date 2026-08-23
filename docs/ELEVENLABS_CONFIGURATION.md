# ElevenLabs voice-channel configuration

## Implemented boundary

The candidate page can embed the official ElevenLabs widget when `ELEVENLABS_AGENT_ID` is configured. The backend exposes an authenticated, idempotent voice-turn endpoint:

```text
POST /api/voice/conversations/{conversation_id}/turn
```

It accepts the exact transcript and an `external_turn_id`, requires the `X-Voice-Tool-Secret` header, and uses the same persisted conversation service as web text. The backend returns `assistant_message`, `status`, `stage`, `terminal` and `outcome`. ElevenLabs handles speech only; the backend owns state, validation and eligibility.

## Required configuration

Set local settings in `.env`:

```dotenv
ELEVENLABS_AGENT_ID=agent_your_agent_id
ELEVENLABS_TOOL_SECRET=replace-with-a-long-random-secret
```

The browser receives the agent ID and non-secret dynamic variables `conversation_id`, `voice_first_message` and `conversation_language`. Never expose the tool secret to browser code, widget variables or the agent prompt.

Configure one ElevenLabs webhook tool named `submit_screening_turn`:

| Setting | Value |
| --- | --- |
| Method | `POST` |
| URL | `<PUBLIC_BASE_URL>/api/voice/conversations/{{conversation_id}}/turn` |
| Header | `X-Voice-Tool-Secret: <ELEVENLABS_TOOL_SECRET>` |
| Body | `text` = exact transcript; `external_turn_id` = stable provider turn ID |

The tool description and agent prompt must require exactly one tool call after each candidate answer, then require the agent to speak `assistant_message` verbatim. The agent must not choose questions, validate answers or decide eligibility.

## Current limitation

The browser UI and backend adapter are implemented and tested without external ElevenLabs calls. A standalone agent has been manually checked. End-to-end webhook persistence has not been validated in the submitted local demo: ElevenLabs needs a public HTTPS URL, such as a deployed environment or a temporary HTTPS tunnel. That deployment also needs origin controls, production secret management and normal authentication/authorization decisions.
