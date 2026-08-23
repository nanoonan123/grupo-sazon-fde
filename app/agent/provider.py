"""LLM provider abstraction and direct OpenAI Responses implementation."""

import asyncio
import json
from collections import deque
from collections.abc import Sequence
from time import perf_counter
from typing import Protocol

from openai import (
    APIConnectionError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    OpenAIError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_exponential

from app.agent.models import (
    MessageInterpretation,
    ProviderMessage,
    ProviderResult,
    SummaryOutput,
)
from app.domain.models import (
    DisqualificationReason,
    Language,
    ScreeningData,
    ScreeningStatus,
)

INTERPRETATION_INSTRUCTIONS = """
Interpret one candidate-screening message into the supplied schema.
Propose facts only; never decide qualification, status, stage, or the next question.
Use null for fields the candidate did not provide. Preserve multiple availability,
schedule, and delivery-platform values. Zero delivery years is valid. Mark unclear,
invalid, or contradictory fields for clarification rather than guessing.

Language detection is observational. Set explicit_language_switch only when the
candidate clearly asks to switch Spanish/English or explicitly selects one. A
complete sentence may be detected in the other language, but never infer a switch
from a name, location, slang, yes/no, or another isolated word.

Explicitly requesting a language is a language switch, not voice. For example,
"please speak in English", "háblame en inglés", and "can we continue in Spanish?"
set explicit_language_switch and retain screening_answer intent. Use voice_switch
only for an explicit voice-channel request such as "podemos hablar en vez de
escribir?", "quiero continuar por voz", or "can I use the microphone?".

The opening asks for the candidate's full name as the opt-in action. Set consent true
when the candidate supplies a name to continue, and false for an explicit refusal.
Full-name completion, including any pending surname, is determined by backend
validation. A response may contain consent and screening facts in the same message;
extract both. Set location_suggestion_confirmed only when the
candidate clearly accepts or rejects the pending canonical location suggestion in
the supplied context.

For locations, extract city and zone when stated; country is optional. Preserve the
candidate's complete location wording in location_raw. Set
confirmed_outside_service_area only when the candidate clearly confirms the
extracted location; never decide whether it is supported. For dates, never map
"yesterday" to immediate availability. Flag relative dates, propose their explicit
calendar date using the supplied current UTC date, and leave confirmation to code.

Availability and schedule are separate facts. Examples:
- "cuando sea", "me da igual el horario", "a cualquier hora", "any time works",
  "I do not mind the schedule", and "at any hour" mean preferred_schedule is
  ["flexible"]. They do not establish full-time or part-time availability.
- "puedo cualquier día", "todos los días", "I can work any day", and "every day"
  establish availability including ["weekends"], but do not establish full-time.
  For those expressions set availability_full_time_confirmation_required true so
  deterministic code can ask whether full-time is available.
- When the supplied context says full-time confirmation is pending, an affirmative
  answer proposes ["full_time"] and a negative/part-time answer proposes
  ["part_time"].

For multiple locations, preserve every option in location_raw and mark service_area
for clarification rather than choosing one. For example, "Madrid por Sanse o por el
centro" and "Madrid around Sanse or the city centre" are ambiguous; Sanse means San
Sebastián de los Reyes, while "el centro" in that phrase means Madrid Centro. The
configured catalogue, not the model, decides whether either location is supported.

Use voice_switch for explicit voice requests, including "¿Podemos hablar?",
"Prefiero hacerlo por voz", "Can we speak instead?", and "I would rather use
voice". A single-token name is incomplete unless the candidate explicitly confirms
they legally use one name; set single_name_confirmed only for that confirmation.

Never use protected characteristics as screening information.
""".strip()

SUMMARY_INSTRUCTIONS = """
Write one short factual recruiter summary from validated screening data and its
deterministic outcome. Do not add facts, recommendations, protected-characteristic
analysis, hidden reasoning, or new qualification criteria.
""".strip()


class ProviderUnavailableError(RuntimeError):
    """Normalized provider failure safe for persistence and API recovery."""

    def __init__(self, code: str, *, recoverable: bool = True) -> None:
        super().__init__(code)
        self.code = code
        self.recoverable = recoverable


class ScreeningLLMProvider(Protocol):
    """Boundary for structured interpretation and terminal summarization."""

    @property
    def name(self) -> str:
        """Return the persisted provider identifier."""

    @property
    def model(self) -> str:
        """Return the persisted model identifier."""

    async def interpret(
        self,
        history: Sequence[ProviderMessage],
        screening_data: ScreeningData,
        selected_language: Language | None,
        pending_data: dict[str, object],
        current_date: str,
    ) -> ProviderResult[MessageInterpretation]:
        """Return schema-constrained proposed updates for one user turn."""

    async def generate_summary(
        self,
        screening_data: ScreeningData,
        status: ScreeningStatus,
        reason: DisqualificationReason | None,
    ) -> ProviderResult[SummaryOutput]:
        """Return a short recruiter summary for a terminal outcome."""


class OpenAIScreeningProvider:
    """Direct AsyncOpenAI Responses API provider with bounded retries."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        timeout_seconds: float,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client_instance: AsyncOpenAI | None = None

    @property
    def model(self) -> str:
        return self._model

    def _client(self) -> AsyncOpenAI:
        """Create the SDK client lazily so startup never requires an API key."""

        if not self._api_key:
            raise ProviderUnavailableError(
                "missing_api_key",
                recoverable=False,
            )
        if self._client_instance is None:
            self._client_instance = AsyncOpenAI(
                api_key=self._api_key,
                max_retries=0,
                timeout=self._timeout_seconds,
            )
        return self._client_instance

    async def _parse[ParsedT: BaseModel](
        self,
        *,
        instructions: str,
        input_messages: list[dict[str, str]],
        text_format: type[ParsedT],
    ) -> ProviderResult[ParsedT]:
        """Call Responses parsing with two bounded transient retries."""

        started = perf_counter()
        try:
            response = None
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(
                    (TimeoutError, APIConnectionError, RateLimitError)
                ),
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.2, min=0.2, max=1.0),
                reraise=True,
            ):
                with attempt:
                    response = await asyncio.wait_for(
                        self._client().responses.parse(
                            model=self.model,
                            instructions=instructions,
                            input=input_messages,
                            text_format=text_format,
                            store=False,
                        ),
                        timeout=self._timeout_seconds,
                    )
            if response is None or response.output_parsed is None:
                raise ProviderUnavailableError("invalid_structured_output")
        except ProviderUnavailableError:
            raise
        except AuthenticationError as error:
            raise ProviderUnavailableError(
                "authentication_error",
                recoverable=False,
            ) from error
        except BadRequestError as error:
            raise ProviderUnavailableError(
                "invalid_request",
                recoverable=False,
            ) from error
        except RateLimitError as error:
            raise ProviderUnavailableError("rate_limit") from error
        except (TimeoutError, APIConnectionError) as error:
            raise ProviderUnavailableError("llm_timeout") from error
        except ValidationError as error:
            raise ProviderUnavailableError("invalid_structured_output") from error
        except OpenAIError as error:
            raise ProviderUnavailableError("provider_unavailable") from error

        latency_ms = round((perf_counter() - started) * 1000)
        return ProviderResult(
            value=response.output_parsed,
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
        )

    async def interpret(
        self,
        history: Sequence[ProviderMessage],
        screening_data: ScreeningData,
        selected_language: Language | None,
        pending_data: dict[str, object],
        current_date: str,
    ) -> ProviderResult[MessageInterpretation]:
        state_context = json.dumps(
            {
                "authoritative_screening_data": screening_data.model_dump(mode="json"),
                "selected_language": selected_language,
                "pending_confirmation_data": pending_data,
                "current_utc_date": current_date,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        instructions = f"{INTERPRETATION_INSTRUCTIONS}\n\nContext: {state_context}"
        input_messages = [message.model_dump() for message in history]
        return await self._parse(
            instructions=instructions,
            input_messages=input_messages,
            text_format=MessageInterpretation,
        )

    async def generate_summary(
        self,
        screening_data: ScreeningData,
        status: ScreeningStatus,
        reason: DisqualificationReason | None,
    ) -> ProviderResult[SummaryOutput]:
        summary_input = json.dumps(
            {
                "screening_data": screening_data.model_dump(mode="json"),
                "status": status,
                "reason": reason,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return await self._parse(
            instructions=SUMMARY_INSTRUCTIONS,
            input_messages=[{"role": "user", "content": summary_input}],
            text_format=SummaryOutput,
        )


class FakeScreeningProvider:
    """Scripted provider used by tests without external API calls."""

    name = "fake"
    model = "fake-screening"

    def __init__(
        self,
        interpretations: Sequence[MessageInterpretation | Exception],
        summaries: Sequence[SummaryOutput | Exception] = (),
    ) -> None:
        self._interpretations = deque(interpretations)
        self._summaries = deque(summaries)
        self.interpret_calls = 0
        self.summary_calls = 0

    async def interpret(
        self,
        history: Sequence[ProviderMessage],
        screening_data: ScreeningData,
        selected_language: Language | None,
        pending_data: dict[str, object],
        current_date: str,
    ) -> ProviderResult[MessageInterpretation]:
        del history, screening_data, selected_language, pending_data, current_date
        self.interpret_calls += 1
        if not self._interpretations:
            raise AssertionError("No scripted fake interpretation remains")
        value = self._interpretations.popleft()
        if isinstance(value, Exception):
            raise value
        return ProviderResult(
            value=value,
            provider=self.name,
            model=self.model,
            latency_ms=0,
        )

    async def generate_summary(
        self,
        screening_data: ScreeningData,
        status: ScreeningStatus,
        reason: DisqualificationReason | None,
    ) -> ProviderResult[SummaryOutput]:
        del screening_data, status, reason
        self.summary_calls += 1
        value: SummaryOutput | Exception
        if self._summaries:
            value = self._summaries.popleft()
        else:
            value = SummaryOutput(summary="Fake terminal screening summary.")
        if isinstance(value, Exception):
            raise value
        return ProviderResult(
            value=value,
            provider=self.name,
            model=self.model,
            latency_ms=0,
        )
