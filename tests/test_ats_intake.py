"""Tests for asynchronous ATS intake and persistence endpoints."""

import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

VALID_PAYLOAD = {
    "external_application_id": "ats-application-1001",
    "phone_number": "+34600000000",
    "source": "demo-ats",
    "preferred_language": "es",
}


@pytest.fixture
def api_client(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    """Run the API against a new temporary SQLite database."""

    database_path = tmp_path / "test.db"
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
        _env_file=None,
    )
    with TestClient(create_app(settings)) as client:
        yield client, database_path


def post_application(
    client: TestClient,
    *,
    key: str = "event-1001",
    payload: dict[str, str] | None = None,
):
    """Send one simulated ATS application request."""

    return client.post(
        "/api/ats/applications",
        headers={"Idempotency-Key": key},
        json=payload or VALID_PAYLOAD,
    )


def row_count(database_path: Path, table: str) -> int:
    """Return a table count from the committed test database."""

    with sqlite3.connect(database_path) as connection:
        result = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    assert result is not None
    return int(result[0])


def test_successful_ats_intake(
    api_client: tuple[TestClient, Path],
) -> None:
    client, _ = api_client

    response = post_application(client)

    assert response.status_code == 201
    body = response.json()
    UUID(body["application_id"])
    UUID(body["conversation_id"])
    assert body["status"] == "in_progress"
    assert datetime.fromisoformat(body["created_at"]).utcoffset() is not None


def test_duplicate_delivery_returns_existing_result(
    api_client: tuple[TestClient, Path],
) -> None:
    client, database_path = api_client

    first = post_application(client)
    duplicate = post_application(client)

    assert first.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.json() == first.json()
    assert row_count(database_path, "candidate_applications") == 1
    assert row_count(database_path, "conversations") == 1
    assert row_count(database_path, "inbound_events") == 1


def test_conflicting_idempotency_key_reuse(
    api_client: tuple[TestClient, Path],
) -> None:
    client, database_path = api_client
    post_application(client)
    conflicting_payload = {**VALID_PAYLOAD, "phone_number": "+525500000000"}

    response = post_application(client, payload=conflicting_payload)

    assert response.status_code == 409
    assert row_count(database_path, "candidate_applications") == 1
    assert row_count(database_path, "conversations") == 1
    assert row_count(database_path, "inbound_events") == 1


def test_application_and_conversation_retrieval(
    api_client: tuple[TestClient, Path],
) -> None:
    client, _ = api_client
    created = post_application(client).json()

    application_response = client.get(
        f"/api/applications/{created['application_id']}"
    )
    conversation_response = client.get(
        f"/api/conversations/{created['conversation_id']}"
    )

    assert application_response.status_code == 200
    assert application_response.json() == {
        **created,
        "external_application_id": VALID_PAYLOAD["external_application_id"],
        "phone_number": VALID_PAYLOAD["phone_number"],
        "source": VALID_PAYLOAD["source"],
        "preferred_language": VALID_PAYLOAD["preferred_language"],
        "updated_at": created["created_at"],
    }
    assert conversation_response.status_code == 200
    assert conversation_response.json() == {
        "conversation_id": created["conversation_id"],
        "application_id": created["application_id"],
        "status": "in_progress",
        "created_at": created["created_at"],
        "updated_at": created["created_at"],
    }


@pytest.mark.parametrize(
    "payload",
    [
        {**VALID_PAYLOAD, "phone_number": ""},
        {**VALID_PAYLOAD, "external_application_id": "   "},
        {**VALID_PAYLOAD, "preferred_language": "fr"},
    ],
)
def test_invalid_payload_handling(
    api_client: tuple[TestClient, Path],
    payload: dict[str, str],
) -> None:
    client, database_path = api_client

    response = post_application(client, key="invalid-event", payload=payload)

    assert response.status_code == 422
    assert row_count(database_path, "candidate_applications") == 0
