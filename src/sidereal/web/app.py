"""FastAPI shell over the existing chart, transit, library, and DB code."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, time
import ipaddress
import math
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..auth import (
    AuthenticationError,
    Authenticator,
    authenticator_from_env,
    normalize_user_id,
)
from ..chart import compute
from ..comparison import build_comparison
from ..config import ChartConfig
from ..ephemeris import SwissEphemeris
from ..interpret.audit import report_interpretation_ids
from ..interpret.ai_seed import (
    EnqueueingEntryLookup,
    SeedQueue,
    ai_seed_queue_from_env,
)
from ..interpret.compose import compose_report
from ..interpret.store import InterpretationStore, InterpretationStoreError
from ..interpret.synastry import calculate_synastry_report
from ..interpret.transit import calculate_transit_study
from ..library import (
    AmbiguousChartError,
    ChartLibraryError,
    ChartNotFoundError,
    list_charts,
    load_chart,
    save_chart,
)
from ..natal import NatalStore, NatalStoreError, natal_record_from_payload
from ..personal_sky import PersonalSkyCache, build_personal_skypack, compute_natal_chart
from ..sky_listen import build_sky_listen, build_sky_listen_from_chart
from ..skyday import SkyDayCache, SkyDayCalculationError
from ..skypack import build_skypack
from ..synastry_library import list_synastries, load_synastry, save_synastry_snapshot
from ..transit_library import list_transits, load_transit, save_transit_snapshot
from ..types import MomentInput
from ..wheel import render_svg
from .supabase_natal import natal_store_from_env


_SKY_LISTEN_DEV_ORIGINS = frozenset(
    (
        "http://127.0.0.1:8931",
        "http://localhost:8931",
    )
)
_SKY_DAY_DEFAULT_ORIGINS = frozenset(
    (
        "http://127.0.0.1:8931",
        "http://localhost:8931",
        "https://aim-dojo.vercel.app",
        "https://robjohncolson.github.io",
    )
)


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
        # Public deploy (allow_lan): Railway edge/healthcheck Host names are not loopback IPs.
        if self.allow_ip_hosts and (
            host.endswith(".up.railway.app")
            or host.endswith(".railway.app")
            or host.endswith(".railway.internal")
        ):
            return True
        if not self.allow_ip_hosts:
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return False
        return True


class ScopedCORSMiddleware:
    """Add browser CORS only to the public sky/personal API surface."""

    def __init__(
        self,
        app: Any,
        *,
        allowed_origins: frozenset[str],
        exact_paths: tuple[str, ...],
        path_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.allowed_origins = allowed_origins
        self.exact_paths = frozenset(exact_paths)
        self.path_prefixes = path_prefixes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = str(scope.get("path") or "")
        selected = path in self.exact_paths or any(
            path.startswith(prefix) for prefix in self.path_prefixes
        )
        origin = _header_value(scope, b"origin") if selected else None
        cors_allowed = origin in self.allowed_origins
        private_response = path.startswith("/api/me/") or (
            path == "/api/sky-listen"
            and (
                _header_value(scope, b"authorization") is not None
                or _header_value(scope, b"x-dev-user-id") is not None
            )
        )
        if not cors_allowed and not private_response:
            await self.app(scope, receive, send)
            return

        async def send_with_cors(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", ()))
                if cors_allowed:
                    if not any(
                        key.lower() == b"access-control-allow-origin"
                        for key, _ in headers
                    ):
                        assert origin is not None
                        headers.append(
                            (b"access-control-allow-origin", origin.encode("latin-1"))
                        )
                    headers = _merge_vary_origin(headers)
                if private_response and not any(
                    key.lower() == b"cache-control" for key, _ in headers
                ):
                    headers.append((b"cache-control", b"private, no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cors)


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
    natal_store: NatalStore | None = None,
    authenticator: Authenticator | None = None,
    personal_sky_cache: PersonalSkyCache | None = None,
    ai_seed_queue: SeedQueue | None = None,
    allow_dev_auth: bool | None = None,
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
    sky_day_origins = _sky_day_allowed_origins()
    personal_origins = frozenset((*sky_day_origins, *_SKY_LISTEN_DEV_ORIGINS))
    sky_day_cache = SkyDayCache()
    active_natal_store = (
        natal_store if natal_store is not None else natal_store_from_env()
    )
    active_authenticator = (
        authenticator if authenticator is not None else authenticator_from_env()
    )
    active_ai_seed_queue = (
        ai_seed_queue
        if ai_seed_queue is not None
        else ai_seed_queue_from_env(settings.db_path)
    )
    dev_auth_enabled = (
        os.environ.get("SIDEREAL_DEV_AUTH") == "1"
        if allow_dev_auth is None
        else allow_dev_auth
    )
    if not isinstance(dev_auth_enabled, bool):
        raise ValueError("allow_dev_auth must be a boolean or None")
    if dev_auth_enabled and (allow_lan or not _is_loopback_host(normalized_bind)):
        raise ValueError("development auth is allowed only on a loopback server")

    def personal_pack_builder(
        record: Any,
        *,
        when: Any,
        tz: str,
    ) -> dict[str, Any]:
        return build_personal_skypack(
            record,
            when=when,
            tz=tz,
            boundary_path=settings.boundary_path,
            ephe_path=settings.ephe_path,
            require_swiss_ephemeris=settings.require_swiss_ephemeris,
        )

    active_personal_cache = (
        personal_sky_cache
        if personal_sky_cache is not None
        else PersonalSkyCache(personal_pack_builder)
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
    app.state.sky_day_cache = sky_day_cache
    app.state.natal_store = active_natal_store
    app.state.personal_sky_cache = active_personal_cache
    app.state.ai_seed_queue = active_ai_seed_queue
    app.add_middleware(
        ScopedCORSMiddleware,
        allowed_origins=personal_origins,
        exact_paths=("/api/sky-listen",),
        path_prefixes=("/api/me/",),
    )
    app.add_middleware(
        HostGuardMiddleware,
        allowed_hosts=allowed_hosts,
        allow_ip_hosts=allow_lan,
    )

    if active_ai_seed_queue is not None:
        app.router.add_event_handler("startup", active_ai_seed_queue.start)
        app.router.add_event_handler("shutdown", active_ai_seed_queue.close)

    close_natal_store = getattr(active_natal_store, "close", None)
    if callable(close_natal_store):
        app.router.add_event_handler("shutdown", close_natal_store)

    @app.exception_handler(InterpretationStoreError)
    async def store_error_handler(_request: Any, exc: InterpretationStoreError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def not_found_handler(_request: Any, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Any, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(NatalStoreError)
    async def natal_store_error_handler(
        _request: Any,
        exc: NatalStoreError,
    ) -> JSONResponse:
        # Only pass through short machine codes we generate ourselves.
        raw = str(exc).strip()
        if raw.startswith("Natal backend HTTP ") and len(raw) <= 40:
            detail = raw
        else:
            detail = "Natal storage is temporarily unavailable"
        return JSONResponse(
            status_code=503,
            content={"detail": detail},
        )

    def authenticated_user_id(
        authorization: str | None,
        dev_user_id: str | None,
        *,
        required: bool,
    ) -> str | None:
        if authorization is None:
            if dev_user_id is not None:
                if not dev_auth_enabled:
                    raise _unauthorized()
                try:
                    return normalize_user_id(dev_user_id)
                except AuthenticationError as exc:
                    raise _unauthorized() from exc
            if required:
                raise _unauthorized()
            return None
        try:
            token = _bearer_token(authorization)
            return normalize_user_id(active_authenticator.authenticate(token))
        except AuthenticationError as exc:
            raise _unauthorized() from exc

    def required_personal_user_id(
        authorization: str | None = Header(default=None),
        dev_user_id: str | None = Header(default=None, alias="X-Dev-User-Id"),
    ) -> str:
        user_id = authenticated_user_id(
            authorization,
            dev_user_id,
            required=True,
        )
        assert user_id is not None
        return user_id

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        provider = SwissEphemeris(
            ephe_path=settings.ephe_path,
            require_swiss_ephemeris=settings.require_swiss_ephemeris,
        )
        store_name = type(active_natal_store).__name__
        if store_name == "SupabaseNatalStore":
            natal_backend = "supabase"
        elif store_name == "MemoryNatalStore":
            natal_backend = "memory"
        else:
            natal_backend = "custom"
        auth_name = type(active_authenticator).__name__
        result: dict[str, Any] = {
            "status": "ok",
            "sidereal_version": __version__,
            "swe_version": provider.swe_version,
            "pyswisseph_version": provider.pyswisseph_version,
            "ephemeris_backend": None,
            "db_available": settings.db_path.is_file(),
            "saved_charts": len(list_charts(settings.charts_dir)),
            "natal_backend": natal_backend,
            "auth_configured": auth_name != "RejectingAuthenticator",
            "ai_seed": active_ai_seed_queue is not None,
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
            result = compose_report(chart, store, comparison=comparison).to_dict()
        result["wheel"] = _wheel_payload(chart)
        return result

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

    @app.get("/api/skypack")
    def skypack_export(
        natal_id: str | None = Query(default=None),
        when: str | None = Query(default=None),
        tz: str | None = Query(default=None),
    ) -> dict[str, Any]:
        identifier = _required_string(natal_id, "natal_id")
        return build_skypack(
            identifier,
            when=when,
            tz=tz,
            charts_dir=settings.charts_dir,
            boundary_path=settings.boundary_path,
            ephe_path=settings.ephe_path,
            require_swiss_ephemeris=settings.require_swiss_ephemeris,
        )

    @app.get("/api/sky-day")
    def sky_day(
        response: Response,
        tz: str = Query(default="UTC"),
        date: str | None = Query(default=None),
        when: str | None = Query(default=None),
        origin: str | None = Header(default=None),
    ) -> Any:
        _set_sky_day_headers(response, origin, sky_day_origins)
        try:
            return sky_day_cache.get(
                tz=tz,
                date=date,
                when=when,
                boundary_path=settings.boundary_path,
                ephe_path=settings.ephe_path,
                require_swiss_ephemeris=settings.require_swiss_ephemeris,
            )
        except ValueError as exc:
            return _sky_day_error_response(
                status_code=400,
                detail=str(exc),
                origin=origin,
                allowed_origins=sky_day_origins,
            )
        except SkyDayCalculationError as exc:
            return _sky_day_error_response(
                status_code=500,
                detail=f"Sky-day calculation failed: {exc}",
                origin=origin,
                allowed_origins=sky_day_origins,
            )

    @app.options("/api/sky-day", include_in_schema=False)
    def sky_day_preflight(
        origin: str | None = Header(default=None),
        access_control_request_method: str | None = Header(default=None),
    ) -> Response:
        if origin not in sky_day_origins:
            return Response(status_code=400)
        if access_control_request_method != "GET":
            return Response(status_code=405)
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET",
                "Vary": "Origin",
            },
        )

    @app.post("/api/me/natal")
    def personal_natal_upsert(
        payload: dict[str, Any],
        response: Response,
        user_id: str = Depends(required_personal_user_id),
    ) -> dict[str, Any]:
        record = natal_record_from_payload(user_id, payload)
        # Validate civil-time/ephemeris calculation before replacing a good row.
        compute_natal_chart(
            record,
            boundary_path=settings.boundary_path,
            ephe_path=settings.ephe_path,
            require_swiss_ephemeris=settings.require_swiss_ephemeris,
        )
        saved = active_natal_store.upsert(record)
        active_personal_cache.invalidate(user_id)
        # Build the private pack in the same request so the client does not depend
        # on a second hop (and so multi-instance memory backends still work).
        pack = active_personal_cache.get(saved)
        response.headers["Cache-Control"] = "private, no-store"
        result = saved.to_dict()
        result["skypack"] = pack
        return result

    @app.get("/api/me/natal")
    def personal_natal_get(
        response: Response,
        user_id: str = Depends(required_personal_user_id),
    ) -> dict[str, Any]:
        record = active_natal_store.get(user_id)
        if record is None:
            raise HTTPException(status_code=404, detail="No natal profile is saved")
        response.headers["Cache-Control"] = "private, no-store"
        return record.to_dict()

    @app.delete("/api/me/natal", status_code=204)
    def personal_natal_delete(
        user_id: str = Depends(required_personal_user_id),
    ) -> Response:
        active_natal_store.delete(user_id)
        active_personal_cache.invalidate(user_id)
        return Response(status_code=204, headers={"Cache-Control": "private, no-store"})

    @app.get("/api/me/skypack")
    def personal_skypack(
        response: Response,
        user_id: str = Depends(required_personal_user_id),
    ) -> dict[str, Any]:
        record = active_natal_store.get(user_id)
        if record is None:
            raise HTTPException(status_code=404, detail="No natal profile is saved")
        response.headers["Cache-Control"] = "private, no-store"
        return active_personal_cache.get(record)

    @app.options("/api/me/{resource:path}", include_in_schema=False)
    def personal_preflight(
        resource: str,
        origin: str | None = Header(default=None),
        access_control_request_method: str | None = Header(default=None),
    ) -> Response:
        del resource
        if origin not in personal_origins:
            return Response(status_code=400)
        if access_control_request_method not in {"GET", "POST", "DELETE"}:
            return Response(status_code=405)
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": (
                    "Authorization, Content-Type"
                    + (", X-Dev-User-Id" if dev_auth_enabled else "")
                ),
                "Access-Control-Max-Age": "600",
            },
        )

    @app.get("/api/sky-listen")
    def sky_listen(
        response: Response,
        natal_id: str | None = Query(default=None),
        body: str | None = Query(default=None),
        sign: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        when: str | None = Query(default=None),
        tz: str | None = Query(default=None),
        origin: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
        dev_user_id: str | None = Header(default=None, alias="X-Dev-User-Id"),
    ) -> dict[str, Any]:
        _set_sky_listen_cors(response, origin, personal_origins)
        with _optional_store(settings) as store:
            listen_store = (
                EnqueueingEntryLookup(store, active_ai_seed_queue)
                if store is not None and active_ai_seed_queue is not None
                else store
            )
            if natal_id is not None:
                if authorization is not None or dev_user_id is not None:
                    authenticated_user_id(
                        authorization,
                        dev_user_id,
                        required=True,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="provide either natal_id or authenticated user natal, not both",
                    )
                return build_sky_listen(
                    natal_id=natal_id,
                    body=body,
                    sign=sign,
                    kind=kind,
                    when=when,
                    tz=tz,
                    charts_dir=settings.charts_dir,
                    boundary_path=settings.boundary_path,
                    ephe_path=settings.ephe_path,
                    require_swiss_ephemeris=settings.require_swiss_ephemeris,
                    store=listen_store,
                )
            user_id = authenticated_user_id(
                authorization,
                dev_user_id,
                required=False,
            )
            if user_id is not None:
                response.headers["Cache-Control"] = "private, no-store"
            record = (
                active_natal_store.get(user_id) if user_id is not None else None
            )
            if record is None:
                return build_sky_listen(
                    body=body,
                    sign=sign,
                    kind=kind,
                    when=when,
                    tz=tz,
                    charts_dir=settings.charts_dir,
                    boundary_path=settings.boundary_path,
                    ephe_path=settings.ephe_path,
                    require_swiss_ephemeris=settings.require_swiss_ephemeris,
                    store=listen_store,
                )
            natal_chart, natal_config = compute_natal_chart(
                record,
                boundary_path=settings.boundary_path,
                ephe_path=settings.ephe_path,
                require_swiss_ephemeris=settings.require_swiss_ephemeris,
            )
            return build_sky_listen_from_chart(
                natal_chart,
                natal_config,
                natal_id=user_id,
                body=body,
                sign=sign,
                kind=kind,
                when=when,
                tz=tz,
                boundary_path=settings.boundary_path,
                ephe_path=settings.ephe_path,
                require_swiss_ephemeris=settings.require_swiss_ephemeris,
                store=listen_store,
            )

    @app.options("/api/sky-listen", include_in_schema=False)
    def sky_listen_preflight(
        origin: str | None = Header(default=None),
        access_control_request_method: str | None = Header(default=None),
    ) -> Response:
        if origin not in personal_origins:
            return Response(status_code=400)
        if access_control_request_method != "GET":
            return Response(status_code=405)
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET",
                "Access-Control-Allow-Headers": (
                    "Authorization"
                    + (", X-Dev-User-Id" if dev_auth_enabled else "")
                ),
                "Vary": "Origin",
            },
        )

    @app.get("/api/charts/{chart_id}")
    def chart_show(chart_id: str) -> dict[str, Any]:
        record = load_chart(chart_id, settings.charts_dir)
        result = record.to_dict()
        result["wheel"] = _wheel_payload(record.chart_object())
        return result

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
            result = compose_report(chart, store, comparison=comparison).to_dict()
        result["wheel"] = _wheel_payload(chart)
        return result

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
            report, geometry = calculate_transit_study(
                natal,
                transit_moment,
                transit_config,
                store,
                natal_source=natal_source,
                natal_id=natal_id,
            )
        result = report.to_dict()
        result["wheel"] = _wheel_payload(
            geometry.natal,
            overlay_chart=geometry.transit,
        )
        if _boolean(options, "save", False) or payload.get("save") is True:
            label = str(payload.get("label") or payload.get("save_label") or "").strip()
            if not label:
                natal_label = str(result.get("natal", {}).get("label") or "natal")
                transit_label = str(result.get("transit", {}).get("label") or "transit")
                label = f"{natal_label} · {transit_label}"
            snapshot = save_transit_snapshot(
                result,
                label=label,
                markdown=report.to_markdown(),
                charts_dir=settings.charts_dir,
                snapshot_id=_optional_snapshot_id(payload.get("snapshot_id")),
                natal_id=natal_id,
            )
            result["saved_transit"] = snapshot.summary_dict()
        return result

    @app.get("/api/transits")
    def transits_index() -> dict[str, Any]:
        return {
            "transits": [item.summary_dict() for item in list_transits(settings.charts_dir)]
        }

    @app.get("/api/transits/{snapshot_id}")
    def transit_show(snapshot_id: str) -> dict[str, Any]:
        try:
            record = load_transit(snapshot_id, settings.charts_dir)
        except ChartNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AmbiguousChartError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ChartLibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return record.to_dict()

    @app.post("/api/transits/{snapshot_id}/refresh")
    def transit_refresh(snapshot_id: str) -> dict[str, Any]:
        """Re-run a saved transit from linked natal + stored moment, refresh DB text."""

        try:
            existing = load_transit(snapshot_id, settings.charts_dir)
        except ChartNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not existing.natal_id:
            raise HTTPException(
                status_code=400,
                detail="This snapshot has no linked natal chart id; re-run transit and save again.",
            )
        natal_record = load_chart(existing.natal_id, settings.charts_dir)
        transit_meta = existing.report.get("transit")
        if not isinstance(transit_meta, Mapping):
            raise HTTPException(status_code=400, detail="Snapshot missing transit moment metadata")
        # Prefer original moment fields if stored on report.transit
        local_dt = str(transit_meta.get("local_datetime") or existing.transit_local_datetime)
        try:
            # local_datetime is ISO with offset; split for date/time/tz
            from datetime import datetime as _dt

            parsed = _dt.fromisoformat(local_dt)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Could not parse stored transit local_datetime: {local_dt}",
            ) from exc
        tz_name = str(transit_meta.get("tz") or getattr(natal_record, "tz", None) or "UTC")
        transit_moment = MomentInput(
            local_date=parsed.date(),
            local_time=parsed.timetz().replace(tzinfo=None),
            tz=tz_name,
            lat=None,
            lon=None,
            label=str(transit_meta.get("label") or existing.transit_label),
            fold=None,
        )
        transit_config = replace(natal_record.chart_config(), include_patterns=False, include_houses=False)
        with _optional_store(settings) as store:
            report, geometry = calculate_transit_study(
                natal_record.chart_object(),
                transit_moment,
                transit_config,
                store,
                natal_source="saved",
                natal_id=natal_record.id,
            )
        result = report.to_dict()
        result["wheel"] = _wheel_payload(geometry.natal, overlay_chart=geometry.transit)
        snapshot = save_transit_snapshot(
            result,
            label=existing.label,
            markdown=report.to_markdown(),
            charts_dir=settings.charts_dir,
            snapshot_id=existing.id,
            natal_id=natal_record.id,
            overwrite=True,
        )
        result["saved_transit"] = snapshot.summary_dict()
        result["markdown"] = snapshot.markdown
        return result

    @app.post("/api/synastry")
    def synastry_report(payload: dict[str, Any]) -> dict[str, Any]:
        options = _options(payload)
        records: dict[str, Any] = {}
        inline_payloads: dict[str, Mapping[str, Any]] = {}
        sources = {"a": "inline", "b": "inline"}
        ids: dict[str, str | None] = {"a": None, "b": None}

        for role in ("a", "b"):
            saved_value = payload.get(f"{role}_id")
            inline_value = payload.get(role)
            if (saved_value is None) == (inline_value is None):
                raise ValueError(
                    f"provide exactly one of {role}_id or {role} for chart {role.upper()}"
                )
            if saved_value is not None:
                identifier = _required_string(saved_value, f"{role}_id")
                record = load_chart(identifier, settings.charts_dir)
                records[role] = record
                sources[role] = "saved"
                ids[role] = record.id
            else:
                inline_payloads[role] = _mapping(inline_value, role)

        base_record = records.get("a") or records.get("b")
        base_config = base_record.chart_config() if base_record is not None else None
        config = _chart_config(
            settings,
            options,
            include_houses=True,
            base=base_config,
        )
        config = replace(config, include_patterns=False)
        charts = {
            role: (
                records[role].chart_object()
                if role in records
                else compute(
                    _moment_from_payload(inline_payloads[role], name=role),
                    config,
                )
            )
            for role in ("a", "b")
        }

        with _optional_store(settings) as store:
            report = calculate_synastry_report(
                charts["a"],
                charts["b"],
                config,
                store,
                source_a=sources["a"],
                id_a=ids["a"],
                source_b=sources["b"],
                id_b=ids["b"],
            ).to_dict()

        if _boolean(options, "save", False) or payload.get("save") is True:
            if ids["a"] is None or ids["b"] is None:
                raise ValueError(
                    "saving a refreshable synastry snapshot requires two saved charts"
                )
            label = payload.get("label")
            if label in (None, ""):
                label_a = str(report.get("chart_a", {}).get("label") or "A")
                label_b = str(report.get("chart_b", {}).get("label") or "B")
                label = f"{label_a} ↔ {label_b}"
            snapshot = save_synastry_snapshot(
                report,
                label=label,
                charts_dir=settings.charts_dir,
                snapshot_id=_optional_snapshot_id(payload.get("snapshot_id")),
                chart_a_id=ids["a"],
                chart_b_id=ids["b"],
            )
            report["saved_synastry"] = snapshot.summary_dict()
        return report

    @app.get("/api/synastries")
    def synastries_index() -> dict[str, Any]:
        return {
            "synastries": [
                item.summary_dict() for item in list_synastries(settings.charts_dir)
            ]
        }

    @app.get("/api/synastries/{snapshot_id}")
    def synastry_show(snapshot_id: str) -> dict[str, Any]:
        try:
            record = load_synastry(snapshot_id, settings.charts_dir)
        except ChartNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AmbiguousChartError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ChartLibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = record.to_dict()
        payload["report"] = dict(record.report)
        return payload

    @app.post("/api/synastries/{snapshot_id}/refresh")
    def synastry_refresh(snapshot_id: str) -> dict[str, Any]:
        """Re-run synastry from linked natal ids and overwrite the snapshot."""

        try:
            existing = load_synastry(snapshot_id, settings.charts_dir)
        except ChartNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not existing.chart_a_id or not existing.chart_b_id:
            raise HTTPException(
                status_code=400,
                detail="This snapshot has no linked natal chart ids; re-run synastry from the form and save again.",
            )
        record_a = load_chart(existing.chart_a_id, settings.charts_dir)
        record_b = load_chart(existing.chart_b_id, settings.charts_dir)
        config = replace(record_a.chart_config(), include_patterns=False)
        with _required_store(settings) as store:
            report = calculate_synastry_report(
                record_a.chart_object(),
                record_b.chart_object(),
                config,
                store,
                source_a="saved",
                id_a=record_a.id,
                source_b="saved",
                id_b=record_b.id,
            ).to_dict()
        snapshot = save_synastry_snapshot(
            report,
            label=existing.label,
            charts_dir=settings.charts_dir,
            snapshot_id=existing.id,
            chart_a_id=record_a.id,
            chart_b_id=record_b.id,
            overwrite=True,
        )
        payload = snapshot.to_dict()
        payload["saved_synastry"] = snapshot.summary_dict()
        return payload

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


def _wheel_payload(
    chart: Any,
    *,
    overlay_chart: Any | None = None,
    width: int = 640,
) -> dict[str, Any]:
    has_ascendant = any(point.id == "asc" for point in chart.points)
    return {
        "version": 1,
        "media_type": "image/svg+xml",
        "kind": "transit_overlay" if overlay_chart is not None else "natal",
        "width": width,
        "orientation": (
            "ascendant_at_9_oclock" if has_ascendant else "j2000_zero_at_9_oclock"
        ),
        "svg": render_svg(chart, width=width, overlay_chart=overlay_chart),
    }


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


def _header_value(scope: Mapping[str, Any], name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            try:
                return value.decode("latin-1")
            except UnicodeDecodeError:  # pragma: no cover - latin-1 decodes all bytes
                return None
    return None


def _merge_vary_origin(
    headers: list[tuple[bytes, bytes]],
) -> list[tuple[bytes, bytes]]:
    for index, (key, value) in enumerate(headers):
        if key.lower() != b"vary":
            continue
        tokens = [item.strip() for item in value.decode("latin-1").split(",")]
        if not any(item.casefold() == "origin" for item in tokens):
            tokens.append("Origin")
            headers[index] = (key, ", ".join(tokens).encode("latin-1"))
        return headers
    headers.append((b"vary", b"Origin"))
    return headers


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


def _optional_snapshot_id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("snapshot_id must be a string when provided")
    text = value.strip()
    return text or None


def _bearer_token(value: str) -> str:
    if not isinstance(value, str):
        raise AuthenticationError("Invalid bearer authorization")
    scheme, separator, token = value.strip().partition(" ")
    if (
        not separator
        or scheme.casefold() != "bearer"
        or not token
        or any(character.isspace() for character in token)
    ):
        raise AuthenticationError("Invalid bearer authorization")
    return token


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid or missing bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _set_sky_listen_cors(
    response: Response,
    origin: str | None,
    allowed_origins: frozenset[str],
) -> None:
    if origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"


def _sky_day_allowed_origins() -> frozenset[str]:
    configured = os.environ.get("SKY_DAY_CORS_ORIGINS", "")
    additions = (item.strip() for item in configured.split(","))
    return frozenset((*_SKY_DAY_DEFAULT_ORIGINS, *(item for item in additions if item)))


def _set_sky_day_headers(
    response: Response,
    origin: str | None,
    allowed_origins: frozenset[str],
) -> None:
    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["Vary"] = "Origin"
    if origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin


def _sky_day_error_response(
    *,
    status_code: int,
    detail: str,
    origin: str | None,
    allowed_origins: frozenset[str],
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={"detail": detail},
        headers={"Cache-Control": "no-store", "Vary": "Origin"},
    )
    if origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
    return response


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


__all__ = [
    "HostGuardMiddleware",
    "ScopedCORSMiddleware",
    "WebSettings",
    "create_app",
]
