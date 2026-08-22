"""Integration tests for the minimal ElevenLabs voice transport."""

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.models import MessageInterpretation, ScreeningUpdates
from app.agent.provider import FakeScreeningProvider
from app.config import Settings
from app.domain.models import DriverLicense, Language
from app.main import create_app

VOICE_SECRET = "test-voice-tool-secret"


@contextmanager
def voice_client(
    tmp_path: Path,
    interpretations: Sequence[MessageInterpretation] = (),
    *,
    agent_id: str | None = "agent_test_demo",
    tool_secret: str | None = VOICE_SECRET,
) -> Iterator[tuple[TestClient, Path, FakeScreeningProvider]]:
    """Create an isolated network-free app with explicit voice configuration."""

    database_path = tmp_path / "voice.db"
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
        service_areas_path=str(Path("data/service_areas.json").resolve()),
        elevenlabs_agent_id=agent_id,
        elevenlabs_tool_secret=tool_secret,
        _env_file=None,
    )
    provider = FakeScreeningProvider(interpretations)
    with TestClient(create_app(settings, provider)) as client:
        yield client, database_path, provider


def intake(client: TestClient, external_id: str) -> str:
    response = client.post(
        "/api/ats/applications",
        headers={"Idempotency-Key": f"voice-event-{external_id}"},
        json={
            "external_application_id": external_id,
            "phone_number": "+34600123456",
            "source": "linkedin",
            "preferred_language": "es",
        },
    )
    assert response.status_code == 201
    return response.json()["conversation_id"]


def voice_turn(
    client: TestClient,
    conversation_id: str,
    *,
    text: str,
    external_turn_id: str,
    secret: str = VOICE_SECRET,
):
    return client.post(
        f"/api/voice/conversations/{conversation_id}/turn",
        headers={"X-Voice-Tool-Secret": secret},
        json={"text": text, "external_turn_id": external_turn_id},
    )


def name_interpretation() -> MessageInterpretation:
    return MessageInterpretation(
        detected_language=Language.ES,
        consent=None,
        updates=ScreeningUpdates(full_name="Ana Demo"),
    )


def test_voice_and_text_use_the_same_persisted_workflow(tmp_path: Path) -> None:
    with voice_client(
        tmp_path,
        [name_interpretation(), name_interpretation()],
    ) as (client, database_path, provider):
        text_conversation = intake(client, "text-channel")
        voice_conversation = intake(client, "voice-channel")
        client.post(f"/api/conversations/{text_conversation}/start")
        text_response = client.post(
            f"/api/conversations/{text_conversation}/messages",
            json={"text": "Ana Demo"},
        )
        voice_response = voice_turn(
            client,
            voice_conversation,
            text="Ana Demo",
            external_turn_id="eleven-conversation:1",
        )

    assert text_response.status_code == 200
    assert voice_response.status_code == 200
    text_body = text_response.json()
    voice_body = voice_response.json()
    assert voice_body == {
        "assistant_message": text_body["assistant_message"]["content"],
        "status": text_body["conversation_status"],
        "stage": text_body["progress"]["current_stage"],
        "terminal": False,
        "outcome": text_body["outcome"],
    }
    assert provider.interpret_calls == 2
    with sqlite3.connect(database_path) as connection:
        data_rows = connection.execute(
            "SELECT data FROM screening_records ORDER BY created_at"
        ).fetchall()
    assert len(data_rows) == 2
    assert json.loads(data_rows[0][0]) == json.loads(data_rows[1][0])


def test_voice_tool_rejects_invalid_secret(tmp_path: Path) -> None:
    with voice_client(tmp_path) as (client, _, provider):
        conversation_id = intake(client, "invalid-secret")
        response = voice_turn(
            client,
            conversation_id,
            text="Ana Demo",
            external_turn_id="eleven-conversation:1",
            secret="wrong-secret",
        )

    assert response.status_code == 401
    assert provider.interpret_calls == 0


def test_duplicate_external_turn_id_replays_without_duplicate_message(
    tmp_path: Path,
) -> None:
    exact_transcript = "  Ana Demo  "
    with voice_client(tmp_path, [name_interpretation()]) as (
        client,
        database_path,
        provider,
    ):
        conversation_id = intake(client, "idempotent")
        first = voice_turn(
            client,
            conversation_id,
            text=exact_transcript,
            external_turn_id="eleven-conversation:1",
        )
        replay = voice_turn(
            client,
            conversation_id,
            text=exact_transcript,
            external_turn_id="eleven-conversation:1",
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert provider.interpret_calls == 1
    with sqlite3.connect(database_path) as connection:
        messages = connection.execute(
            "SELECT role, content FROM messages ORDER BY sequence_number"
        ).fetchall()
        receipt_count = connection.execute(
            "SELECT COUNT(*) FROM voice_turn_receipts"
        ).fetchone()[0]
    assert len(messages) == 3
    assert messages[1] == ("user", exact_transcript)
    assert receipt_count == 1


def test_voice_turn_returns_terminal_outcome(tmp_path: Path) -> None:
    terminal = MessageInterpretation(
        detected_language=Language.ES,
        consent=True,
        updates=ScreeningUpdates(
            full_name="Ana Demo",
            driver_license=DriverLicense.NO,
        ),
    )
    with voice_client(tmp_path, [terminal]) as (client, _, provider):
        conversation_id = intake(client, "terminal")
        response = voice_turn(
            client,
            conversation_id,
            text="Soy Ana Demo y no tengo permiso de conducir",
            external_turn_id="eleven-conversation:1",
        )

    assert response.status_code == 200
    assert response.json() == {
        "assistant_message": (
            "Gracias por tu tiempo. Este puesto requiere permiso de conducir."
        ),
        "status": "disqualified",
        "stage": "complete",
        "terminal": True,
        "outcome": "disqualified",
    }
    assert provider.interpret_calls == 1
    assert provider.summary_calls == 1


def test_missing_agent_configuration_renders_message_without_crashing(
    tmp_path: Path,
) -> None:
    with voice_client(tmp_path, agent_id=None, tool_secret=None) as (
        client,
        _,
        provider,
    ):
        conversation_id = intake(client, "missing-config")
        response = client.get(f"/voice/{conversation_id}")

    assert response.status_code == 200
    assert "Configuración de desarrollo pendiente" in response.text
    assert "ELEVENLABS_AGENT_ID" in response.text
    assert "<elevenlabs-convai" not in response.text
    assert provider.interpret_calls == 0


def test_voice_page_embeds_official_widget_with_non_secret_variables(
    tmp_path: Path,
) -> None:
    with voice_client(tmp_path) as (client, _, _):
        conversation_id = intake(client, "widget")
        response = client.get(f"/voice/{conversation_id}")

    assert response.status_code == 200
    assert '<elevenlabs-convai' in response.text
    assert 'agent-id="agent_test_demo"' in response.text
    assert f'"conversation_id": "{conversation_id}"' in response.text
    assert '"language": "es"' in response.text
    assert "https://unpkg.com/@elevenlabs/convai-widget-embed" in response.text
    assert VOICE_SECRET not in response.text
