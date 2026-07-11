"""Chart-scoped interpretation inventory helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_READING_STATUSES = frozenset(("ready", "stub", "user", "missing"))


def report_interpretation_ids(report: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the canonical reading ids actually present in a report payload."""

    if not isinstance(report, Mapping):
        raise TypeError("report JSON must be an object")
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            entry_id = value.get("id")
            status = value.get("status")
            if isinstance(entry_id, str) and status in _READING_STATUSES:
                found.add(entry_id)
            for child in value.values():
                visit(child)
        elif isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            for child in value:
                visit(child)

    visit(report)
    if not found:
        raise ValueError(
            "report JSON contains no interpretation readings; pass a full chart report"
        )
    return tuple(sorted(found))


__all__ = ["report_interpretation_ids"]
