"""Focused booking tests for the qualified-candidate scheduling boundary."""

from datetime import UTC, datetime

import pytest

from app.interviews import _slot_read, available_slot_starts


@pytest.mark.parametrize(
    ("country", "timezone"),
    [("ES", "Europe/Madrid"), ("MX", "America/Mexico_City")],
)
def test_demo_slots_are_wednesday_or_thursday_in_the_country_timezone(
    country: str,
    timezone: str,
) -> None:
    """Slots use the bounded local weekday, hour, and duration assumptions."""

    starts = available_slot_starts(
        country,
        now=datetime(2026, 8, 24, 9, tzinfo=UTC),
    )

    assert starts
    for start in starts:
        local = _slot_read(start, timezone)
        weekday = datetime.fromisoformat(local.local_date).weekday()
        assert weekday in {2, 3}
        assert 10 <= int(local.local_time[:2]) < 14
        assert local.local_time.endswith(("00", "30"))
