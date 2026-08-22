"""Integration tests for the transient graph and authoritative persistence."""

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent.models import (
    CandidateIntent,
    MessageInterpretation,
    ScreeningUpdates,
    SummaryOutput,
)
from app.agent.provider import FakeScreeningProvider, ProviderUnavailableError
from app.config import Settings
from app.domain.models import Availability, DriverLicense, Language, Schedule
from app.main import create_app


def interpretation(
    *,
    language: Language = Language.ES,
    explicit_switch: Language | None = None,
    consent: bool | None = True,
    ambiguous: bool = False,
    clarification_fields: list[str] | None = None,
    intent: CandidateIntent = CandidateIntent.SCREENING_ANSWER,
    abusive: bool = False,
    outside_confirmed: bool = False,
    location_confirmation: bool | None = None,
    availability_confirmation_required: bool = False,
    relative_date: bool = False,
    date_confirmed: bool = False,
    explanation: str = "Test extraction.",
    **updates: object,
) -> MessageInterpretation:
    """Build one scripted structured interpretation."""

    return MessageInterpretation(
        updates=ScreeningUpdates.model_validate(updates),
        detected_language=language,
        explicit_language_switch=explicit_switch,
        consent=consent,
        ambiguous=ambiguous,
        clarification_fields=clarification_fields or [],
        intent=intent,
        abusive_language=abusive,
        confirmed_outside_service_area=outside_confirmed,
        location_suggestion_confirmed=location_confirmation,
        availability_full_time_confirmation_required=(
            availability_confirmation_required
        ),
        start_date_is_relative=relative_date,
        start_date_confirmed=date_confirmed,
        debug_explanation=explanation,
    )


def complete_updates(
    *,
    start_date: date,
    years: float = 2,
    country: str = "Spain",
    city: str = "Madrid",
    zone: str = "Zona Centro Demo ES-01",
) -> dict[str, object]:
    """Return a complete valid set of proposed screening fields."""

    return {
        "full_name": "Alex Rivera",
        "driver_license": DriverLicense.YES,
        "location_raw": f"{city}, {zone}",
        "location_country": country,
        "location_city": city,
        "location_zone": zone,
        "availability": [Availability.FULL_TIME, Availability.WEEKENDS],
        "preferred_schedule": [Schedule.MORNING, Schedule.FLEXIBLE],
        "delivery_experience_years": years,
        "delivery_platforms": [] if years == 0 else ["Demo Delivery"],
        "start_date_raw": start_date.isoformat(),
        "start_date": start_date,
    }


@contextmanager
def screening_client(
    tmp_path: Path,
    interpretations: Sequence[MessageInterpretation | Exception],
    *,
    preferred_language: Language | None = Language.ES,
    summaries: Sequence[SummaryOutput | Exception] = (),
    retry_limit: int = 2,
) -> Iterator[tuple[TestClient, Path, str, FakeScreeningProvider]]:
    """Create an isolated API and candidate application using the fake provider."""

    database_path = tmp_path / "screening.db"
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
        service_areas_path=str(Path("data/service_areas.json").resolve()),
        ambiguity_retry_limit=retry_limit,
        _env_file=None,
    )
    provider = FakeScreeningProvider(interpretations, summaries)
    with TestClient(create_app(settings, provider)) as client:
        payload: dict[str, str] = {
            "external_application_id": "conversation-application-1",
            "phone_number": "+34600000000",
            "source": "test-ats",
        }
        if preferred_language is not None:
            payload["preferred_language"] = preferred_language.value
        intake = client.post(
            "/api/ats/applications",
            headers={"Idempotency-Key": "conversation-event-1"},
            json=payload,
        )
        assert intake.status_code == 201
        yield client, database_path, intake.json()["conversation_id"], provider


def start(client: TestClient, conversation_id: str):
    """Start one prepared conversation."""

    return client.post(f"/api/conversations/{conversation_id}/start")


def send(client: TestClient, conversation_id: str, text: str):
    """Send one candidate turn."""

    return client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"text": text},
    )


def database_row(database_path: Path, query: str) -> sqlite3.Row:
    """Return one persistence row with named columns."""

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(query).fetchone()
    assert row is not None
    return row


def screening_row(database_path: Path) -> sqlite3.Row:
    """Return the authoritative screening row."""

    return database_row(database_path, "SELECT * FROM screening_records")


def future_date() -> date:
    """Return a stable valid future date for the current test run."""

    return datetime.now(UTC).date() + timedelta(days=30)


def test_conversation_start_is_idempotent(tmp_path: Path) -> None:
    with screening_client(tmp_path, []) as (
        client,
        database_path,
        conversation_id,
        provider,
    ):
        first = start(client, conversation_id)
        replay = start(client, conversation_id)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert provider.interpret_calls == 0
    messages = database_row(database_path, "SELECT COUNT(*) AS count FROM messages")
    records = database_row(
        database_path,
        "SELECT COUNT(*) AS count FROM screening_records",
    )
    assert messages["count"] == 1
    assert records["count"] == 1


def test_start_explains_process_and_progress_begins_at_zero(tmp_path: Path) -> None:
    expected = (
        "Hola 👋 Hemos recibido tu candidatura para el puesto de repartidor/a "
        "en Grupo Sazón. El screening dura unos 3 minutos. Para continuar, "
        "¿cuál es tu nombre completo?"
    )
    with screening_client(tmp_path, []) as (client, _, conversation_id, _):
        response = start(client, conversation_id)

    body = response.json()
    assert body["assistant_message"]["content"] == expected
    assert body["progress"] == {
        "current_stage": "full_name",
        "collected_fields": 0,
        "total_fields": 7,
    }
    assert len(body["missing_fields"]) == 7


def test_consent_acceptance_advances_to_full_name(tmp_path: Path) -> None:
    accepted = interpretation(consent=True)
    with screening_client(tmp_path, [accepted]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "Sí")
        pending = json.loads(screening_row(database_path)["pending_data"])

    assert response.json()["progress"] == {
        "current_stage": "full_name",
        "collected_fields": 0,
        "total_fields": 7,
    }
    assert pending["consent_granted"] is True


def test_bare_name_grants_opt_in_and_is_stored_in_same_turn(
    tmp_path: Path,
) -> None:
    name = interpretation(consent=None, full_name="Michael Jackson")
    with screening_client(tmp_path, [name]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "Michael Jackson")
        record = screening_row(database_path)
        data = json.loads(record["data"])
        pending = json.loads(record["pending_data"])

    assert data["full_name"] == "Michael Jackson"
    assert pending["consent_granted"] is True
    assert response.json()["progress"]["collected_fields"] == 1
    assert response.json()["progress"]["current_stage"] == "driver_license"


def test_affirmative_name_grants_opt_in_and_is_stored(
    tmp_path: Path,
) -> None:
    name = interpretation(consent=True, full_name="María Jackson")
    with screening_client(tmp_path, [name]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        send(client, conversation_id, "Sí, soy María Jackson")
        record = screening_row(database_path)

    assert json.loads(record["data"])["full_name"] == "María Jackson"
    assert json.loads(record["pending_data"])["consent_granted"] is True


def test_consent_rejection_stops_without_disqualification(tmp_path: Path) -> None:
    rejected = interpretation(consent=False)
    with screening_client(tmp_path, [rejected]) as (
        client,
        _,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "No, gracias")

    assert response.json()["conversation_status"] == "incomplete"
    assert response.json()["outcome"] == "incomplete"
    assert response.json()["disqualification_reason"] is None


def test_consent_and_name_in_one_turn_are_both_retained(tmp_path: Path) -> None:
    accepted_with_name = interpretation(consent=True, full_name="Pepe Canals")
    with screening_client(tmp_path, [accepted_with_name]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "Sí, soy Pepe Canals")
        data = json.loads(screening_row(database_path)["data"])

    assert data["full_name"] == "Pepe Canals"
    assert response.json()["progress"]["collected_fields"] == 1
    assert response.json()["assistant_message"]["content"] == (
        "Gracias, Pepe. ¿Tienes un permiso de conducir vigente?"
    )


def test_language_switch_does_not_change_screening_progress(tmp_path: Path) -> None:
    switch = interpretation(
        language=Language.EN,
        explicit_switch=Language.EN,
        consent=None,
    )
    with screening_client(tmp_path, [switch]) as (
        client,
        _,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "Please continue in English")

    assert response.json()["progress"]["collected_fields"] == 0
    assert response.json()["progress"]["total_fields"] == 7
    assert response.json()["progress"]["current_stage"] == "full_name"


def test_real_spanish_location_is_accepted_and_canonicalized(tmp_path: Path) -> None:
    location = interpretation(location_raw="España, Madrid centro")
    with screening_client(tmp_path, [location]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "España, Madrid centro")
        record = screening_row(database_path)
        data = json.loads(record["data"])

    assert response.json()["progress"]["collected_fields"] == 1
    assert record["service_area_supported"] == 1
    assert (data["location_country"], data["location_city"], data["location_zone"]) == (
        "ES",
        "Madrid",
        "Centro",
    )


def test_country_only_asks_for_city_and_zone(tmp_path: Path) -> None:
    country = interpretation(location_raw="España", location_country="España")
    with screening_client(tmp_path, [country]) as (
        client,
        _,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "España")

    text = response.json()["assistant_message"]["content"]
    assert "ciudad y zona" in text
    assert "país" not in text


def test_city_only_asks_only_for_zone(tmp_path: Path) -> None:
    city = interpretation(location_raw="Madrid", location_city="Madrid")
    with screening_client(tmp_path, [city]) as (
        client,
        _,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "Madrid")

    text = response.json()["assistant_message"]["content"]
    assert text == "¿En qué zona de Madrid trabajarías?"


def test_close_location_match_is_persisted_only_after_confirmation(
    tmp_path: Path,
) -> None:
    misspelled = interpretation(location_raw="Madird centro")
    confirmed = interpretation(location_confirmation=True)
    with screening_client(tmp_path, [misspelled, confirmed]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        first = send(client, conversation_id, "Madird centro")
        before = json.loads(screening_row(database_path)["data"])
        send(client, conversation_id, "Sí, Madrid Centro")
        after = json.loads(screening_row(database_path)["data"])

    assert first.json()["assistant_message"]["content"] == (
        "¿Te refieres a Madrid, zona Centro?"
    )
    assert before["location_city"] is None
    assert after["location_country"] == "ES"
    assert after["location_city"] == "Madrid"
    assert after["location_zone"] == "Centro"


def test_typo_then_zone_wording_does_not_exhaust_clarifications(
    tmp_path: Path,
) -> None:
    typo = interpretation(
        location_raw="madird city center",
        location_city="Madrid",
        location_zone="City Center",
    )
    zone_only = interpretation(
        location_raw="city center",
        location_zone="City Center",
    )
    with screening_client(tmp_path, [typo, zone_only]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        first = send(client, conversation_id, "madird city center")
        first_record = screening_row(database_path)
        second = send(client, conversation_id, "city center")
        second_record = screening_row(database_path)

    assert first.json()["assistant_message"]["content"] == (
        "¿Te refieres a Madrid, zona Centro?"
    )
    assert json.loads(first_record["clarification_counts"]).get("service_area") is None
    assert second.json()["conversation_status"] == "in_progress"
    assert second.json()["outcome"] is None
    assert json.loads(second_record["clarification_counts"])["service_area"] == 1


def test_known_madrid_plus_city_center_resolves_supported_area(
    tmp_path: Path,
) -> None:
    city = interpretation(location_raw="madrid", location_city="Madrid")
    zone = interpretation(location_raw="city center", location_zone="City Center")
    with screening_client(tmp_path, [city, zone]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        first = send(client, conversation_id, "madrid")
        second = send(client, conversation_id, "city center")
        record = screening_row(database_path)

    assert first.json()["assistant_message"]["content"] == (
        "¿En qué zona de Madrid trabajarías?"
    )
    data = json.loads(record["data"])
    assert (data["location_country"], data["location_city"], data["location_zone"]) == (
        "ES",
        "Madrid",
        "Centro",
    )
    assert record["service_area_supported"] == 1
    assert "service_area" not in second.json()["missing_fields"]


def test_multiple_supported_locations_require_a_primary_choice(
    tmp_path: Path,
) -> None:
    identity = interpretation(
        full_name="Ana Demo",
        driver_license=DriverLicense.YES,
    )
    alternatives = interpretation(
        consent=None,
        ambiguous=True,
        clarification_fields=["service_area"],
        location_raw="Madrid por Sanse o por el centro",
        location_city="Madrid",
        location_zone="Centro",
    )
    selected = interpretation(
        consent=None,
        location_raw="Sanse",
        location_city="Sanse",
        location_zone="Sanse",
    )
    with screening_client(tmp_path, [identity, alternatives, selected]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        send(client, conversation_id, "Ana Demo, carnet vigente")
        choice = send(client, conversation_id, "Madrid por Sanse o por el centro")
        choice_record = screening_row(database_path)
        resolved = send(client, conversation_id, "Sanse")
        resolved_record = screening_row(database_path)

    assert choice.json()["assistant_message"]["content"] == (
        "¿Qué zona prefieres como principal: San Sebastián de los Reyes o "
        "Madrid Centro?"
    )
    assert choice.json()["conversation_status"] == "in_progress"
    assert json.loads(choice_record["clarification_counts"]).get("service_area") is None
    resolved_data = json.loads(resolved_record["data"])
    assert resolved_data["location_city"] == "San Sebastián de los Reyes"
    assert resolved_data["location_zone"] == "Área urbana"
    assert resolved.json()["conversation_status"] == "in_progress"


def test_unknown_location_disqualifies_only_after_confirmation(
    tmp_path: Path,
) -> None:
    unknown = interpretation(
        location_raw="Barcelona, Norte",
        location_city="Barcelona",
        location_zone="Norte",
    )
    confirmed = interpretation(outside_confirmed=True)
    with screening_client(tmp_path, [unknown, confirmed]) as (
        client,
        _,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        first = send(client, conversation_id, "Barcelona, Norte")
        terminal = send(client, conversation_id, "Sí, confirmo")

    assert first.json()["conversation_status"] == "in_progress"
    assert terminal.json()["outcome"] == "disqualified"
    assert terminal.json()["disqualification_reason"] == "outside_service_area"


def test_unresolved_location_reaches_retry_limit_after_two_failed_follow_ups(
    tmp_path: Path,
) -> None:
    unknown = interpretation(
        location_raw="Un lugar desconocido",
        location_city="Desconocida",
        location_zone="Ninguna",
    )
    with screening_client(tmp_path, [unknown, unknown, unknown]) as (
        client,
        _,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        first = send(client, conversation_id, "Un lugar desconocido")
        second = send(client, conversation_id, "Sigue siendo ese lugar")
        terminal = send(client, conversation_id, "Lo repito: ese lugar")

    assert first.json()["conversation_status"] == "in_progress"
    assert second.json()["conversation_status"] == "in_progress"
    assert terminal.json()["outcome"] == "needs_review"


def _availability_setup() -> MessageInterpretation:
    return interpretation(
        full_name="Ana Demo",
        driver_license=DriverLicense.YES,
        location_raw="Madrid Centro",
        location_city="Madrid",
        location_zone="Centro",
    )


@pytest.mark.parametrize(
    "candidate_text",
    ["cuando sea", "me da igual el horario", "a cualquier hora"],
)
def test_flexible_schedule_is_useful_partial_information(
    tmp_path: Path,
    candidate_text: str,
) -> None:
    flexible = interpretation(
        consent=None,
        clarification_fields=["availability"],
        preferred_schedule=[Schedule.FLEXIBLE],
    )
    with screening_client(tmp_path, [_availability_setup(), flexible]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        send(client, conversation_id, "Datos iniciales")
        response = send(client, conversation_id, candidate_text)
        record = screening_row(database_path)

    assert response.json()["assistant_message"]["content"] == (
        "Perfecto, tienes flexibilidad horaria. "
        "¿Buscas jornada completa o parcial?"
    )
    data = json.loads(record["data"])
    assert data["preferred_schedule"] == ["flexible"]
    assert data["availability"] == []
    assert json.loads(record["clarification_counts"]).get("availability") is None
    assert response.json()["conversation_status"] == "in_progress"


@pytest.mark.parametrize("candidate_text", ["puedo cualquier día", "todos los días"])
def test_any_day_availability_requires_full_time_confirmation(
    tmp_path: Path,
    candidate_text: str,
) -> None:
    any_day = interpretation(
        consent=None,
        availability_confirmation_required=True,
        availability=[Availability.WEEKENDS],
    )
    with screening_client(tmp_path, [_availability_setup(), any_day]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        send(client, conversation_id, "Datos iniciales")
        response = send(client, conversation_id, candidate_text)
        record = screening_row(database_path)

    assert response.json()["assistant_message"]["content"] == (
        "Entendido, puedes trabajar cualquier día, incluidos fines de semana. "
        "¿Confirmas que tienes disponibilidad para jornada completa?"
    )
    data = json.loads(record["data"])
    assert data["availability"] == ["weekends"]
    assert "full_time" not in data["availability"]
    assert json.loads(record["pending_data"])[
        "availability_full_time_confirmation"
    ] is True
    assert response.json()["conversation_status"] == "in_progress"


def test_flexible_then_any_day_progress_does_not_route_to_review(
    tmp_path: Path,
) -> None:
    flexible = interpretation(
        consent=None,
        clarification_fields=["availability"],
        preferred_schedule=[Schedule.FLEXIBLE],
    )
    any_day = interpretation(
        consent=None,
        availability_confirmation_required=True,
        availability=[Availability.WEEKENDS],
    )
    full_time = interpretation(
        consent=None,
        availability=[Availability.FULL_TIME],
    )
    with screening_client(
        tmp_path,
        [_availability_setup(), flexible, any_day, full_time],
    ) as (client, database_path, conversation_id, _):
        start(client, conversation_id)
        send(client, conversation_id, "Datos iniciales")
        first = send(client, conversation_id, "cuando sea")
        second = send(client, conversation_id, "puedo cualquier día")
        third = send(client, conversation_id, "sí")
        record = screening_row(database_path)

    assert first.json()["conversation_status"] == "in_progress"
    assert second.json()["conversation_status"] == "in_progress"
    assert third.json()["conversation_status"] == "in_progress"
    assert json.loads(record["data"])["availability"] == [
        "weekends",
        "full_time",
    ]
    assert "availability_full_time_confirmation" not in json.loads(
        record["pending_data"]
    )
    assert json.loads(record["clarification_counts"]).get("availability") is None


def test_spanish_happy_path(tmp_path: Path) -> None:
    first_turn = interpretation(
        full_name="Alex Rivera",
        driver_license=DriverLicense.YES,
        location_raw="Madrid, Zona Centro Demo ES-01",
        location_country="Spain",
        location_city="Madrid",
        location_zone="Zona Centro Demo ES-01",
    )
    second_turn = interpretation(
        availability=[Availability.FULL_TIME],
        preferred_schedule=[Schedule.FLEXIBLE],
        delivery_experience_years=2,
        delivery_platforms=["Demo Delivery"],
        start_date_raw=future_date().isoformat(),
        start_date=future_date(),
        date_confirmed=True,
    )
    with screening_client(tmp_path, [first_turn, second_turn]) as (
        client,
        _,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        first = send(client, conversation_id, "Datos personales y ubicación")
        terminal = send(client, conversation_id, "Disponibilidad y experiencia")

    assert first.json()["conversation_status"] == "in_progress"
    assert terminal.json()["outcome"] == "qualified"
    assert "Gracias" in terminal.json()["assistant_message"]["content"]


def test_english_happy_path(tmp_path: Path) -> None:
    complete = interpretation(
        language=Language.EN,
        date_confirmed=True,
        **complete_updates(
            start_date=future_date(),
            country="Mexico",
            city="Mexico City",
            zone="Zona Central Demo MX-01",
        ),
    )
    with screening_client(
        tmp_path,
        [complete],
        preferred_language=Language.EN,
    ) as (client, _, conversation_id, _):
        initial = start(client, conversation_id)
        terminal = send(client, conversation_id, "Here is all my information")

    assert initial.json()["assistant_message"]["content"] == (
        "Hi 👋 We received your application for the delivery driver role at Grupo "
        "Sazón. The screening takes about 3 minutes. To continue, what is your "
        "full name?"
    )
    assert terminal.json()["outcome"] == "qualified"
    assert terminal.json()["assistant_message"]["content"] == (
        "Thank you, Alex. You have completed the initial screening and meet the "
        "configured basic requirements for the role. Grupo Sazón's recruitment "
        "team will review your application and contact you with the next steps."
    )


def test_multiple_fields_in_one_answer(tmp_path: Path) -> None:
    complete = interpretation(
        date_confirmed=True,
        **complete_updates(start_date=future_date()),
    )
    with screening_client(tmp_path, [complete]) as (
        client,
        _,
        conversation_id,
        provider,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "All requested information")

    assert response.json()["outcome"] == "qualified"
    assert provider.interpret_calls == 1


def test_explicit_code_switch_preserves_collected_state(tmp_path: Path) -> None:
    name_turn = interpretation(language=Language.EN, full_name="Ana López")
    switch_turn = interpretation(
        language=Language.EN,
        explicit_switch=Language.EN,
        driver_license=DriverLicense.YES,
    )
    with screening_client(tmp_path, [name_turn, switch_turn]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        send(client, conversation_id, "Ana López")
        first_data = json.loads(screening_row(database_path)["data"])
        send(client, conversation_id, "Please switch to English. Yes, I have one.")
        switched_data = json.loads(screening_row(database_path)["data"])

    assert first_data["language"] == "es"
    assert switched_data["language"] == "en"
    assert switched_data["full_name"] == "Ana López"
    assert switched_data["driver_license"] == "yes"


def test_complete_sentence_can_switch_language_without_explicit_request(
    tmp_path: Path,
) -> None:
    english_sentence = interpretation(
        language=Language.EN,
        explicit_switch=None,
        driver_license=DriverLicense.YES,
    )
    with screening_client(tmp_path, [english_sentence]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "I have a valid driver's license")
        data = json.loads(screening_row(database_path)["data"])

    assert data["language"] == "en"
    assert response.json()["selected_language"] == "en"


def test_driver_license_disqualification(tmp_path: Path) -> None:
    no_license = interpretation(driver_license=DriverLicense.NO)
    with screening_client(tmp_path, [no_license]) as (
        client,
        _,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "No tengo permiso")

    assert response.json()["outcome"] == "disqualified"
    assert response.json()["disqualification_reason"] == "no_driver_license"


def test_confirmed_out_of_area_disqualification(tmp_path: Path) -> None:
    outside = interpretation(
        outside_confirmed=True,
        driver_license=DriverLicense.YES,
        location_raw="Barcelona, Zona Real",
        location_country="Spain",
        location_city="Barcelona",
        location_zone="Zona Real",
    )
    with screening_client(tmp_path, [outside]) as (
        client,
        _,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "Confirmo Barcelona, Zona Real")

    assert response.json()["outcome"] == "disqualified"
    assert response.json()["disqualification_reason"] == "outside_service_area"


def test_zero_delivery_experience_is_valid(tmp_path: Path) -> None:
    complete = interpretation(
        date_confirmed=True,
        **complete_updates(start_date=future_date(), years=0),
    )
    with screening_client(tmp_path, [complete]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "No delivery experience")
        data = json.loads(screening_row(database_path)["data"])

    assert response.json()["outcome"] == "qualified"
    assert data["delivery_experience_years"] == 0
    assert data["delivery_platforms"] == []


def test_ambiguous_input_reaches_retry_limit(tmp_path: Path) -> None:
    unclear = interpretation(
        ambiguous=True,
        clarification_fields=["driver_license"],
    )
    with screening_client(tmp_path, [unclear, unclear]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        first = send(client, conversation_id, "No está claro")
        first_counts = json.loads(screening_row(database_path)["clarification_counts"])
        second = send(client, conversation_id, "Sigue sin estar claro")

    assert first.json()["conversation_status"] == "in_progress"
    assert first_counts["driver_license"] == 1
    assert second.json()["outcome"] == "needs_review"


def test_first_abusive_message_issues_warning(tmp_path: Path) -> None:
    abusive = interpretation(abusive=True)
    with screening_client(tmp_path, [abusive]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "Abusive text")
        record = screening_row(database_path)

    assert response.json()["conversation_status"] == "in_progress"
    assert "respetuosa" in response.json()["assistant_message"]["content"]
    assert record["abuse_count"] == 1


def test_repeated_abuse_is_terminal(tmp_path: Path) -> None:
    abusive = interpretation(abusive=True)
    with screening_client(tmp_path, [abusive, abusive]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        send(client, conversation_id, "First abusive text")
        response = send(client, conversation_id, "Second abusive text")
        record = screening_row(database_path)

    assert response.json()["outcome"] == "disqualified"
    assert record["abuse_count"] == 2
    assert record["disqualification_reason"] == "repeated_abuse_after_warning"


def test_past_start_date_requires_clarification(tmp_path: Path) -> None:
    past = datetime.now(UTC).date() - timedelta(days=1)
    proposed = interpretation(
        date_confirmed=True,
        **complete_updates(start_date=past),
    )
    with screening_client(tmp_path, [proposed]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "I could start yesterday")
        record = screening_row(database_path)
        data = json.loads(record["data"])

    assert response.json()["conversation_status"] == "in_progress"
    assert "start_date" in response.json()["missing_fields"]
    assert data["start_date"] is None
    assert json.loads(record["clarification_counts"]).get("start_date") is None


def test_relative_start_date_requires_explicit_confirmation(tmp_path: Path) -> None:
    start_on = future_date()
    relative = interpretation(
        relative_date=True,
        date_confirmed=False,
        **complete_updates(start_date=start_on),
    )
    confirmed = interpretation(date_confirmed=True)
    with screening_client(tmp_path, [relative, confirmed]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        first = send(client, conversation_id, "In about a month")
        pending = json.loads(screening_row(database_path)["pending_data"])
        terminal = send(client, conversation_id, "Yes, I confirm that date")
        data = json.loads(screening_row(database_path)["data"])

    assert first.json()["conversation_status"] == "in_progress"
    assert pending["start_date"] == start_on.isoformat()
    assert terminal.json()["outcome"] == "qualified"
    assert data["start_date"] == start_on.isoformat()


def test_llm_timeout_recovers_without_screening_updates(tmp_path: Path) -> None:
    timeout = ProviderUnavailableError("llm_timeout")
    with screening_client(tmp_path, [timeout]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        response = send(client, conversation_id, "My name is Alex")
        record = screening_row(database_path)
        data = json.loads(record["data"])
        last_message = database_row(
            database_path,
            "SELECT * FROM messages ORDER BY sequence_number DESC LIMIT 1",
        )

    assert response.status_code == 200
    assert "Inténtalo de nuevo" in response.json()["assistant_message"]["content"]
    assert data["full_name"] is None
    assert record["recoverable_error_code"] == "llm_timeout"
    assert last_message["recoverable_error_code"] == "llm_timeout"


def test_structured_state_and_complete_history_are_persisted(tmp_path: Path) -> None:
    name = interpretation(full_name="Alex Rivera")
    license_answer = interpretation(driver_license=DriverLicense.YES)
    with screening_client(tmp_path, [name, license_answer]) as (
        client,
        database_path,
        conversation_id,
        _,
    ):
        start(client, conversation_id)
        send(client, conversation_id, "Alex Rivera")
        send(client, conversation_id, "Sí")
        record = screening_row(database_path)
        with sqlite3.connect(database_path) as connection:
            messages = connection.execute(
                "SELECT sequence_number, role FROM messages "
                "ORDER BY sequence_number"
            ).fetchall()

    data = json.loads(record["data"])
    assert messages == [
        (0, "assistant"),
        (1, "user"),
        (2, "assistant"),
        (3, "user"),
        (4, "assistant"),
    ]
    assert data["full_name"] == "Alex Rivera"
    assert data["driver_license"] == "yes"
    assert record["llm_provider"] == "fake"
    assert record["llm_model"] == "fake-screening"


def test_terminal_summary_has_deterministic_fallback(tmp_path: Path) -> None:
    complete = interpretation(
        date_confirmed=True,
        **complete_updates(start_date=future_date()),
    )
    summary_error = ProviderUnavailableError("llm_timeout")
    with screening_client(
        tmp_path,
        [complete],
        summaries=[summary_error],
    ) as (client, database_path, conversation_id, provider):
        start(client, conversation_id)
        response = send(client, conversation_id, "All information")
        record = screening_row(database_path)

    assert response.json()["outcome"] == "qualified"
    assert record["final_summary"] == (
        "Alex Rivera: screening ended with status qualified."
    )
    assert record["recoverable_error_code"] == "llm_timeout"
    assert provider.summary_calls == 1
