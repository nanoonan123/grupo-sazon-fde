"""Tests for demo pages and database-backed recruiter read models."""

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agent.models import MessageInterpretation, ScreeningUpdates
from app.agent.provider import FakeScreeningProvider
from app.config import Settings
from app.domain.models import Language
from app.main import create_app


@contextmanager
def web_client(
    tmp_path: Path,
    interpretations: Sequence[MessageInterpretation] = (),
) -> Iterator[tuple[TestClient, Path]]:
    """Create an isolated demo app with a network-free provider."""

    database_path = tmp_path / "web-demo.db"
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
        service_areas_path=str(Path("data/service_areas.json").resolve()),
        openai_api_key="test-secret-that-must-not-appear",
        _env_file=None,
    )
    provider = FakeScreeningProvider(interpretations)
    with TestClient(create_app(settings, provider)) as client:
        yield client, database_path


def intake(
    client: TestClient,
    external_id: str,
    phone: str,
) -> dict[str, str]:
    """Create one isolated simulated ATS application."""

    response = client.post(
        "/api/ats/applications",
        headers={"Idempotency-Key": f"event-{external_id}"},
        json={
            "external_application_id": external_id,
            "phone_number": phone,
            "source": "test-demo-ats",
            "preferred_language": "es",
        },
    )
    assert response.status_code == 201
    return response.json()


def screening_data(
    *,
    name: str | None = None,
    driver_license: str | None = None,
) -> dict[str, object]:
    """Return a complete JSON shape with selected partial candidate values."""

    return {
        "full_name": name,
        "language": "es",
        "driver_license": driver_license,
        "location_raw": None,
        "location_country": None,
        "location_city": None,
        "location_zone": None,
        "availability": [],
        "preferred_schedule": [],
        "delivery_experience_years": None,
        "delivery_platforms": [],
        "start_date_raw": None,
        "start_date": None,
    }


def seed_screening_record(
    database_path: Path,
    application_id: str,
    *,
    record_status: str,
    stage: str,
    data: dict[str, object],
    outcome: str | None,
    created_at: str,
    updated_at: str,
    reason: str | None = None,
    final_summary: str | None = None,
    provider: str | None = "fake",
    model: str | None = "fake-screening",
    latency_ms: int | None = None,
) -> str:
    """Seed authoritative state for deterministic analytics tests."""

    record_id = str(uuid4())
    with sqlite3.connect(database_path) as connection:
        conversation_id = connection.execute(
            "SELECT id FROM conversations WHERE application_id = ?",
            (application_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO screening_records (
                id, application_id, status, stage, data, pending_data,
                clarification_counts, abuse_count, service_area_supported,
                outcome, disqualification_reason, final_summary, llm_provider,
                llm_model, llm_latency_ms, recoverable_error_code,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '{}', '{}', 0, NULL, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                record_id,
                application_id,
                record_status,
                stage,
                json.dumps(data),
                outcome,
                reason,
                final_summary,
                provider,
                model,
                latency_ms,
                created_at,
                updated_at,
            ),
        )
        connection.execute(
            "UPDATE candidate_applications SET status = ?, updated_at = ? WHERE id = ?",
            (record_status, updated_at, application_id),
        )
        connection.execute(
            "UPDATE conversations SET status = ?, updated_at = ? WHERE id = ?",
            (record_status, updated_at, conversation_id),
        )
    return conversation_id


def seed_message(
    database_path: Path,
    conversation_id: str,
    *,
    sequence: int,
    role: str,
    content: str,
    created_at: str,
    latency_ms: int | None = None,
    error_code: str | None = None,
) -> None:
    """Add one ordered persisted message with optional operational metadata."""

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO messages (
                id, conversation_id, sequence_number, role, content,
                message_type, llm_latency_ms, recoverable_error_code, created_at
            ) VALUES (?, ?, ?, ?, ?, 'turn', ?, ?, ?)
            """,
            (
                str(uuid4()),
                conversation_id,
                sequence,
                role,
                content,
                latency_ms,
                error_code,
                created_at,
            ),
        )


def test_candidate_page_loads(tmp_path: Path) -> None:
    with web_client(tmp_path) as (client, _):
        application = intake(client, "candidate-page", "+34610000001")
        response = client.get(f"/screen/{application['conversation_id']}")

    assert response.status_code == 200
    assert "Asistente con IA" in response.text
    assert 'id="booking-panel"' not in response.text
    assert "0/7" in response.text
    assert "candidate.js" in response.text
    assert "language-switch" not in response.text
    assert "interface-note" not in response.text
    assert "you can also reply in English" in response.text
    assert "también puedes responder en español" in response.text


def test_candidate_page_renders_persisted_history_after_refresh(
    tmp_path: Path,
) -> None:
    interpretation = MessageInterpretation(
        detected_language=Language.ES,
        consent=True,
        updates=ScreeningUpdates(full_name="Ana Demo"),
    )
    with web_client(tmp_path, [interpretation]) as (client, _):
        application = intake(client, "candidate-history", "+34610000002")
        conversation_id = application["conversation_id"]
        client.post(f"/api/conversations/{conversation_id}/start")
        client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"text": "Sí, soy Ana Demo"},
        )
        refreshed = client.get(f"/screen/{conversation_id}")

    assert refreshed.status_code == 200
    assert "Sí, soy Ana Demo" in refreshed.text
    assert "Gracias, Ana" in refreshed.text
    assert "1/7" in refreshed.text


def test_candidate_html_exposes_no_secret_prompt_or_internal_metadata(
    tmp_path: Path,
) -> None:
    with web_client(tmp_path) as (client, _):
        application = intake(client, "candidate-safe", "+34610000003")
        client.post(
            f"/api/conversations/{application['conversation_id']}/start"
        )
        response = client.get(f"/screen/{application['conversation_id']}")

    assert "test-secret-that-must-not-appear" not in response.text
    assert "INTERPRETATION_INSTRUCTIONS" not in response.text
    assert "no_driver_license" not in response.text


def test_demo_launcher_creates_application_and_candidate_link(
    tmp_path: Path,
) -> None:
    with web_client(tmp_path) as (client, database_path):
        response = client.post(
            "/demo",
            data={
                "external_application_id": "launcher-application",
                "phone_number": "+34610000004",
                "source": "launcher-demo",
                "preferred_language": "es",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].startswith("http://testserver/screen/")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM candidate_applications"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM inbound_events"
        ).fetchone()[0] == 1


def test_demo_launcher_uses_recruiting_defaults_without_advanced_controls(
    tmp_path: Path,
) -> None:
    with web_client(tmp_path) as (client, _):
        response = client.get("/demo")

    assert response.status_code == 200
    assert "LI-GS-DEMO-0001" in response.text
    assert "+34600123456" in response.text
    assert 'name="external_application_id"' in response.text
    assert '<option value="linkedin" selected>LinkedIn</option>' in response.text
    assert "País del teléfono" in response.text
    assert "Configuración avanzada de demo" not in response.text
    assert "Pista para el mensaje inicial" not in response.text


def test_recruiter_list_filters_and_search(tmp_path: Path) -> None:
    with web_client(tmp_path) as (client, database_path):
        ana = intake(client, "ATS-ANA-100", "+34611110000")
        bob = intake(client, "ATS-BOB-200", "+525511110000")
        seed_screening_record(
            database_path,
            ana["application_id"],
            record_status="qualified",
            stage="complete",
            data=screening_data(name="Ana Pérez", driver_license="yes"),
            outcome="qualified",
            created_at="2026-08-22 10:00:00.000000",
            updated_at="2026-08-22 10:02:00.000000",
        )
        seed_screening_record(
            database_path,
            bob["application_id"],
            record_status="incomplete",
            stage="complete",
            data=screening_data(name="Bob Demo"),
            outcome="incomplete",
            created_at="2026-08-22 09:00:00.000000",
            updated_at="2026-08-22 09:01:00.000000",
        )

        qualified = client.get(
            "/api/recruiter/applications",
            params={"status": "qualified"},
        ).json()
        stopped = client.get(
            "/api/recruiter/applications",
            params={"outcome": "stopped"},
        ).json()
        by_name = client.get(
            "/api/recruiter/applications",
            params={"search": "ana pé"},
        ).json()
        by_external_id = client.get(
            "/api/recruiter/applications",
            params={"search": "BOB-200"},
        ).json()
        by_phone = client.get(
            "/api/recruiter/applications",
            params={"search": "+3461111"},
        ).json()

    assert qualified["total"] == 1
    assert qualified["items"][0]["name"] == "Ana Pérez"
    assert stopped["total"] == 1
    assert stopped["items"][0]["outcome"] == "stopped"
    assert by_name["items"][0]["application_id"] == ana["application_id"]
    assert by_external_id["items"][0]["application_id"] == bob["application_id"]
    assert by_phone["items"][0]["application_id"] == ana["application_id"]


def test_empty_recruiter_metrics_return_zeros(tmp_path: Path) -> None:
    with web_client(tmp_path) as (client, _):
        response = client.get("/api/recruiter/metrics")

    assert response.status_code == 200
    assert response.json() == {
        "total_applications": 0,
        "screening_started": 0,
        "screening_completed": 0,
        "qualified": 0,
        "disqualified": 0,
        "needs_review": 0,
        "stopped": 0,
        "deleted": 0,
        "completion_rate": 0,
        "qualification_rate": 0,
        "interview_booking_rate": 0,
        "drop_off_by_current_stage": {},
        "average_completed_screening_duration_seconds": 0,
        "average_conversation_turns": 0,
        "llm_recoverable_error_count": 0,
        "p50_provider_latency_ms": 0,
    }


def test_metrics_use_persisted_outcomes_stages_turns_and_latency(
    tmp_path: Path,
) -> None:
    with web_client(tmp_path) as (client, database_path):
        applications = [
            intake(client, f"metrics-{index}", f"+3462000000{index}")
            for index in range(4)
        ]
        qualified_conversation = seed_screening_record(
            database_path,
            applications[0]["application_id"],
            record_status="qualified",
            stage="complete",
            data=screening_data(name="Qualified Demo", driver_license="yes"),
            outcome="qualified",
            created_at="2026-08-22 10:00:00.000000",
            updated_at="2026-08-22 10:02:00.000000",
            final_summary="Qualified persisted summary.",
            latency_ms=300,
        )
        disqualified_conversation = seed_screening_record(
            database_path,
            applications[1]["application_id"],
            record_status="disqualified",
            stage="complete",
            data=screening_data(name="Disqualified Demo", driver_license="no"),
            outcome="disqualified",
            reason="no_driver_license",
            created_at="2026-08-22 11:00:00.000000",
            updated_at="2026-08-22 11:01:00.000000",
        )
        stopped_conversation = seed_screening_record(
            database_path,
            applications[2]["application_id"],
            record_status="incomplete",
            stage="complete",
            data=screening_data(name="Stopped Demo"),
            outcome="incomplete",
            created_at="2026-08-22 12:00:00.000000",
            updated_at="2026-08-22 12:00:30.000000",
        )
        seed_screening_record(
            database_path,
            applications[3]["application_id"],
            record_status="in_progress",
            stage="service_area",
            data=screening_data(name="Active Demo", driver_license="yes"),
            outcome=None,
            created_at="2026-08-22 13:00:00.000000",
            updated_at="2026-08-22 13:00:30.000000",
        )
        seed_message(
            database_path,
            qualified_conversation,
            sequence=0,
            role="assistant",
            content="Initial",
            created_at="2026-08-22 10:00:00.000000",
        )
        seed_message(
            database_path,
            qualified_conversation,
            sequence=1,
            role="user",
            content="First answer",
            created_at="2026-08-22 10:00:30.000000",
        )
        seed_message(
            database_path,
            qualified_conversation,
            sequence=2,
            role="assistant",
            content="Second question",
            created_at="2026-08-22 10:01:00.000000",
            latency_ms=100,
        )
        seed_message(
            database_path,
            qualified_conversation,
            sequence=3,
            role="user",
            content="Second answer",
            created_at="2026-08-22 10:01:30.000000",
        )
        seed_message(
            database_path,
            qualified_conversation,
            sequence=4,
            role="assistant",
            content="Complete",
            created_at="2026-08-22 10:02:00.000000",
            latency_ms=300,
            error_code="llm_timeout",
        )
        seed_message(
            database_path,
            disqualified_conversation,
            sequence=0,
            role="user",
            content="No license",
            created_at="2026-08-22 11:00:30.000000",
        )
        seed_message(
            database_path,
            stopped_conversation,
            sequence=0,
            role="user",
            content="Stop",
            created_at="2026-08-22 12:00:20.000000",
        )
        metrics = client.get("/api/recruiter/metrics").json()

    assert metrics["total_applications"] == 4
    assert metrics["screening_started"] == 4
    assert metrics["screening_completed"] == 2
    assert metrics["qualified"] == 1
    assert metrics["disqualified"] == 1
    assert metrics["stopped"] == 1
    assert metrics["completion_rate"] == 0.5
    assert metrics["qualification_rate"] == 0.5
    assert metrics["drop_off_by_current_stage"] == {
        "driver_license": 1,
        "service_area": 1,
    }
    assert metrics["average_completed_screening_duration_seconds"] == 90
    assert metrics["average_conversation_turns"] == 1
    assert metrics["llm_recoverable_error_count"] == 1
    assert metrics["p50_provider_latency_ms"] == 200


def test_recruiter_detail_contains_structured_data_and_ordered_transcript(
    tmp_path: Path,
) -> None:
    with web_client(tmp_path) as (client, database_path):
        application = intake(client, "detail-application", "+34630000000")
        conversation_id = seed_screening_record(
            database_path,
            application["application_id"],
            record_status="disqualified",
            stage="complete",
            data=screening_data(name="Detail Demo", driver_license="no"),
            outcome="disqualified",
            reason="no_driver_license",
            final_summary="Persisted final summary.",
            created_at="2026-08-22 15:00:00.000000",
            updated_at="2026-08-22 15:01:00.000000",
            latency_ms=125,
        )
        seed_message(
            database_path,
            conversation_id,
            sequence=1,
            role="user",
            content="No tengo permiso",
            created_at="2026-08-22 15:00:30.000000",
        )
        seed_message(
            database_path,
            conversation_id,
            sequence=2,
            role="assistant",
            content="Gracias por tu tiempo.",
            created_at="2026-08-22 15:01:00.000000",
            latency_ms=125,
        )
        response = client.get(
            f"/api/recruiter/applications/{application['application_id']}"
        )

    assert response.status_code == 200
    detail = response.json()
    assert detail["screening_data"]["full_name"] == "Detail Demo"
    assert detail["deterministic_reason"] == "no_driver_license"
    assert detail["candidate_summary"] == "Gracias por tu tiempo."
    assert detail["final_summary"] == "Persisted final summary."
    assert [message["role"] for message in detail["transcript"]] == [
        "user",
        "assistant",
    ]
    assert detail["provider"]["model"] == "fake-screening"
    assert detail["provider"]["p50_latency_ms"] == 125


def test_recruiter_dashboard_loads_and_labels_baseline_separately(
    tmp_path: Path,
) -> None:
    with web_client(tmp_path) as (client, _):
        response = client.get("/recruiter")

    assert response.status_code == 200
    assert "Línea base declarada · no medida por esta demo" in response.text
    assert "Datos medidos" in response.text
    assert "60%" in response.text
    assert "ROI" not in response.text
    assert response.text.count('class="kpi-card') == 6
    assert "Salud operativa" in response.text
    assert "Grupo Sazón · Internal HR" in response.text
    assert "Panel interno de selección" in response.text
    assert "Uso exclusivo del equipo de RRHH de Grupo Sazón" in response.text
