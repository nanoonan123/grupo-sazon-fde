"""Tests for deterministic service-area resolution semantics."""

import json
from pathlib import Path

import pytest

from app.service_areas import LocationResolutionStatus, ServiceAreaCatalog


@pytest.fixture
def catalog() -> ServiceAreaCatalog:
    """Load the repository's explicitly synthetic service areas."""

    return ServiceAreaCatalog.from_file(Path("data/service_areas.json"))


@pytest.mark.parametrize(
    "raw,country_code,city,zone",
    [
        ("España, Madrid centro", "ES", "Madrid", "Centro"),
        ("País: España. Ciudad: Madrid. Zona: Centro.", "ES", "Madrid", "Centro"),
        ("Madrid Centro", "ES", "Madrid", "Centro"),
        ("madrid city center", "ES", "Madrid", "Centro"),
        ("Madrid city centre", "ES", "Madrid", "Centro"),
        ("downtown Madrid", "ES", "Madrid", "Centro"),
        ("  madrid,   ZONA centro ", "ES", "Madrid", "Centro"),
        ("México / CDMX / Central", "MX", "Mexico City", "Central"),
        ("cdmx centro", "MX", "Mexico City", "Central"),
        ("downtown Mexico City", "MX", "Mexico City", "Central"),
    ],
)
def test_supported_location_aliases_are_canonicalized(
    catalog: ServiceAreaCatalog,
    raw: str,
    country_code: str,
    city: str,
    zone: str,
) -> None:
    result = catalog.resolve(raw=raw)

    assert result.status is LocationResolutionStatus.RESOLVED
    assert (result.country_code, result.city, result.zone) == (
        country_code,
        city,
        zone,
    )


@pytest.mark.parametrize("country", ["España", "espana", "Mexico", "méxico"])
def test_country_alone_is_incomplete(
    catalog: ServiceAreaCatalog,
    country: str,
) -> None:
    result = catalog.resolve(raw=country)

    assert result.status is LocationResolutionStatus.INCOMPLETE
    assert result.country_code in {"ES", "MX"}
    assert result.missing_components == ("city", "zone")


def test_city_alone_requires_zone(catalog: ServiceAreaCatalog) -> None:
    result = catalog.resolve(raw="Madrid")

    assert result.status is LocationResolutionStatus.INCOMPLETE
    assert result.city == "Madrid"
    assert result.missing_components == ("zone",)


def test_zone_follow_up_combines_with_known_city(
    catalog: ServiceAreaCatalog,
) -> None:
    result = catalog.resolve(raw="city center", city="Madrid")

    assert result.status is LocationResolutionStatus.RESOLVED
    assert (result.country_code, result.city, result.zone) == (
        "ES",
        "Madrid",
        "Centro",
    )


def test_close_misspelling_requires_confirmation(
    catalog: ServiceAreaCatalog,
) -> None:
    result = catalog.resolve(raw="madird city center")

    assert result.status is LocationResolutionStatus.SUGGESTION
    assert result.suggestion is not None
    assert result.suggestion.city == "Madrid"
    assert result.suggestion.zone == "Centro"


def test_unknown_location_is_not_supported(catalog: ServiceAreaCatalog) -> None:
    result = catalog.resolve(raw="Barcelona, Norte")

    assert result.status is LocationResolutionStatus.UNKNOWN


def test_country_is_requested_only_for_cross_country_ambiguity(
    tmp_path: Path,
) -> None:
    document = {
        "countries": [
            {
                "country_code": code,
                "country_name": name,
                "areas": [
                    {"city": "Springfield", "zone": "Centro"},
                ],
            }
            for code, name in (("AA", "Alpha"), ("BB", "Beta"))
        ]
    }
    path = tmp_path / "ambiguous-areas.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    ambiguous_catalog = ServiceAreaCatalog.from_file(path)

    ambiguous = ambiguous_catalog.resolve(raw="Springfield Centro")
    resolved = ambiguous_catalog.resolve(
        country="Alpha",
        city="Springfield",
        zone="Centro",
    )

    assert ambiguous.status is LocationResolutionStatus.INCOMPLETE
    assert ambiguous.missing_components == ("country",)
    assert resolved.status is LocationResolutionStatus.RESOLVED
    assert resolved.country_code == "AA"
