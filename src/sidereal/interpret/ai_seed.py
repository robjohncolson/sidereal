"""Validated, shared interpretation fills through DeepSeek chat completions.

Only canonical interpretation ids and catalog keywords leave the process.  No
natal metadata, user id, chart geometry, or API credential is included in a
prompt or result persisted to SQLite.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from functools import lru_cache
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import queue
import re
from threading import Condition, RLock, Thread
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .schema import (
    PLANETS,
    SIGNS,
    InterpretationEntry,
    aspect_key,
    generate_seed0_entries,
)
from .store import EntryConflictError, InterpretationStore


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_CHAT_PATH = "/chat/completions"
MAX_DEEPSEEK_RESPONSE_BYTES = 1_000_000
SUPPORTED_AI_ENTRY_TYPES = frozenset(("sign", "planet_in_sign", "aspect"))

BANNED_GENERATED_FRAGMENTS = frozenset(
    (
        "you will",
        "you are going to",
        "diagnos",
        "prescrib",
        "cure your",
        "medical advice",
        "financial advice",
        "investment advice",
        "buy this stock",
        "legal advice",
        "legal outcome",
        "lottery",
        "guaranteed",
        "destined to die",
        "will die",
        "death prediction",
        "self-harm",
        "harm yourself",
        "suicide",
        "call 911",
        "emergency services",
        "crisis hotline",
        "treat your",
        "medication",
        "disease",
    )
)

AI_SEED_SYSTEM_PROMPT = """You author shared interpretation-catalog records for Sidereal.
Use the Midpoint 13-sign true-sidereal framework, with Ophiuchus as a first-class sign.
Write symbolic cultural study language only, never personality verdicts or predictions.
Do not make medical, diagnostic, treatment, financial, legal, crisis, death, fate, or guaranteed-outcome claims.
For aspects, distinguish a fixed natal relationship from a moving-to-fixed transit timing lens without forecasting events.
Return only one JSON object with exactly these fields: title (string), summary (string), growth (string), keywords (array of strings).
The summary should be substantive, reflective, and approximately 120-500 characters.
Do not wrap the JSON in Markdown and do not add commentary."""

_GENERATED_FIELDS = frozenset(("title", "summary", "growth", "keywords"))
_LOGGER = logging.getLogger(__name__)


class AISeedError(RuntimeError):
    """Base error for safe AI-seed generation and persistence failures."""


class AISeedConfigurationError(AISeedError):
    """Required server-only DeepSeek configuration is absent or unsafe."""


class AISeedValidationError(AISeedError, ValueError):
    """A target id or generated record failed deterministic validation."""


class DeepSeekRequestError(AISeedError):
    """DeepSeek could not return one usable chat completion."""


@dataclass(frozen=True, slots=True)
class GeneratedSeedContent:
    """Normalized model-authored fields before store metadata is attached."""

    title: str
    summary: str
    growth: str
    keywords: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "growth": self.growth,
            "keywords": list(self.keywords),
        }


@dataclass(frozen=True, slots=True)
class SeedPrompt:
    """An id-only shared-catalog prompt with no personal chart context."""

    entry_id: str
    entry_type: str
    title: str
    keywords: tuple[str, ...]
    system: str
    user: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "entry_type": self.entry_type,
            "title": self.title,
            "keywords": list(self.keywords),
            "messages": [
                {"role": "system", "content": self.system},
                {"role": "user", "content": self.user},
            ],
        }


@dataclass(frozen=True, slots=True)
class AISeedFillResult:
    """Outcome of one requested catalog fill."""

    action: str
    entry: InterpretationEntry

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "entry": self.entry.to_dict()}


@dataclass(frozen=True, slots=True)
class AISeedBatchResult:
    """Bounded deterministic batch outcome for CLI fill-gaps."""

    limit: int
    selected_ids: tuple[str, ...]
    results: tuple[AISeedFillResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "selected_ids": list(self.selected_ids),
            "processed": len(self.results),
            "results": [result.to_dict() for result in self.results],
        }


class DeepSeekTransport(Protocol):
    """Injectable JSON transport so CI never needs network access."""

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        ...


class SeedAuthor(Protocol):
    """Generate and validate model fields for one catalog prompt."""

    def generate(self, prompt: SeedPrompt) -> GeneratedSeedContent:
        ...


class SeedQueue(Protocol):
    """Minimal web lifecycle and enqueue boundary."""

    def start(self) -> None:
        ...

    def enqueue(self, entry_id: str) -> bool:
        ...

    def close(self) -> None:
        ...


class EntryLookup(Protocol):
    def get(self, entry_id: str) -> InterpretationEntry | None:
        ...


def validate_generated_record(
    entry_id: str,
    payload: Mapping[str, Any],
) -> GeneratedSeedContent:
    """Validate the exact model schema and epistemic safety constraints."""

    interpretation_template(entry_id)
    if not isinstance(payload, Mapping):
        raise AISeedValidationError("generated interpretation must be a JSON object")
    fields = frozenset(payload)
    missing = sorted(_GENERATED_FIELDS - fields)
    extra = sorted(fields - _GENERATED_FIELDS)
    if missing:
        raise AISeedValidationError(
            f"generated interpretation is missing field(s): {', '.join(missing)}"
        )
    if extra:
        raise AISeedValidationError(
            f"generated interpretation has unsupported field(s): {', '.join(extra)}"
        )

    title = _generated_text(payload.get("title"), "title", minimum=1, maximum=200)
    summary = _generated_text(
        payload.get("summary"),
        "summary",
        minimum=40,
        maximum=4000,
    )
    growth = _generated_text(
        payload.get("growth"),
        "growth",
        minimum=0,
        maximum=2000,
    )
    raw_keywords = payload.get("keywords")
    if not isinstance(raw_keywords, list):
        raise AISeedValidationError("generated keywords must be an array")
    if not 1 <= len(raw_keywords) <= 12:
        raise AISeedValidationError("generated keywords must contain 1-12 items")
    keywords: list[str] = []
    seen_keywords: set[str] = set()
    for raw_keyword in raw_keywords:
        keyword = _generated_text(
            raw_keyword,
            "keyword",
            minimum=1,
            maximum=80,
        )
        identity = keyword.casefold()
        if identity in seen_keywords:
            raise AISeedValidationError("generated keywords must be unique")
        seen_keywords.add(identity)
        keywords.append(keyword)

    for text in (title, summary, growth, *keywords):
        normalized = re.sub(r"\s+", " ", text.casefold())
        match = next(
            (
                fragment
                for fragment in BANNED_GENERATED_FRAGMENTS
                if fragment in normalized
            ),
            None,
        )
        if match is not None:
            raise AISeedValidationError(
                f"generated interpretation contains banned fragment {match!r}"
            )
    return GeneratedSeedContent(
        title=title,
        summary=summary,
        growth=growth,
        keywords=tuple(keywords),
    )


def interpretation_template(entry_id: str) -> InterpretationEntry:
    """Resolve one strict canonical Q target from the deterministic inventory."""

    if not isinstance(entry_id, str) or not entry_id or entry_id != entry_id.strip():
        raise AISeedValidationError("interpretation id must be a canonical string")
    parts = entry_id.split(":")
    entry_type = parts[0]
    if entry_type == "sign":
        if len(parts) != 2 or parts[1] not in SIGNS:
            raise AISeedValidationError("invalid sign interpretation id")
    elif entry_type == "planet_in_sign":
        if len(parts) != 3 or parts[1] not in PLANETS or parts[2] not in SIGNS:
            raise AISeedValidationError("invalid planet_in_sign interpretation id")
    elif entry_type == "aspect":
        if len(parts) != 4:
            raise AISeedValidationError("invalid aspect interpretation id")
        try:
            canonical = aspect_key(parts[1], parts[2], parts[3])
        except ValueError as exc:
            raise AISeedValidationError(str(exc)) from exc
        if canonical != entry_id:
            raise AISeedValidationError(
                f"aspect interpretation id is not canonical; expected {canonical!r}"
            )
    else:
        raise AISeedValidationError(
            "AI seed targets must be sign, planet_in_sign, or aspect ids"
        )
    template = _supported_templates().get(entry_id)
    if template is None:  # defensive consistency check around the inventory
        raise AISeedValidationError("interpretation id is outside the shared inventory")
    return template


@lru_cache(maxsize=1)
def _supported_templates() -> Mapping[str, InterpretationEntry]:
    return {
        entry.id: entry
        for entry in generate_seed0_entries()
        if entry.type in SUPPORTED_AI_ENTRY_TYPES
    }


def build_seed_prompt(
    entry_id: str,
    *,
    current: InterpretationEntry | None = None,
) -> SeedPrompt:
    """Build a type-specific prompt from an id and catalog keywords only."""

    template = interpretation_template(entry_id)
    if current is not None and current.id != entry_id:
        raise AISeedValidationError("current entry id does not match prompt target")
    keywords = current.keywords if current is not None else template.keywords
    keyword_text = json.dumps(list(keywords), ensure_ascii=False)
    if template.type == "sign":
        assert template.sign is not None
        task = (
            f"Write the shared Midpoint sign entry for {template.sign}. "
            "Treat this sign as a symbolic lens, not a personality label."
        )
    elif template.type == "planet_in_sign":
        assert template.planet is not None and template.sign is not None
        task = (
            f"Write the shared placement entry for {template.planet} in "
            f"{template.sign}. Describe the two symbols in relationship without "
            "claiming that every person with the placement has fixed traits."
        )
    else:
        assert template.body_a is not None and template.body_b is not None
        assert template.aspect_type is not None
        task = (
            f"Write the shared {template.aspect_type} aspect entry between "
            f"{template.body_a} and {template.body_b}. It may be reused for natal, "
            "synastry, or moving-to-natal transit composition; frame timing as a "
            "reflective lens, never an event forecast."
        )
    user = (
        f"Catalog id: {entry_id}\n"
        f"Catalog title: {template.title}\n"
        f"Inventory keywords: {keyword_text}\n"
        f"Task: {task}\n"
        "Return only the required JSON object."
    )
    return SeedPrompt(
        entry_id=entry_id,
        entry_type=template.type,
        title=template.title,
        keywords=tuple(keywords),
        system=AI_SEED_SYSTEM_PROMPT,
        user=user,
    )


def _chat_payload(prompt: SeedPrompt, model: str) -> dict[str, Any]:
    return {
        "model": _validated_model(model),
        "messages": [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0.4,
        "max_tokens": 1200,
        "stream": False,
    }


def dry_run_interpretation(entry_id: str) -> dict[str, Any]:
    """Return the exact key-free request preview without DB or network access."""

    prompt = build_seed_prompt(entry_id)
    model = _model_from_env_without_key()
    base_url = _base_url_from_env()
    return {
        "mode": "dry-run",
        "writes": False,
        "entry_id": entry_id,
        "endpoint": f"{base_url}{DEEPSEEK_CHAT_PATH}",
        "request": _chat_payload(prompt, model),
    }


@dataclass(frozen=True, slots=True)
class DeepSeekConfig:
    """Server-only client configuration; the credential is omitted from repr."""

    api_key: str = field(repr=False)
    model: str = DEFAULT_DEEPSEEK_MODEL
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.api_key, str)
            or not self.api_key
            or any(not 33 <= ord(character) <= 126 for character in self.api_key)
        ):
            raise AISeedConfigurationError(
                "DEEPSEEK_API_KEY must be a non-empty printable ASCII token"
            )
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(float(self.timeout_seconds))
            or float(self.timeout_seconds) <= 0.0
        ):
            raise AISeedConfigurationError("DeepSeek timeout must be positive and finite")
        object.__setattr__(self, "model", _validated_model(self.model))
        object.__setattr__(self, "base_url", _normalize_base_url(self.base_url))
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}{DEEPSEEK_CHAT_PATH}"

    @classmethod
    def from_env(cls) -> DeepSeekConfig:
        raw_key = os.environ.get("DEEPSEEK_API_KEY")
        if raw_key is None or not raw_key.strip():
            raise AISeedConfigurationError(
                "DEEPSEEK_API_KEY is required for ai-seed fill commands"
            )
        return cls(
            api_key=raw_key,
            model=_model_from_env_without_key(),
            base_url=_base_url_from_env(),
        )


class DeepSeekClient:
    """Strict non-streaming chat-completions client with injected transport."""

    def __init__(
        self,
        config: DeepSeekConfig,
        *,
        transport: DeepSeekTransport | None = None,
    ) -> None:
        if not isinstance(config, DeepSeekConfig):
            raise TypeError("config must be a DeepSeekConfig")
        self._config = config
        self._transport = transport or UrllibDeepSeekTransport()

    @classmethod
    def from_env(cls) -> DeepSeekClient:
        return cls(DeepSeekConfig.from_env())

    def generate(self, prompt: SeedPrompt) -> GeneratedSeedContent:
        if not isinstance(prompt, SeedPrompt):
            raise TypeError("prompt must be a SeedPrompt")
        response = self._transport.post_json(
            self._config.endpoint,
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            payload=_chat_payload(prompt, self._config.model),
            timeout_seconds=self._config.timeout_seconds,
        )
        choices = response.get("choices") if isinstance(response, Mapping) else None
        if not isinstance(choices, list) or not choices:
            raise DeepSeekRequestError("DeepSeek returned no completion choice")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise DeepSeekRequestError("DeepSeek returned an invalid completion choice")
        if choice.get("finish_reason") != "stop":
            raise DeepSeekRequestError("DeepSeek completion did not finish cleanly")
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise DeepSeekRequestError("DeepSeek returned no completion message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekRequestError("DeepSeek returned empty completion content")
        try:
            generated = json.loads(content)
        except json.JSONDecodeError as exc:
            raise DeepSeekRequestError("DeepSeek completion was not valid JSON") from exc
        if not isinstance(generated, Mapping):
            raise DeepSeekRequestError("DeepSeek completion JSON must be an object")
        return validate_generated_record(prompt.entry_id, generated)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None


class UrllibDeepSeekTransport:
    """Small stdlib HTTP transport that never follows credentialed redirects."""

    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirectHandler())

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        body = json.dumps(
            dict(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            request = Request(
                url,
                data=body,
                headers=dict(headers),
                method="POST",
            )
            with self._opener.open(request, timeout=timeout_seconds) as response:
                status = int(response.getcode())
                raw = response.read(MAX_DEEPSEEK_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise DeepSeekRequestError(
                f"DeepSeek request failed with HTTP status {exc.code}"
            ) from exc
        except (URLError, TimeoutError, OSError, ValueError, UnicodeError) as exc:
            raise DeepSeekRequestError("DeepSeek request failed") from exc
        if status != 200:
            raise DeepSeekRequestError(
                f"DeepSeek request failed with HTTP status {status}"
            )
        if len(raw) > MAX_DEEPSEEK_RESPONSE_BYTES:
            raise DeepSeekRequestError("DeepSeek response exceeded the size limit")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeepSeekRequestError("DeepSeek returned invalid response JSON") from exc
        if not isinstance(decoded, Mapping):
            raise DeepSeekRequestError("DeepSeek response must be a JSON object")
        return decoded


def fill_interpretation(
    entry_id: str,
    store: InterpretationStore,
    *,
    client: SeedAuthor | None = None,
    today: Callable[[], date] = date.today,
) -> AISeedFillResult:
    """Generate one missing/stub shared entry and atomically persist it."""

    template = interpretation_template(entry_id)
    current = store.get(entry_id)
    if current is not None and current.status in {"ready", "user"}:
        return AISeedFillResult(action="already_ready", entry=current)
    author = client or DeepSeekClient.from_env()
    prompt = build_seed_prompt(entry_id, current=current)
    content = author.generate(prompt)
    # Re-validate injected authors as strictly as real HTTP responses.
    content = validate_generated_record(entry_id, content.to_dict())
    baseline = current or template
    changed_on = today()
    if not isinstance(changed_on, date) or isinstance(changed_on, datetime):
        raise TypeError("today must return a date")
    candidate = replace(
        baseline,
        title=content.title,
        summary=content.summary,
        growth=content.growth,
        keywords=content.keywords,
        source="ai-deepseek",
        license="personal-use",
        status="ready",
        version=baseline.version + 1,
        updated=changed_on.isoformat(),
    )
    try:
        written = store.upsert_entry(candidate, expected=current)
    except EntryConflictError as exc:
        latest = store.get(entry_id)
        if latest is not None and latest.status in {"ready", "user"}:
            return AISeedFillResult(action="race_won_elsewhere", entry=latest)
        raise AISeedError(
            f"interpretation {entry_id!r} changed while its fill was running"
        ) from exc
    return AISeedFillResult(action="filled", entry=written)


def fill_interpretation_gaps(
    store: InterpretationStore,
    *,
    limit: int,
    client: SeedAuthor | None = None,
    today: Callable[[], date] = date.today,
) -> AISeedBatchResult:
    """Fill a bounded deterministic set of supported stub/missing ids."""

    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    audit = store.audit()
    supported = _supported_templates()
    candidates = tuple(
        entry_id
        for entry_id in (*audit.stub_ids, *audit.missing_ids)
        if entry_id in supported
    )
    selected = candidates[:limit]
    if not selected:
        return AISeedBatchResult(limit=limit, selected_ids=(), results=())
    author = client or DeepSeekClient.from_env()
    results = tuple(
        fill_interpretation(
            entry_id,
            store,
            client=author,
            today=today,
        )
        for entry_id in selected
    )
    return AISeedBatchResult(
        limit=limit,
        selected_ids=selected,
        results=results,
    )


class AISeedQueue:
    """Bounded daemon worker with queued-and-in-flight id de-duplication."""

    def __init__(
        self,
        worker: Callable[[str], Any],
        *,
        maxsize: int = 256,
    ) -> None:
        if not callable(worker):
            raise TypeError("worker must be callable")
        if not isinstance(maxsize, int) or isinstance(maxsize, bool) or maxsize <= 0:
            raise ValueError("maxsize must be a positive integer")
        self._worker = worker
        self._jobs: queue.Queue[str] = queue.Queue(maxsize=maxsize)
        self._condition = Condition(RLock())
        self._pending: set[str] = set()
        self._started = False
        self._closed = False
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("AI seed queue is closed")
            if self._started:
                return
            self._started = True
            self._thread = Thread(
                target=self._run,
                name="sidereal-ai-seed",
                daemon=True,
            )
            self._thread.start()

    def enqueue(self, entry_id: str) -> bool:
        try:
            interpretation_template(entry_id)
        except (TypeError, ValueError, AISeedError):
            return False
        with self._condition:
            if not self._started or self._closed or entry_id in self._pending:
                return False
            self._pending.add(entry_id)
            try:
                self._jobs.put_nowait(entry_id)
            except queue.Full:
                self._pending.remove(entry_id)
                return False
            self._condition.notify_all()
            return True

    def wait_until_idle(self, timeout_seconds: float = 5.0) -> bool:
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0.0:
            raise ValueError("timeout_seconds must be finite and non-negative")
        with self._condition:
            return self._condition.wait_for(
                lambda: not self._pending,
                timeout=float(timeout_seconds),
            )

    def close(self) -> None:
        with self._condition:
            self._closed = True
            # Cancel jobs that have not begun. An in-flight request remains
            # bounded by its client timeout, but shutdown never starts another.
            while True:
                try:
                    entry_id = self._jobs.get_nowait()
                except queue.Empty:
                    break
                self._jobs.task_done()
                self._pending.discard(entry_id)
            thread = self._thread
            self._condition.notify_all()
        # Never make application shutdown wait for a model request. The daemon
        # exits after its finite request timeout if one fill is already running.
        if thread is not None:
            thread.join(timeout=0.25)

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._closed and self._jobs.empty():
                    return
            try:
                entry_id = self._jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._worker(entry_id)
            except Exception as exc:  # background failures must never reach HTTP
                _LOGGER.warning(
                    "AI seed fill failed for %s (%s)",
                    entry_id,
                    type(exc).__name__,
                )
            finally:
                self._jobs.task_done()
                with self._condition:
                    self._pending.discard(entry_id)
                    self._condition.notify_all()


class EnqueueingEntryLookup:
    """Sky Listen lookup decorator that schedules gaps without blocking reads."""

    def __init__(self, store: EntryLookup, seed_queue: SeedQueue) -> None:
        self._store = store
        self._queue = seed_queue

    def get(self, entry_id: str) -> InterpretationEntry | None:
        entry = self._store.get(entry_id)
        if entry is None or entry.status == "stub":
            try:
                self._queue.enqueue(entry_id)
            except Exception as exc:  # a hook bug cannot break Listen
                _LOGGER.warning(
                    "AI seed enqueue failed for %s (%s)",
                    entry_id,
                    type(exc).__name__,
                )
        return entry


def ai_seed_queue_from_env(db_path: Path | str) -> AISeedQueue | None:
    """Build an inert-until-started worker when key and SQLite DB exist."""

    raw_key = os.environ.get("DEEPSEEK_API_KEY")
    if raw_key is None or not raw_key.strip():
        return None
    path = Path(db_path).expanduser()
    if not path.is_file():
        return None
    client = DeepSeekClient.from_env()

    def worker(entry_id: str) -> None:
        with InterpretationStore(path) as store:
            fill_interpretation(entry_id, store, client=client)

    return AISeedQueue(worker)


def _generated_text(
    value: Any,
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise AISeedValidationError(f"generated {name} must be a string")
    normalized = value.strip()
    if len(normalized) < minimum:
        raise AISeedValidationError(
            f"generated {name} must contain at least {minimum} characters"
        )
    if len(normalized) > maximum:
        raise AISeedValidationError(
            f"generated {name} must contain at most {maximum} characters"
        )
    return normalized


def _validated_model(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AISeedConfigurationError("DEEPSEEK_MODEL must be non-empty")
    model = value.strip()
    if len(model) > 200 or any(character.isspace() for character in model):
        raise AISeedConfigurationError("DEEPSEEK_MODEL is invalid")
    return model


def _model_from_env_without_key() -> str:
    raw = os.environ.get("DEEPSEEK_MODEL")
    return _validated_model(DEFAULT_DEEPSEEK_MODEL if raw is None else raw)


def _base_url_from_env() -> str:
    raw = os.environ.get("DEEPSEEK_BASE_URL")
    return _normalize_base_url(DEFAULT_DEEPSEEK_BASE_URL if raw is None else raw)


def _normalize_base_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AISeedConfigurationError("DEEPSEEK_BASE_URL must be non-empty")
    base = value.strip().rstrip("/")
    try:
        parsed = urlsplit(base)
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise AISeedConfigurationError("DEEPSEEK_BASE_URL must be a valid URL") from exc
    scheme = parsed.scheme.casefold()
    if (
        hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or scheme not in {"http", "https"}
        or (scheme == "http" and not _is_loopback_host(hostname))
    ):
        raise AISeedConfigurationError(
            "DEEPSEEK_BASE_URL must use HTTPS (or loopback HTTP for tests)"
        )
    return base


def _is_loopback_host(value: str) -> bool:
    if value.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


__all__ = [
    "AI_SEED_SYSTEM_PROMPT",
    "AISeedBatchResult",
    "AISeedConfigurationError",
    "AISeedError",
    "AISeedFillResult",
    "AISeedQueue",
    "AISeedValidationError",
    "BANNED_GENERATED_FRAGMENTS",
    "DEFAULT_DEEPSEEK_BASE_URL",
    "DEFAULT_DEEPSEEK_MODEL",
    "DeepSeekClient",
    "DeepSeekConfig",
    "DeepSeekRequestError",
    "EnqueueingEntryLookup",
    "GeneratedSeedContent",
    "SeedAuthor",
    "SeedPrompt",
    "SeedQueue",
    "ai_seed_queue_from_env",
    "build_seed_prompt",
    "dry_run_interpretation",
    "fill_interpretation",
    "fill_interpretation_gaps",
    "interpretation_template",
    "validate_generated_record",
]
