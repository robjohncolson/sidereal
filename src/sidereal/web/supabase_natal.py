"""Optional Supabase/PostgREST implementation of the private natal store."""

from __future__ import annotations

from collections.abc import Mapping
import ipaddress
import os
import re
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from ..auth import normalize_user_id
from ..natal import MemoryNatalStore, NatalRecord, NatalStore, NatalStoreError


_TABLE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")
_SELECT_FIELDS = (
    "user_id,birth_date,birth_time,time_unknown,tz,lat,lon,place_label,updated_at"
)


class SupabaseNatalStore:
    """Server-side owner-keyed CRUD through Supabase's REST endpoint."""

    def __init__(
        self,
        supabase_url: str,
        service_role_key: str,
        *,
        table: str = "natal_charts",
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not isinstance(supabase_url, str) or not supabase_url.strip():
            raise ValueError("SUPABASE_URL must be a non-empty URL")
        if not isinstance(service_role_key, str) or not service_role_key.strip():
            raise ValueError("Supabase server key must be non-empty")
        if _TABLE_RE.fullmatch(table) is None:
            raise ValueError("SUPABASE_NATAL_TABLE is not a safe table identifier")
        base = supabase_url.strip().rstrip("/")
        try:
            parsed = urlsplit(base)
            hostname = parsed.hostname
            parsed.port  # force validation of malformed port syntax
        except ValueError as exc:
            raise ValueError("SUPABASE_URL must be a valid URL") from exc
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
            raise ValueError("SUPABASE_URL must use HTTPS (or loopback HTTP for tests)")
        server_key = service_role_key.strip()
        self._endpoint = f"{base}/rest/v1/{table}"
        self._headers = {
            "apikey": server_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        # Current ``sb_secret_*`` keys belong only in ``apikey``.  Legacy
        # service-role JWTs can also be sent as the PostgREST bearer token.
        if _looks_like_jwt(server_key):
            self._headers["Authorization"] = f"Bearer {server_key}"
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get(self, user_id: str) -> NatalRecord | None:
        normalized = normalize_user_id(user_id)
        rows = self._rows("GET", self._user_url(normalized, select=True))
        if not rows:
            return None
        if len(rows) != 1:
            raise NatalStoreError("Natal backend returned duplicate user rows")
        record = NatalRecord.from_storage(rows[0])
        if record.user_id != normalized:
            raise NatalStoreError("Natal backend returned the wrong user row")
        return record

    def upsert(self, record: NatalRecord) -> NatalRecord:
        if not isinstance(record, NatalRecord):
            raise TypeError("record must be a NatalRecord")
        rows = self._rows(
            "POST",
            f"{self._endpoint}?on_conflict=user_id&select={_SELECT_FIELDS}",
            json=record.storage_dict(),
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        if len(rows) != 1:
            raise NatalStoreError("Natal backend did not return the upserted row")
        saved = NatalRecord.from_storage(rows[0])
        if saved.user_id != record.user_id:
            raise NatalStoreError("Natal backend returned the wrong user row")
        return saved

    def delete(self, user_id: str) -> bool:
        normalized = normalize_user_id(user_id)
        rows = self._rows(
            "DELETE",
            self._user_url(normalized, select=True),
            headers={
                "Prefer": "handling=strict,max-affected=1,return=representation"
            },
        )
        if not rows:
            return False
        if len(rows) != 1:
            raise NatalStoreError("Natal backend deleted duplicate user rows")
        deleted = NatalRecord.from_storage(rows[0])
        if deleted.user_id != normalized:
            raise NatalStoreError("Natal backend returned the wrong user row")
        return True

    def _user_url(self, user_id: str, *, select: bool) -> str:
        normalized = normalize_user_id(user_id)
        url = f"{self._endpoint}?user_id=eq.{quote(normalized, safe='')}"
        return f"{url}&select={_SELECT_FIELDS}" if select else url

    def _rows(
        self,
        method: str,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> list[Mapping[str, Any]]:
        merged_headers = {**self._headers, **dict(headers or {})}
        try:
            response = self._client.request(
                method,
                url,
                headers=merged_headers,
                json=dict(json) if json is not None else None,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = int(exc.response.status_code)
            # Safe, actionable signal only — never echo Supabase response bodies
            # (they can include policy text or keys in some misconfigurations).
            raise NatalStoreError(f"Natal backend HTTP {status}") from exc
        except httpx.HTTPError as exc:
            raise NatalStoreError("Natal backend request failed") from exc
        if not response.content:
            return []
        try:
            payload = response.json()
        except ValueError as exc:
            raise NatalStoreError("Natal backend returned invalid JSON") from exc
        if not isinstance(payload, list) or not all(
            isinstance(item, Mapping) for item in payload
        ):
            raise NatalStoreError("Natal backend returned an invalid row set")
        return payload


def natal_store_from_env() -> NatalStore:
    """Select a process-memory or durable Supabase natal backend once."""

    backend = os.environ.get("SIDEREAL_NATAL_BACKEND", "auto").strip().casefold()
    if backend not in {"auto", "memory", "supabase"}:
        raise ValueError("SIDEREAL_NATAL_BACKEND must be auto, memory, or supabase")
    if backend == "memory":
        return MemoryNatalStore()
    raw_url = os.environ.get("SUPABASE_URL", "")
    url = raw_url.strip()
    raw_secret_key = os.environ.get("SUPABASE_SECRET_KEY", "")
    raw_legacy_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    secret_key = raw_secret_key.strip()
    legacy_key = raw_legacy_key.strip()
    server_key = secret_key or legacy_key
    if backend == "supabase" or raw_url or raw_secret_key or raw_legacy_key:
        if not url or not server_key:
            raise ValueError(
                "Supabase natal storage requires both SUPABASE_URL and "
                "SUPABASE_SECRET_KEY (or legacy SUPABASE_SERVICE_ROLE_KEY); "
                "otherwise set SIDEREAL_NATAL_BACKEND=memory"
            )
        return SupabaseNatalStore(
            url,
            server_key,
            table=os.environ.get("SUPABASE_NATAL_TABLE", "natal_charts"),
        )
    return MemoryNatalStore()


def _looks_like_jwt(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 3 and all(parts)


def _is_loopback_host(value: str) -> bool:
    if value.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


__all__ = ["SupabaseNatalStore", "natal_store_from_env"]
