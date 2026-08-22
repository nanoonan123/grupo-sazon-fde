"""Deterministic loading and resolution of configured service areas."""

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from pathlib import Path


def _normalize(value: str) -> str:
    """Normalize text without inventing a fuzzy match."""

    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    words_only = re.sub(r"[^a-z0-9]+", " ", without_marks)
    return " ".join(words_only.split())


def _contains_phrase(text: str, phrase: str) -> bool:
    """Return whether normalized text contains a complete normalized phrase."""

    return f" {phrase} " in f" {text} "


class LocationResolutionStatus(StrEnum):
    """Possible deterministic outcomes from resolving candidate location text."""

    RESOLVED = "resolved"
    INCOMPLETE = "incomplete"
    SUGGESTION = "suggestion"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ServiceArea:
    """One canonical configured service area and its explicit aliases."""

    country_code: str
    country_name: str
    city: str
    zone: str
    country_aliases: frozenset[str]
    city_aliases: frozenset[str]
    zone_aliases: frozenset[str]


@dataclass(frozen=True)
class LocationResolution:
    """Deterministic location result consumed by the screening workflow."""

    status: LocationResolutionStatus
    country_code: str | None = None
    city: str | None = None
    zone: str | None = None
    missing_components: tuple[str, ...] = ()
    suggestion: ServiceArea | None = None


@dataclass(frozen=True)
class ServiceAreaCatalog:
    """Immutable configured service areas with conservative text resolution."""

    areas: tuple[ServiceArea, ...]

    @classmethod
    def from_file(cls, path: str | Path) -> "ServiceAreaCatalog":
        """Load canonical demo areas and their configured aliases from JSON."""

        with Path(path).open(encoding="utf-8") as file:
            document = json.load(file)
        areas: list[ServiceArea] = []
        for country in document["countries"]:
            country_aliases = frozenset(
                _normalize(alias)
                for alias in (
                    country["country_code"],
                    country["country_name"],
                    *country.get("aliases", []),
                )
            )
            for area in country["areas"]:
                city_aliases = frozenset(
                    _normalize(alias)
                    for alias in (area["city"], *area.get("city_aliases", []))
                )
                zone_aliases = frozenset(
                    _normalize(alias)
                    for alias in (area["zone"], *area.get("zone_aliases", []))
                )
                areas.append(
                    ServiceArea(
                        country_code=country["country_code"].upper(),
                        country_name=country["country_name"],
                        city=area["city"],
                        zone=area["zone"],
                        country_aliases=country_aliases,
                        city_aliases=city_aliases,
                        zone_aliases=zone_aliases,
                    )
                )
        return cls(areas=tuple(areas))

    def _country_code(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = _normalize(value)
        codes = {
            area.country_code
            for area in self.areas
            if normalized in area.country_aliases
        }
        return next(iter(codes)) if len(codes) == 1 else None

    def _country_from_raw(self, raw: str) -> str | None:
        codes = {
            area.country_code
            for area in self.areas
            for alias in area.country_aliases
            if len(alias) > 2 and _contains_phrase(raw, alias)
        }
        return next(iter(codes)) if len(codes) == 1 else None

    @staticmethod
    def _field_matches(
        value: str | None,
        areas: tuple[ServiceArea, ...],
        attribute: str,
    ) -> set[ServiceArea]:
        if not value:
            return set()
        normalized = _normalize(value)
        return {
            area
            for area in areas
            if normalized in getattr(area, attribute)
        }

    @staticmethod
    def _raw_matches(
        raw: str,
        areas: tuple[ServiceArea, ...],
        attribute: str,
    ) -> set[ServiceArea]:
        if not raw:
            return set()
        return {
            area
            for area in areas
            if any(
                _contains_phrase(raw, alias)
                for alias in getattr(area, attribute)
            )
        }

    def _suggestion(
        self,
        raw: str,
        city: str | None,
        zone: str | None,
        country_code: str | None,
    ) -> ServiceArea | None:
        """Return one strong close match for confirmation, never acceptance."""

        query = _normalize(" ".join(part for part in (city, zone) if part))
        if not query:
            query = raw
            labels = ("pais", "country", "ciudad", "city", "zona", "zone")
            query = " ".join(word for word in query.split() if word not in labels)
            for area in self.areas:
                for alias in area.country_aliases:
                    if len(alias) > 2:
                        query = re.sub(rf"\b{re.escape(alias)}\b", " ", query)
            query = " ".join(query.split())
        if not query:
            return None

        candidates = tuple(
            area
            for area in self.areas
            if country_code is None or area.country_code == country_code
        )
        scored: list[tuple[float, ServiceArea]] = []
        for area in candidates:
            score = max(
                SequenceMatcher(None, query, f"{city_alias} {zone_alias}").ratio()
                for city_alias in area.city_aliases
                for zone_alias in area.zone_aliases
            )
            scored.append((score, area))
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored or scored[0][0] < 0.82:
            return None
        if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08:
            return None
        return scored[0][1]

    def resolve(
        self,
        *,
        raw: str | None = None,
        country: str | None = None,
        city: str | None = None,
        zone: str | None = None,
    ) -> LocationResolution:
        """Resolve explicit location data using only configured deterministic rules."""

        normalized_raw = _normalize(raw or "")
        country_code = self._country_code(country)
        unknown_country = bool(country and country_code is None)
        if country_code is None and not unknown_country:
            country_code = self._country_from_raw(normalized_raw)

        city_matches = self._field_matches(city, self.areas, "city_aliases")
        if not city_matches:
            city_matches = self._raw_matches(
                normalized_raw,
                self.areas,
                "city_aliases",
            )
        zone_matches = self._field_matches(zone, self.areas, "zone_aliases")
        if not zone_matches:
            zone_matches = self._raw_matches(
                normalized_raw,
                self.areas,
                "zone_aliases",
            )

        exact = city_matches & zone_matches
        if country_code is not None:
            exact = {area for area in exact if area.country_code == country_code}
        if len(exact) == 1 and not unknown_country:
            area = next(iter(exact))
            return LocationResolution(
                status=LocationResolutionStatus.RESOLVED,
                country_code=area.country_code,
                city=area.city,
                zone=area.zone,
            )
        if len(exact) > 1:
            countries = {area.country_code for area in exact}
            if len(countries) > 1:
                example = next(iter(exact))
                return LocationResolution(
                    status=LocationResolutionStatus.INCOMPLETE,
                    city=example.city,
                    zone=example.zone,
                    missing_components=("country",),
                )

        suggestion = self._suggestion(
            normalized_raw,
            city,
            zone,
            country_code,
        )
        if suggestion is not None:
            return LocationResolution(
                status=LocationResolutionStatus.SUGGESTION,
                suggestion=suggestion,
            )

        filtered_city_matches = {
            area
            for area in city_matches
            if country_code is None or area.country_code == country_code
        }
        filtered_zone_matches = {
            area
            for area in zone_matches
            if country_code is None or area.country_code == country_code
        }
        cities = {area.city for area in filtered_city_matches}
        zones = {area.zone for area in filtered_zone_matches}
        canonical_city = next(iter(cities)) if len(cities) == 1 else None
        canonical_zone = next(iter(zones)) if len(zones) == 1 else None
        if canonical_city and not canonical_zone:
            return LocationResolution(
                status=LocationResolutionStatus.INCOMPLETE,
                country_code=country_code,
                city=canonical_city,
                missing_components=("zone",),
            )
        if canonical_zone and not canonical_city:
            return LocationResolution(
                status=LocationResolutionStatus.INCOMPLETE,
                country_code=country_code,
                zone=canonical_zone,
                missing_components=("city",),
            )
        if country_code and not city_matches and not zone_matches and not (
            city or zone
        ):
            return LocationResolution(
                status=LocationResolutionStatus.INCOMPLETE,
                country_code=country_code,
                missing_components=("city", "zone"),
            )
        if not any((raw, country, city, zone)):
            return LocationResolution(
                status=LocationResolutionStatus.INCOMPLETE,
                missing_components=("city", "zone"),
            )
        return LocationResolution(status=LocationResolutionStatus.UNKNOWN)

    def supports(self, country: str, city: str, zone: str) -> bool:
        """Return whether values resolve to one exact configured area."""

        return self.resolve(country=country, city=city, zone=zone).status is (
            LocationResolutionStatus.RESOLVED
        )
