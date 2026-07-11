"""Sidereal Moment Interpreter public package."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .types import (
    AspectHit,
    Chart,
    ChartMeta,
    HouseCusp,
    MomentInput,
    PatternHit,
    PointPos,
)

try:
    __version__ = version("sidereal")
except PackageNotFoundError:  # pragma: no cover - direct source-tree import
    __version__ = "0.1.0"

__all__ = [
    "AspectHit",
    "Chart",
    "ChartMeta",
    "HouseCusp",
    "MomentInput",
    "PatternHit",
    "PointPos",
    "__version__",
]

