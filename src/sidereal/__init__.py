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
    TransitAspectHit,
)
from .transit import TransitGeometry, TransitPlacement, compute_transit_geometry

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
    "TransitAspectHit",
    "TransitGeometry",
    "TransitPlacement",
    "compute_transit_geometry",
    "__version__",
]
