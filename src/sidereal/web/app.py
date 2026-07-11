"""FastAPI shell over the existing chart, transit, library, and DB code."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, time
import ipaddress
import math
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..chart import compute
from ..comparison import build_comparison
from ..config import ChartConfig
from ..ephemeris import SwissEphemeris
from ..interpret.audit import report_interpretation_ids
from ..interpret.compose import compose_report
from ..interpret.store import InterpretationStore, InterpretationStoreError
from ..interpret.transit import calculate_transit_report
from ..library import list_charts, load_chart, save_chart
from ..types import MomentInput


@dataclass(frozen=True, slots=True)
class WebSettings:
    """Machine-local paths and calculation defaults for one web app."""

    db_path: Path
    charts_dir: Path
    boundary_path: Path | None = None
    ephe_path: Path | None = None
    require_swiss_ephemeris: bool = False
    bind_host: str = "127.0.0.1"
    allow_lan: bool = False
    trusted_hosts: tuple[str, ...] = ()


class HostGuardMiddleware:
    """Reject untrusted Host headers, including DNS-rebinding origins."""

    def __init__(
        self,
        app: Any,
        *,
        allowed_hosts: tuple[str, ...],
        allow_ip_hosts: bool,
    ) -> None:
        self.app = app
        self.allowed_hosts = frozenset(allowed_hosts)
        self.allow_ip_hosts = allow_ip_hosts

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            raw_host = next(
                (
                    value.decode("latin-1")
                    for key, value in scope.get("headers", ())
                    if key.lower() == b"host"
                ),
                "",
            )
            host = _normalize_host(raw_host)
            if host is None or not self._is_allowed(host):
                response = JSONResponse(
                    status_code=400,
                    content={"detail": "Untrusted Host header"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def _is_allowed(self, host: str) -> bool:
        if host in self.allowed_hosts:
            return True
        if not self.allow_ip_hosts:
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return False
        return True


def create_app(
    *,
    db_path: Path | str = Path("data/sidereal.db"),
    charts_dir: Path | str = Path("charts"),
    boundary_path: Path | str | None = None,
    ephe_path: Path | str | None = None,
    require_swiss_ephemeris: bool = False,
    bind_host: str = "127.0.0.1",
    allow_lan: bool = False,
    trusted_hosts: tuple[str, ...] = (),
) -> FastAPI:
    """Create a same-origin local API and static UI application."""

    normalized_bind = _required_host(bind_host, "bind_host")
    if not isinstance(allow_lan, bool):
        raise ValueError("allow_lan must be a boolean")
    if not _is_loopback_host(normalized_bind) and not allow_lan:
        raise ValueError("a non-loopback bind_host requires allow_lan=True")
    normalized_trusted = tuple(
        _required_host(value, "trusted_hosts") for value in trusted_hosts
    )
    allowed_hosts = tuple(
        dict.fromkeys(
            (
                "127.0.0.1",
                "::1",
                "localhost",
                "testserver",
                normalized_bind,
                *normalized_trusted,
            )
        )
    )
    settings = WebSettings(
        db_path=Path(db_path).expanduser(),
        charts_dir=Path(charts_dir).expanduser(),
        boundary_path=(
            Path(boundary_path).expanduser() if boundary_path is not None else None
        ),
        ephe_path=Path(ephe_path).expanduser() if ephe_path is not None else None,
        require_swiss_ephemeris=require_swiss_ephemeris,
        bind_host=normalized_bind,
        allow_lan=allow_lan,
        trusted_hosts=normalized_trusted,
    )
    static_dir = Path(__file__).with_name("static")
    app = FastAPI(
        title="Sidereal local desk",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.sidereal_settings = settings
    app.add_middleware(
        HostGuardMiddleware,
        allowed_hosts=allowed_hosts,
        allow_ip_hosts=allow_lan,
    )

    @app.exception_handler(InterpretationStoreError)
    async def store_error_handler(_request: Any, exc: InterpretationStoreError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def not_found_handler(_request: Any, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Any, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        provider = SwissEphemeris(
            ephe_path=settings.ephe_path,
            require_swiss_ephemeris=settings.require_swiss_ephemeris,
        )
        result: dict[str, Any] = {
            "status": "ok",
            "sidereal_version": __version__,
            "swe_version": provider.swe_version,
            "pyswisseph_version": provider.pyswisseph_version,
            "ephemeris_backend": None,
            "db_available": settings.db_path.is_file(),
            "saved_charts": len(list_charts(settings.charts_dir)),
        }
        try:
            batch = provider.calculate_positions(2451545.0)
        except Exception as exc:  # health remains inspectable when strict files are absent
            result.update(status="degraded", ephemeris_error=str(exc))
        else:
            result["ephemeris_backend"] = batch.backend
            result["warnings"] = list(batch.warnings)
        return result

    @app.post("/api/chart")
    def chart_report(payload: dict[str, Any]) -> dict[str, Any]:
        moment = _moment_from_payload(_moment_payload(payload), name="moment")
        options = _options(payload)
        config = _chart_config(settings, options, include_houses=True)
        chart = compute(moment, config)
        comparison = (
            build_comparison(chart, ("midpoint_v1", "tropical"))
            if _boolean(options, "compare_tropical", False)
            else None
        )
        with _optional_store(settings) as store:
            return compose_report(chart, store, comparison=comparison).to_dict()

    @app.get("/api/charts")
    def charts_index() -> dict[str, Any]:
        return {
            "charts": [
                {
                    "id": record.id,
                    "label": record.label,
                    "local_datetime": record.local_datetime,
                    "tz": record.tz,
                    "systems": list(record.systems),
                    "last_report_path": record.last_report_path,
                }
                for record in list_charts(settings.charts_dir)
            ]
        }

    @app.get("/api/charts/{chart_id}")
    def chart_show(chart_id: str) -> dict[str, Any]:
        return load_chart(chart_id, settings.charts_dir).to_dict()

    @app.post("/api/charts")
    def chart_save(payload: dict[str, Any]) -> dict[str, Any]:
        moment = _moment_from_payload(_moment_payload(payload), name="moment")
        if not moment.label.strip():
            raise ValueError("moment.label is required when saving a chart")
        options = _options(payload)
        config = _chart_config(settings, options, include_houses=True)
        chart = compute(moment, config)
        systems = (
            ("midpoint_v1", "tropical")
            if _boolean(options, "compare_tropical", False)
            else ("midpoint_v1",)
        )
        return save_chart(
            chart,
            config,
            charts_dir=settings.charts_dir,
            systems=systems,
        ).to_dict()

    @app.post("/api/charts/{chart_id}/interpret")
    def chart_interpret(chart_id: str) -> dict[str, Any]:
        record = load_chart(chart_id, settings.charts_dir)
        chart = record.chart_object()
        comparison = (
            build_comparison(chart, record.systems)
            if "tropical" in record.systems
            else None
        )
        with _optional_store(settings) as store:
            return compose_report(chart, store, comparison=comparison).to_dict()

    @app.post("/api/transit")
    def transit_report(payload: dict[str, Any]) -> dict[str, Any]:
        options = _options(payload)
        natal_id_value = payload.get("natal_id")
        inline_value = payload.get("natal")
        if natal_id_value is not None and inline_value is not None:
            raise ValueError("provide exactly one of natal_id or natal")

        natal_id: str | None = None
        natal_source = "inline"
        if natal_id_value is not None:
            natal_id = _required_string(natal_id_value, "natal_id")
            record = load_chart(natal_id, settings.charts_dir)
            natal = record.chart_object()
            base_config = record.chart_config()
            natal_id = record.id
            natal_source = "saved"
        elif inline_value is not None:
            inline = _mapping(inline_value, "natal")
            base_config = _chart_config(settings, options, include_houses=True)
            natal = compute(_moment_from_payload(inline, name="natal"), base_config)
        else:
            raise ValueError("provide exactly one of natal_id or natal")

        transit_payload = _mapping(payload.get("transit"), "transit")
        transit_moment = _moment_from_payload(
            transit_payload,
            name="transit",
            require_time=True,
        )
        transit_config = _chart_config(
            settings,
            options,
            include_houses=transit_moment.lat is not None,
            base=base_config,
        )
        transit_config = replace(transit_config, include_patterns=False)
        with _optional_store(settings) as store:
            return calculate_transit_report(
                natal,
                transit_moment,
                transit_config,
                store,
                natal_source=natal_source,
                natal_id=natal_id,
            ).to_dict()

    @app.get("/api/db/gaps")
    def database_gaps(chart_id: str | None = Query(default=None)) -> dict[str, Any]:
        with _required_store(settings) as store:
            if chart_id is None:
                return store.audit().to_dict()
            record = load_chart(chart_id, settings.charts_dir)
            report = compose_report(record.chart_object(), store)
            return store.audit(report_interpretation_ids(report.to_dict())).to_dict()

    @app.get("/api/db/entry/{entry_id}")
    def database_entry(entry_id: str) -> dict[str, Any]:
        with _required_store(settings) as store:
            entry = store.get(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Interpretation key not found: {entry_id}")
        return entry.to_dict()

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return app


def _moment_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = payload.get("moment")
    return payload if nested is None else _mapping(nested, "moment")


def _moment_from_payload(
    payload: Mapping[str, Any],
    *,
    name: str,
    require_time: bool = False,
) -> MomentInput:
    raw_date = _required_string(payload.get("date"), f"{name}.date")
    try:
        local_date = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise ValueError(f"{name}.date must use YYYY-MM-DD") from exc

    raw_time = payload.get("time")
    local_time: time | None
    if raw_time in (None, ""):
        if require_time:
            raise ValueError(f"{name}.time is required")
        local_time = None
    else:
        try:
            local_time = time.fromisoformat(_required_string(raw_time, f"{name}.time"))
        except ValueError as exc:
            raise ValueError(f"{name}.time must use HH:MM or HH:MM:SS") from exc
        if local_time.tzinfo is not None:
            raise ValueError(f"{name}.time must not include a UTC offset; use tz")

    tz = _required_string(payload.get("tz"), f"{name}.tz")
    lat = _optional_float(payload.get("lat"), f"{name}.lat")
    lon = _optional_float(payload.get("lon"), f"{name}.lon")
    _validate_location(lat, lon, name=name)
    fold = payload.get("fold")
    if isinstance(fold, bool) or fold not in (None, 0, 1):
        raise ValueError(f"{name}.fold must be 0, 1, or null")
    if fold is not None and local_time is None:
        raise ValueError(f"{name}.fold requires time")
    label_value = payload.get("label", "")
    if not isinstance(label_value, str):
        raise ValueError(f"{name}.label must be a string")
    return MomentInput(local_date, local_time, tz, lat, lon, label_value, fold)


def _chart_config(
    settings: WebSettings,
    options: Mapping[str, Any],
    *,
    include_houses: bool,
    base: ChartConfig | None = None,
) -> ChartConfig:
    active = base or ChartConfig()
    return replace(
        active,
        boundary_path=(
            settings.boundary_path
            if settings.boundary_path is not None
            else active.boundary_path
        ),
        ephe_path=(
            settings.ephe_path if settings.ephe_path is not None else active.ephe_path
        ),
        require_swiss_ephemeris=(
            settings.require_swiss_ephemeris
            or active.require_swiss_ephemeris
            or _boolean(options, "require_swiss_ephemeris", False)
        ),
        include_houses=(
            include_houses and _boolean(options, "include_houses", True)
        ),
    )


def _options(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("options", {})
    return _mapping(value, "options")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_float(value: Any, name: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _validate_location(lat: float | None, lon: float | None, *, name: str) -> None:
    if (lat is None) != (lon is None):
        raise ValueError(f"{name}.lat and {name}.lon must be supplied together")
    if lat is not None and not -90.0 < lat < 90.0:
        raise ValueError(f"{name}.lat must be strictly between -90 and 90 degrees")
    if lon is not None and not -180.0 <= lon <= 180.0:
        raise ValueError(f"{name}.lon must be between -180 and 180 degrees")


def _normalize_host(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or any(character in text for character in "/\\@\x00\r\n"):
        return None
    if text.startswith("["):
        closing = text.find("]")
        if closing < 0:
            return None
        suffix = text[closing + 1 :]
        if suffix and not (suffix.startswith(":") and suffix[1:].isdigit()):
            return None
        host = text[1:closing]
    else:
        host = text
        if text.count(":") == 1:
            candidate, separator, port = text.rpartition(":")
            if separator and port.isdigit():
                host = candidate
    normalized = host.rstrip(".").casefold()
    if not normalized or any(character.isspace() for character in normalized):
        return None
    return normalized


def _required_host(value: Any, name: str) -> str:
    normalized = _normalize_host(value)
    if normalized is None or normalized == "*":
        raise ValueError(f"{name} must be an exact host name or IP address")
    return normalized


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _boolean(options: Mapping[str, Any], key: str, default: bool) -> bool:
    value = options.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"options.{key} must be a boolean")
    return value


@contextmanager
def _optional_store(settings: WebSettings) -> Iterator[InterpretationStore | None]:
    if not settings.db_path.is_file():
        yield None
        return
    with InterpretationStore(settings.db_path) as store:
        yield store


@contextmanager
def _required_store(settings: WebSettings) -> Iterator[InterpretationStore]:
    if not settings.db_path.is_file():
        raise FileNotFoundError(
            f"Interpretation database does not exist: {settings.db_path}"
        )
    with InterpretationStore(settings.db_path) as store:
        yield store


__all__ = ["HostGuardMiddleware", "WebSettings", "create_app"]
