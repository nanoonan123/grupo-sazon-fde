# ElevenLabs voice-channel configuration

## Same-page voice transport

Set the dashboard **First message** exactly to `{{voice_first_message}}`. Pass the
non-secret dynamic variables `conversation_id`, `voice_first_message`, and
`conversation_language`; use the voice-only widget in the candidate chat dialog.
Configure the authenticated webhook tool against a public HTTPS FastAPI URL. Its
secret header is configured in ElevenLabs, never in browser HTML or JavaScript.

Use this dashboard instruction exactly:

> You are the voice channel for Grupo Sazón’s screening backend. Do not decide screening questions, validation, eligibility or outcomes yourself. After every candidate utterance, call submit_screening_turn exactly once using the verbatim transcript. Wait for the tool result and speak its assistant_message exactly as returned. Do not add, remove, paraphrase or summarize information. If terminal is true, speak the returned message and end the conversation. Always follow the language used in assistant_message.

This adapter uses the official ElevenLabs widget for speech input/output and one
authenticated webhook tool for each candidate answer. ElevenLabs handles speech;
the Grupo Sazón backend remains authoritative for conversation state, transcript
persistence, validation, clarification retries, and deterministic eligibility.

Official references:

- [Widget embedding and dynamic variables](https://elevenlabs.io/docs/eleven-agents/customization/widget)
- [Webhook tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/webhook-tools)
- [System dynamic variables](https://elevenlabs.io/docs/eleven-agents/customization/personalization/dynamic-variables)

## 1. Local environment

Copy `.env.example` to `.env` and set:

```dotenv
ELEVENLABS_AGENT_ID=agent_your_agent_id
ELEVENLABS_TOOL_SECRET=replace-with-a-long-random-secret
```

The secret is server-side only. Never place it in widget markup, browser
JavaScript, a dynamic variable, or the agent prompt.

## 2. Public development URL

ElevenLabs executes webhook tools from its servers and cannot call a localhost
URL. Run the API locally, expose it through ngrok or another HTTPS tunnel, and keep
that tunnel running while testing. For example:

```text
https://your-subdomain.ngrok-free.app
```

Use the resulting HTTPS origin as `<PUBLIC_BASE_URL>` below. Restart the app after
changing `.env` values.

## 3. Agent and widget

1. In ElevenLabs, open **Agents Platform → Agents** and create or select the voice
   agent.
2. Copy its agent ID into `ELEVENLABS_AGENT_ID`.
3. In the agent's **Widget** settings, keep voice enabled.
4. For the direct official widget embed used by this demo, make the agent public
   with widget authentication disabled, as required by the widget documentation.
5. In **Security**, add the local/tunnel origins you will use to the agent allowlist.
6. Ensure Spanish (`es`) and English (`en`) are supported. The page passes the
   authoritative backend language as `conversation_language` and the persisted
   opening as `voice_first_message`.

The application passes these non-secret dynamic variables to the widget:

- `conversation_id`: the backend conversation UUID.
- `voice_first_message`: the persisted assistant opening.
- `conversation_language`: the current authoritative language (`es` or `en`).

## 4. Webhook tool

In the selected agent, go to **Tools → Add tool → Webhook** and configure exactly:

- **Name:** `submit_screening_turn`
- **Method:** `POST`
- **URL:**
  `<PUBLIC_BASE_URL>/api/voice/conversations/{{conversation_id}}/turn`
- **Content type:** `application/json`
- **Description:** `Submit the candidate's exact latest spoken answer to the Grupo Sazón screening backend. Call this once after every candidate answer. The backend owns all state, validation, next-question selection, and eligibility decisions. Speak the returned assistant_message verbatim.`

Add the custom header:

- **Header name:** `X-Voice-Tool-Secret`
- **Header type:** `Secret`
- **Secret value:** exactly the same value as `ELEVENLABS_TOOL_SECRET`

Do not configure this value as an LLM-provided parameter or browser dynamic
variable.

Add two required JSON body parameters:

| Parameter | Type | Value source | Description |
| --- | --- | --- | --- |
| `text` | string | LLM Prompt | `The exact transcript of the candidate's latest answer. Copy it verbatim; do not summarize, translate, correct, or add words.` |
| `external_turn_id` | string | Dynamic/template value | `{{system__conversation_id}}:{{system__agent_turns}}` |

`system__conversation_id` identifies the ElevenLabs conversation and
`system__agent_turns` identifies the current agent turn. Their combination is the
stable provider turn identifier used by the backend to make webhook retries
idempotent. Configure `conversation_id` in the URL from the widget-supplied custom
dynamic variable, not from `system__conversation_id`.

## 5. Agent system prompt

Add these instructions to the agent's system prompt without adding screening
criteria or question logic:

```text
You are the speech interface for Grupo Sazón's candidate screening backend.
The backend, not you, owns conversation state, validation, clarification logic,
question selection, and eligibility decisions.

After every candidate answer:
1. Call submit_screening_turn exactly once.
2. Set text to the exact candidate transcript without summarizing, translating,
   correcting, or adding content.
3. Use the configured external_turn_id template for the current turn.
4. Wait for the tool result.
5. Speak assistant_message from the tool response verbatim. Do not paraphrase it,
   prepend commentary, answer independently, or ask a different question.
6. If terminal is true, speak assistant_message verbatim and do not continue the
   screening.

Never infer qualification, change an outcome, or collect screening answers without
submitting them to the backend tool.
```

The page supplies the backend's persisted opening message as the widget's first
message override. Do not maintain a separate opening question in the agent prompt.

## 6. Test the integration

1. Create a demo application at `/demo`.
2. Select **Continuar por voz**.
3. Allow microphone access and answer the opening question.
4. In ElevenLabs call history, verify one `submit_screening_turn` call per candidate
   answer and confirm its URL contains the backend `conversation_id`.
5. Confirm the response contains only `assistant_message`, `status`, `stage`,
   `terminal`, and `outcome`, and that the agent speaks `assistant_message`
   unchanged.
6. Retry one tool call with the same `external_turn_id`; the backend must replay the
   stored response without adding another candidate message.

This slice does not add telephony, signed widget URLs, scheduling, RAG, deployment,
or production authentication/RBAC.
