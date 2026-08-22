"""Explicit transient LangGraph workflow for one screening turn."""

import re
from datetime import date
from time import perf_counter
from typing import TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.models import (
    CandidateIntent,
    GraphRoute,
    MessageInterpretation,
    ProviderMessage,
    ScreeningStage,
    WorkflowResult,
)
from app.agent.provider import ProviderUnavailableError, ScreeningLLMProvider
from app.domain.models import (
    DisqualificationReason,
    DriverLicense,
    EligibilityContext,
    ScreeningData,
    ScreeningStatus,
)
from app.domain.rules import evaluate_eligibility, missing_required_fields
from app.service_areas import (
    LocationResolutionStatus,
    ServiceAreaCatalog,
)


class ScreeningGraphState(TypedDict):
    """Transient state reconstructed from authoritative database records."""

    history: list[ProviderMessage]
    screening_data: ScreeningData
    pending_data: dict[str, object]
    clarification_counts: dict[str, int]
    abuse_count: int
    consent_granted: bool | None
    service_area_supported: bool | None
    status: ScreeningStatus
    stage: ScreeningStage
    interpretation: MessageInterpretation | None
    turn_clarification_fields: list[str]
    turn_resolved_fields: list[str]
    route: GraphRoute
    missing_fields: list[str]
    disqualification_reason: DisqualificationReason | None
    response_text: str
    final_summary: str | None
    provider_name: str | None
    provider_model: str | None
    provider_latency_ms: int | None
    provider_error_code: str | None
    debug_explanation: str | None
    current_date: date


STAGE_ORDER = (
    ScreeningStage.FULL_NAME,
    ScreeningStage.DRIVER_LICENSE,
    ScreeningStage.SERVICE_AREA,
    ScreeningStage.AVAILABILITY,
    ScreeningStage.PREFERRED_SCHEDULE,
    ScreeningStage.DELIVERY_EXPERIENCE,
    ScreeningStage.START_DATE,
)

FIELD_TO_STAGE = {
    "consent": ScreeningStage.CONSENT,
    "full_name": ScreeningStage.FULL_NAME,
    "driver_license": ScreeningStage.DRIVER_LICENSE,
    "service_area": ScreeningStage.SERVICE_AREA,
    "availability": ScreeningStage.AVAILABILITY,
    "preferred_schedule": ScreeningStage.PREFERRED_SCHEDULE,
    "delivery_experience_years": ScreeningStage.DELIVERY_EXPERIENCE,
    "start_date": ScreeningStage.START_DATE,
}

KNOWN_CLARIFICATION_FIELDS = frozenset(FIELD_TO_STAGE)


def _latest_candidate_text(state: ScreeningGraphState) -> str:
    """Return the latest candidate message from database-reconstructed history."""

    for message in reversed(state["history"]):
        if message.role == "user":
            return message.content.strip()
    return ""


def _is_complete_language_turn(state: ScreeningGraphState) -> bool:
    """Reject isolated names/words while allowing clear sentence-level switching."""

    words = re.findall(r"[^\W_]+(?:['’][^\W_]+)?", _latest_candidate_text(state))
    return len(words) >= 4


def _stage_for_missing(missing_fields: list[str]) -> ScreeningStage:
    """Choose the first deterministic stage represented in missing fields."""

    missing = set(missing_fields)
    for stage in STAGE_ORDER:
        field = stage.value
        if stage is ScreeningStage.DELIVERY_EXPERIENCE:
            field = "delivery_experience_years"
        if field in missing:
            return stage
    return ScreeningStage.REVIEW if missing_fields else ScreeningStage.COMPLETE


def _current_missing_fields(state: ScreeningGraphState) -> list[str]:
    """Evaluate completion without introducing a terminal ambiguity outcome."""

    return missing_required_fields(
        state["screening_data"],
        state["service_area_supported"],
    )


def _merge_simple_updates(
    data: ScreeningData,
    interpretation: MessageInterpretation,
    clarifications: set[str],
) -> set[str]:
    """Merge non-location and non-date proposals that pass deterministic checks."""

    updates = interpretation.updates
    resolved: set[str] = set()
    if "full_name" not in clarifications and updates.full_name is not None:
        full_name = updates.full_name.strip()
        if full_name:
            data.full_name = full_name
            resolved.add("full_name")
        else:
            clarifications.add("full_name")
    if "driver_license" not in clarifications and updates.driver_license is not None:
        data.driver_license = updates.driver_license
        if updates.driver_license is DriverLicense.UNCLEAR:
            clarifications.add("driver_license")
        else:
            resolved.add("driver_license")
    if "availability" not in clarifications and updates.availability is not None:
        if updates.availability:
            data.availability = updates.availability
            resolved.add("availability")
        else:
            clarifications.add("availability")
    if (
        "preferred_schedule" not in clarifications
        and updates.preferred_schedule is not None
    ):
        if updates.preferred_schedule:
            data.preferred_schedule = updates.preferred_schedule
            resolved.add("preferred_schedule")
        else:
            clarifications.add("preferred_schedule")
    if updates.delivery_platforms is not None:
        data.delivery_platforms = [
            platform.strip()
            for platform in updates.delivery_platforms
            if platform.strip()
        ]
    if (
        "delivery_experience_years" not in clarifications
        and updates.delivery_experience_years is not None
    ):
        if updates.delivery_experience_years < 0:
            clarifications.add("delivery_experience_years")
        else:
            data.delivery_experience_years = updates.delivery_experience_years
            if updates.delivery_experience_years == 0 or data.delivery_platforms:
                resolved.add("delivery_experience_years")
            else:
                clarifications.add("delivery_experience_years")
    elif (
        data.delivery_experience_years is not None
        and data.delivery_experience_years > 0
        and updates.delivery_platforms
    ):
        resolved.add("delivery_experience_years")
    return resolved


def _merge_location(
    state: ScreeningGraphState,
    data: ScreeningData,
    interpretation: MessageInterpretation,
    clarifications: set[str],
    catalog: ServiceAreaCatalog,
) -> set[str]:
    """Resolve location text without silently accepting approximate matches."""

    pending = state["pending_data"]
    pending_location = pending.get("location")
    if (
        isinstance(pending_location, dict)
        and pending_location.get("status") == "unknown"
        and interpretation.confirmed_outside_service_area
    ):
        data.location_raw = str(pending_location.get("raw") or "") or None
        data.location_country = (
            str(pending_location["country"])
            if pending_location.get("country")
            else None
        )
        data.location_city = (
            str(pending_location["city"])
            if pending_location.get("city")
            else None
        )
        data.location_zone = (
            str(pending_location["zone"])
            if pending_location.get("zone")
            else None
        )
        state["service_area_supported"] = False
        pending.pop("location", None)
        clarifications.discard("service_area")
        return {"service_area"}
    if (
        isinstance(pending_location, dict)
        and pending_location.get("status") == "suggestion"
        and interpretation.location_suggestion_confirmed is True
    ):
        data.location_country = str(pending_location["country_code"])
        data.location_city = str(pending_location["city"])
        data.location_zone = str(pending_location["zone"])
        data.location_raw = str(pending_location.get("raw") or "") or None
        state["service_area_supported"] = True
        pending.pop("location", None)
        clarifications.discard("service_area")
        return {"service_area"}
    if (
        isinstance(pending_location, dict)
        and pending_location.get("status") == "suggestion"
        and interpretation.location_suggestion_confirmed is False
    ):
        pending["location"] = {
            "status": "incomplete",
            "missing_components": ["city", "zone"],
        }
        state["service_area_supported"] = None
        clarifications.add("service_area")
        return set()

    updates = interpretation.updates
    location_changed = any(
        value is not None
        for value in (
            updates.location_raw,
            updates.location_country,
            updates.location_city,
            updates.location_zone,
        )
    )
    if not location_changed:
        return set()

    raw = updates.location_raw or _latest_candidate_text(state)
    # Raw candidate wording is the evidence for a new location turn. Previously
    # validated partial state may complete it, but normalized LLM proposals cannot
    # silently turn approximate candidate text into an exact catalogue match.
    country = data.location_country
    city = data.location_city
    zone = data.location_zone
    resolution = catalog.resolve(raw=raw, country=country, city=city, zone=zone)
    if resolution.status is LocationResolutionStatus.RESOLVED:
        data.location_country = resolution.country_code
        data.location_city = resolution.city
        data.location_zone = resolution.zone
        data.location_raw = " / ".join(
            part
            for part in (
                resolution.country_code,
                resolution.city,
                resolution.zone,
            )
            if part
        )
        state["service_area_supported"] = True
        pending.pop("location", None)
        clarifications.discard("service_area")
        return {"service_area"}

    state["service_area_supported"] = None
    if resolution.status is LocationResolutionStatus.SUGGESTION:
        suggestion = resolution.suggestion
        if suggestion is None:
            raise RuntimeError("Suggestion status requires a configured area")
        pending["location"] = {
            "status": "suggestion",
            "country_code": suggestion.country_code,
            "city": suggestion.city,
            "zone": suggestion.zone,
            "raw": raw or ", ".join(part for part in (city, zone) if part),
        }
        clarifications.add("service_area")
        return set()

    if resolution.status is LocationResolutionStatus.INCOMPLETE:
        if resolution.country_code:
            data.location_country = resolution.country_code
        if resolution.city:
            data.location_city = resolution.city
        if resolution.zone:
            data.location_zone = resolution.zone
        pending["location"] = {
            "status": "incomplete",
            "missing_components": list(resolution.missing_components),
            "country_code": resolution.country_code,
            "city": resolution.city,
            "zone": resolution.zone,
        }
        clarifications.add("service_area")
        return set()

    unknown = {
        "status": "unknown",
        "raw": raw,
        "country": updates.location_country or country,
        "city": updates.location_city or city,
        "zone": updates.location_zone or zone,
    }
    pending["location"] = unknown
    if interpretation.confirmed_outside_service_area:
        data.location_raw = raw or ", ".join(
            part for part in (country, city, zone) if part
        )
        data.location_country = country
        data.location_city = city
        data.location_zone = zone
        state["service_area_supported"] = False
        pending.pop("location", None)
        clarifications.discard("service_area")
        return {"service_area"}
    clarifications.add("service_area")
    return set()


def _merge_start_date(
    state: ScreeningGraphState,
    data: ScreeningData,
    interpretation: MessageInterpretation,
    clarifications: set[str],
) -> set[str]:
    """Promote only confirmed, non-past explicit dates to authoritative data."""

    updates = interpretation.updates
    pending = state["pending_data"]
    if updates.start_date_raw is not None:
        data.start_date_raw = updates.start_date_raw.strip() or None
    if "start_date" in clarifications:
        return set()

    proposed_date = updates.start_date
    if proposed_date is None and interpretation.start_date_confirmed:
        pending_value = pending.get("start_date")
        if isinstance(pending_value, str):
            proposed_date = date.fromisoformat(pending_value)
    if proposed_date is None:
        return set()
    if proposed_date < state["current_date"]:
        pending.pop("start_date", None)
        clarifications.add("start_date")
        return set()
    if interpretation.start_date_is_relative or not interpretation.start_date_confirmed:
        pending["start_date"] = proposed_date.isoformat()
        clarifications.add("start_date")
        return set()
    data.start_date = proposed_date
    pending.pop("start_date", None)
    return {"start_date"}


def _deterministic_fallback_summary(state: ScreeningGraphState) -> str:
    """Build a factual terminal summary without an LLM dependency."""

    data = state["screening_data"]
    name = data.full_name or "Candidate"
    reason = state["disqualification_reason"]
    suffix = f" Reason: {reason.value}." if reason else ""
    return f"{name}: screening ended with status {state['status'].value}.{suffix}"


def build_screening_graph(
    provider: ScreeningLLMProvider,
    catalog: ServiceAreaCatalog,
    retry_limit: int,
) -> CompiledStateGraph:
    """Compile the explicit graph without a checkpointer or persistent memory."""

    async def interpret_message(state: ScreeningGraphState) -> dict[str, object]:
        started = perf_counter()
        try:
            result = await provider.interpret(
                state["history"],
                state["screening_data"],
                state["screening_data"].language,
                state["pending_data"],
                state["current_date"].isoformat(),
            )
        except ProviderUnavailableError as error:
            return {
                "provider_name": provider.name,
                "provider_model": provider.model,
                "provider_latency_ms": round((perf_counter() - started) * 1000),
                "provider_error_code": error.code,
            }
        return {
            "interpretation": result.value,
            "provider_name": result.provider,
            "provider_model": result.model,
            "provider_latency_ms": result.latency_ms,
            "debug_explanation": result.value.debug_explanation,
        }

    async def validate_and_merge(state: ScreeningGraphState) -> dict[str, object]:
        interpretation = state["interpretation"]
        if interpretation is None:
            return {}
        data = state["screening_data"].model_copy(deep=True)
        pending = dict(state["pending_data"])
        counts = dict(state["clarification_counts"])
        updates: dict[str, object] = {
            "screening_data": data,
            "pending_data": pending,
            "clarification_counts": counts,
        }
        if interpretation.explicit_language_switch is not None:
            data.language = interpretation.explicit_language_switch
            counts.pop("language", None)
        elif (
            data.language is not None
            and interpretation.detected_language is not data.language
            and _is_complete_language_turn(state)
        ):
            data.language = interpretation.detected_language

        consent_granted = state["consent_granted"]
        supplied_name_as_opt_in = (
            consent_granted is None
            and interpretation.consent is None
            and interpretation.intent is CandidateIntent.SCREENING_ANSWER
            and bool((interpretation.updates.full_name or "").strip())
        )
        consent_newly_granted = (
            (interpretation.consent is True or supplied_name_as_opt_in)
            and consent_granted is not True
        )
        if interpretation.consent is not None or supplied_name_as_opt_in:
            consent_granted = interpretation.consent is not False
            pending["consent_granted"] = consent_granted
            updates["consent_granted"] = consent_granted

        abuse_count = state["abuse_count"]
        if interpretation.abusive_language:
            abuse_count += 1
            updates["abuse_count"] = abuse_count
            return updates

        if consent_granted is not True:
            if consent_granted is None:
                counts["consent"] = counts.get("consent", 0) + 1
                updates["turn_clarification_fields"] = ["consent"]
            return updates

        clarifications = {
            field
            for field in interpretation.clarification_fields
            if field in KNOWN_CLARIFICATION_FIELDS
        }
        if interpretation.ambiguous and not clarifications:
            missing = _current_missing_fields(state)
            clarifications.add(missing[0] if missing else state["stage"].value)

        was_clarifying_location = isinstance(pending.get("location"), dict)
        resolved = _merge_simple_updates(data, interpretation, clarifications)
        if consent_newly_granted:
            resolved.add("consent")
        location_state = cast(ScreeningGraphState, {**state, **updates})
        resolved.update(
            _merge_location(
                location_state,
                data,
                interpretation,
                clarifications,
                catalog,
            )
        )
        updates["service_area_supported"] = location_state[
            "service_area_supported"
        ]
        date_state = cast(ScreeningGraphState, {**state, **updates})
        resolved.update(
            _merge_start_date(
                date_state,
                data,
                interpretation,
                clarifications,
            )
        )
        for field in resolved - clarifications:
            counts.pop(field, None)
        for field in clarifications:
            if field == "service_area" and not was_clarifying_location:
                continue
            counts[field] = counts.get(field, 0) + 1
        updates["turn_clarification_fields"] = sorted(clarifications)
        updates["turn_resolved_fields"] = sorted(resolved)
        return updates

    async def determine_next_action(state: ScreeningGraphState) -> dict[str, object]:
        interpretation = state["interpretation"]
        if state["provider_error_code"] is not None:
            missing = _current_missing_fields(state)
            return {
                "route": GraphRoute.ASK_NEXT_QUESTION,
                "status": ScreeningStatus.IN_PROGRESS,
                "stage": (
                    ScreeningStage.FULL_NAME
                    if state["consent_granted"] is not True
                    else _stage_for_missing(missing)
                ),
                "missing_fields": missing,
            }
        if interpretation is not None:
            if interpretation.intent is CandidateIntent.DATA_DELETION:
                return {
                    "route": GraphRoute.DATA_DELETION,
                    "status": ScreeningStatus.DELETED,
                    "stage": ScreeningStage.COMPLETE,
                    "missing_fields": [],
                }
            if (
                interpretation.intent is CandidateIntent.STOP
                or state["consent_granted"] is False
            ):
                return {
                    "route": GraphRoute.STOPPED,
                    "status": ScreeningStatus.INCOMPLETE,
                    "stage": ScreeningStage.COMPLETE,
                    "missing_fields": _current_missing_fields(state),
                }
        if state["consent_granted"] is not True:
            return {
                "route": GraphRoute.ASK_NEXT_QUESTION,
                "status": ScreeningStatus.IN_PROGRESS,
                "stage": ScreeningStage.FULL_NAME,
                "missing_fields": _current_missing_fields(state),
            }

        turn_fields = state["turn_clarification_fields"]
        retry_count = max(
            (state["clarification_counts"].get(field, 0) for field in turn_fields),
            default=0,
        )
        evaluation = evaluate_eligibility(
            EligibilityContext(
                screening_data=state["screening_data"],
                service_area_supported=state["service_area_supported"],
                repeated_abuse_after_warning=state["abuse_count"] >= 2,
                has_unresolved_ambiguity=bool(turn_fields),
                ambiguity_retry_count=retry_count,
                ambiguity_retry_limit=retry_limit,
            )
        )
        completion_missing = missing_required_fields(
            state["screening_data"],
            state["service_area_supported"],
        )
        route_by_status = {
            ScreeningStatus.QUALIFIED: GraphRoute.QUALIFIED,
            ScreeningStatus.DISQUALIFIED: GraphRoute.DISQUALIFIED,
            ScreeningStatus.NEEDS_REVIEW: GraphRoute.NEEDS_REVIEW,
        }
        route = route_by_status.get(
            evaluation.status,
            GraphRoute.ASK_NEXT_QUESTION,
        )
        if interpretation is not None and (
            interpretation.intent
            in {CandidateIntent.JOB_QUESTION, CandidateIntent.OFF_TOPIC}
            or state["abuse_count"] == 1
        ):
            route = GraphRoute.ASK_NEXT_QUESTION
            evaluation.status = ScreeningStatus.IN_PROGRESS
        missing = completion_missing
        stage = ScreeningStage.COMPLETE
        if route is GraphRoute.ASK_NEXT_QUESTION:
            current_clarification = next(iter(turn_fields), None)
            stage = FIELD_TO_STAGE.get(
                current_clarification,
                _stage_for_missing(missing),
            )
        return {
            "route": route,
            "status": evaluation.status,
            "stage": stage,
            "missing_fields": missing,
            "disqualification_reason": evaluation.disqualification_reason,
        }

    async def compose_response(state: ScreeningGraphState) -> dict[str, object]:
        language = state["screening_data"].language
        interpretation = state["interpretation"]
        if language is None and interpretation is not None:
            language = interpretation.detected_language
        text = _compose_candidate_response(state, language)
        return {"response_text": text}

    async def generate_summary(state: ScreeningGraphState) -> dict[str, object]:
        fallback = _deterministic_fallback_summary(state)
        if state["route"] is GraphRoute.DATA_DELETION:
            return {"final_summary": fallback}
        started = perf_counter()
        try:
            result = await provider.generate_summary(
                state["screening_data"],
                state["status"],
                state["disqualification_reason"],
            )
        except ProviderUnavailableError as error:
            latency = (state["provider_latency_ms"] or 0) + round(
                (perf_counter() - started) * 1000
            )
            return {
                "final_summary": fallback,
                "provider_error_code": error.code,
                "provider_latency_ms": latency,
            }
        latency = (state["provider_latency_ms"] or 0) + result.latency_ms
        return {
            "final_summary": result.value.summary,
            "provider_name": result.provider,
            "provider_model": result.model,
            "provider_latency_ms": latency,
        }

    graph = StateGraph(ScreeningGraphState)
    graph.add_node("interpret_message", interpret_message)
    graph.add_node("validate_and_merge", validate_and_merge)
    graph.add_node("determine_next_action", determine_next_action)
    graph.add_node("compose_response", compose_response)
    graph.add_node("generate_summary", generate_summary)
    graph.add_edge(START, "interpret_message")
    graph.add_edge("interpret_message", "validate_and_merge")
    graph.add_edge("validate_and_merge", "determine_next_action")
    graph.add_conditional_edges(
        "determine_next_action",
        lambda state: state["route"].value,
        {route.value: "compose_response" for route in GraphRoute},
    )
    graph.add_conditional_edges(
        "compose_response",
        lambda state: (
            "done"
            if state["route"] is GraphRoute.ASK_NEXT_QUESTION
            else "terminal"
        ),
        {"done": END, "terminal": "generate_summary"},
    )
    graph.add_edge("generate_summary", END)
    return graph.compile()


def _question_for_stage(stage: ScreeningStage, language: object) -> str:
    """Return one deterministic primary question in the selected language."""

    spanish = str(language) == "es"
    questions = {
        ScreeningStage.CONSENT: (
            "¿Te parece bien continuar?"
            if spanish
            else "Is it okay to continue?"
        ),
        ScreeningStage.LANGUAGE: (
            "¿Prefieres continuar en español o en inglés?"
            if spanish
            else "Would you prefer to continue in Spanish or English?"
        ),
        ScreeningStage.FULL_NAME: (
            "¿Cuál es tu nombre completo?"
            if spanish
            else "What is your full name?"
        ),
        ScreeningStage.DRIVER_LICENSE: (
            "¿Tienes un permiso de conducir vigente?"
            if spanish
            else "Do you have a valid driver's license?"
        ),
        ScreeningStage.SERVICE_AREA: (
            "¿En qué ciudad y zona trabajarías?"
            if spanish
            else "Which city and zone would you work in?"
        ),
        ScreeningStage.AVAILABILITY: (
            "¿Tienes disponibilidad completa, parcial o de fines de semana?"
            if spanish
            else "Are you available full-time, part-time, or weekends?"
        ),
        ScreeningStage.PREFERRED_SCHEDULE: (
            "¿Qué horarios prefieres: mañana, tarde, noche o flexible?"
            if spanish
            else (
                "Which schedules do you prefer: morning, afternoon, evening, "
                "or flexible?"
            )
        ),
        ScreeningStage.DELIVERY_EXPERIENCE: (
            "¿Cuántos años de reparto tienes y con qué plataformas?"
            if spanish
            else (
                "How many years of delivery experience do you have, and with "
                "which platforms?"
            )
        ),
        ScreeningStage.START_DATE: (
            "¿En qué fecha futura concreta podrías empezar?"
            if spanish
            else "What specific future date could you start?"
        ),
        ScreeningStage.REVIEW: (
            "¿Puedes confirmar la información pendiente?"
            if spanish
            else "Can you confirm the remaining information?"
        ),
        ScreeningStage.COMPLETE: "",
    }
    return questions[stage]


def _location_question(state: ScreeningGraphState, spanish: bool) -> str:
    """Ask only for the unresolved deterministic location component."""

    location = state["pending_data"].get("location")
    if not isinstance(location, dict):
        return (
            "¿En qué ciudad y zona trabajarías?"
            if spanish
            else "Which city and zone would you work in?"
        )
    status = location.get("status")
    city = location.get("city")
    zone = location.get("zone")
    if status == "suggestion":
        return (
            f"¿Te refieres a {city}, zona {zone}?"
            if spanish
            else f"Do you mean {city}, {zone} zone?"
        )
    missing = set(location.get("missing_components", []))
    if missing == {"country"}:
        return (
            "¿En qué país está esa ciudad y zona?"
            if spanish
            else "Which country is that city and zone in?"
        )
    if missing == {"zone"}:
        return (
            f"¿En qué zona de {city} trabajarías?"
            if spanish
            else f"Which zone of {city} would you work in?"
        )
    if missing == {"city"}:
        return (
            f"¿En qué ciudad está la zona {zone}?"
            if spanish
            else f"Which city is the {zone} zone in?"
        )
    if status == "unknown":
        shown = location.get("raw") or ", ".join(
            str(part)
            for part in (location.get("city"), location.get("zone"))
            if part
        )
        return (
            f"No encuentro «{shown}» en las áreas configuradas. "
            "¿Confirmas esa ubicación?"
            if spanish
            else (
                f"I can't find “{shown}” in the configured areas. "
                "Do you confirm that location?"
            )
        )
    return (
        "¿En qué ciudad y zona trabajarías?"
        if spanish
        else "Which city and zone would you work in?"
    )


def _compose_candidate_response(
    state: ScreeningGraphState,
    language: object,
) -> str:
    """Compose a concise response constrained by the deterministic route."""

    spanish = str(language) == "es"
    if state["provider_error_code"] is not None:
        return (
            "No pude procesar tu respuesta ahora. Inténtalo de nuevo en un momento."
            if spanish
            else "I couldn't process your answer just now. Please try again shortly."
        )
    route = state["route"]
    if route is GraphRoute.DATA_DELETION:
        return (
            "He registrado tu solicitud de eliminación para revisión."
            if spanish
            else "I recorded your deletion request for review."
        )
    if route is GraphRoute.STOPPED:
        return (
            "He detenido el proceso. Puedes contactar con selección si deseas "
            "retomarlo."
            if spanish
            else (
                "I stopped the process. You can contact recruiting if you wish "
                "to resume."
            )
        )
    if route is GraphRoute.QUALIFIED:
        name = state["screening_data"].full_name or ""
        first_name = name.split()[0] if name.split() else ""
        return (
            f"Gracias, {first_name}. Has completado el screening inicial y cumples "
            "los requisitos básicos configurados para el puesto. El equipo de "
            "selección de Grupo Sazón revisará tu candidatura y se pondrá en "
            "contacto contigo para explicarte los siguientes pasos."
            if spanish
            else (
                f"Thank you, {first_name}. You have completed the initial screening "
                "and meet the configured basic requirements for the role. Grupo "
                "Sazón's recruitment team will review your application and contact "
                "you with the next steps."
            )
        )
    if route is GraphRoute.NEEDS_REVIEW:
        return (
            "Gracias. Selección revisará la información que no pudimos confirmar."
            if spanish
            else (
                "Thank you. Recruiting will review the information we could not "
                "confirm."
            )
        )
    if route is GraphRoute.DISQUALIFIED:
        reason = state["disqualification_reason"]
        if reason is DisqualificationReason.NO_DRIVER_LICENSE:
            return (
                "Gracias por tu tiempo. Este puesto requiere permiso de conducir."
                if spanish
                else "Thank you for your time. This role requires a driver's license."
            )
        if reason is DisqualificationReason.OUTSIDE_SERVICE_AREA:
            return (
                "Gracias por tu tiempo. La zona confirmada no está cubierta "
                "actualmente."
                if spanish
                else (
                    "Thank you for your time. The confirmed area is not currently "
                    "covered."
                )
            )
        return (
            "La conversación se ha cerrado tras el aviso previo."
            if spanish
            else "The conversation has been closed after the previous warning."
        )

    question = (
        _location_question(state, spanish)
        if state["stage"] is ScreeningStage.SERVICE_AREA
        else _question_for_stage(state["stage"], language)
    )
    interpretation = state["interpretation"]
    if state["abuse_count"] == 1:
        warning = (
            "Mantengamos una conversación respetuosa, por favor."
            if spanish
            else "Please keep the conversation respectful."
        )
        return f"{warning} {question}".strip()
    if (
        interpretation is not None
        and interpretation.intent is CandidateIntent.JOB_QUESTION
    ):
        handoff = (
            "Selección podrá confirmar ese detalle."
            if spanish
            else "Recruiting can confirm that detail."
        )
        return f"{handoff} {question}".strip()
    if (
        interpretation is not None
        and interpretation.intent is CandidateIntent.OFF_TOPIC
    ):
        prefix = (
            "Volvamos a la evaluación."
            if spanish
            else "Let's return to the screening."
        )
        return f"{prefix} {question}".strip()
    if "start_date" in state["turn_clarification_fields"]:
        prefix = (
            "Necesito una fecha futura explícita."
            if spanish
            else "I need an explicit future date."
        )
        return f"{prefix} {question}".strip()
    if "service_area" in state["turn_clarification_fields"]:
        return question
    if state["turn_clarification_fields"]:
        prefix = (
            "No pude confirmar esa respuesta."
            if spanish
            else "I couldn't confirm that answer."
        )
        return f"{prefix} {question}".strip()
    if (
        state["stage"] is ScreeningStage.DRIVER_LICENSE
        and "full_name" in state["turn_resolved_fields"]
    ):
        name = state["screening_data"].full_name or ""
        first_name = name.split()[0] if name.split() else ""
        return (
            f"Gracias, {first_name}. ¿Tienes un permiso de conducir vigente?"
            if spanish
            else f"Thank you, {first_name}. Do you have a valid driver's license?"
        )
    if state["turn_resolved_fields"]:
        acknowledgement = "Gracias." if spanish else "Thank you."
        return f"{acknowledgement} {question}".strip()
    return question


def to_workflow_result(state: ScreeningGraphState) -> WorkflowResult:
    """Convert completed transient state into a persistence-ready value."""

    return WorkflowResult(
        screening_data=state["screening_data"].model_dump(mode="json"),
        pending_data=state["pending_data"],
        clarification_counts=state["clarification_counts"],
        abuse_count=state["abuse_count"],
        consent_granted=state["consent_granted"],
        service_area_supported=state["service_area_supported"],
        status=state["status"],
        stage=state["stage"],
        route=state["route"],
        missing_fields=state["missing_fields"],
        disqualification_reason=state["disqualification_reason"],
        response_text=state["response_text"],
        final_summary=state["final_summary"],
        llm_provider=state["provider_name"],
        llm_model=state["provider_model"],
        llm_latency_ms=state["provider_latency_ms"],
        recoverable_error_code=state["provider_error_code"],
        debug_explanation=state["debug_explanation"],
    )
