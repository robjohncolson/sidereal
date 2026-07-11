"""Thin, explicit wrapper around the :mod:`swisseph` Python binding."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
import math
import os
from pathlib import Path
import site
import sys
import sysconfig
from threading import RLock
from typing import Any, Protocol, runtime_checkable

from .config import BODY_IDS
from .zodiac.base import normalize_longitude


_SWE_LOCK = RLock()
EPHE_PATH_ENV = "SIDEREAL_EPHE_PATH"


class EphemerisError(RuntimeError):
    """Raised when Swiss Ephemeris cannot produce a complete, coherent result."""


@dataclass(frozen=True, slots=True)
class RawPosition:
    id: str
    lon_date: float
    lon_j2000: float
    lat: float
    speed_long: float


@dataclass(frozen=True, slots=True)
class PositionBatch:
    positions: tuple[RawPosition, ...]
    backend: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RawHouseData:
    cusps_date: tuple[float, ...]
    cusps_j2000: tuple[float, ...]
    cusp_speeds_date: tuple[float, ...]
    asc_date: float
    asc_j2000: float
    asc_speed_date: float
    mc_date: float
    mc_j2000: float
    mc_speed_date: float


@runtime_checkable
class EphemerisProvider(Protocol):
    swe_version: str
    pyswisseph_version: str

    def calculate_positions(self, jd_ut: float) -> PositionBatch:
        ...

    def calculate_houses(self, jd_ut: float, lat: float, lon: float) -> RawHouseData:
        ...


class SwissEphemeris:
    """Geocentric apparent positions and equal-house angles from Swiss Ephemeris.

    Planetary longitude is requested twice.  The normal call supplies apparent
    tropical ecliptic-of-date longitude/speed for aspects and houses; adding
    ``FLG_J2000`` asks Swiss Ephemeris itself to precess the same apparent point
    into the mean J2000 ecliptic frame required by the Midpoint boundary table.

    Equal-house cusps are first computed in the tropical ecliptic of date.
    Swiss Ephemeris does not expose a public arbitrary-vector precession call,
    and its sidereal-house projection is explicitly unsuitable for converting
    equal cusps.  Instead, corresponding ``FLG_XYZ`` body vectors in the date
    and ``FLG_J2000`` frames define the exact rigid SE rotation; that rotation
    is then applied to every tropical cusp, Ascendant, and Midheaven vector.
    """

    position_flags = ("FLG_SWIEPH", "FLG_SPEED", "FLG_J2000")
    house_frame_flags = ("FLG_XYZ", "FLG_J2000")
    house_frame_method = "se_xyz_rigid_rotation"

    def __init__(
        self,
        *,
        ephe_path: str | Path | None = None,
        require_swiss_ephemeris: bool = False,
        swe_module: Any | None = None,
    ) -> None:
        if swe_module is None:
            try:
                import swisseph as swe_module  # type: ignore[no-redef]
            except ImportError as exc:  # pragma: no cover - packaging failure
                raise RuntimeError(
                    "pyswisseph is required; install the project dependencies before computing a chart"
                ) from exc
        self._swe = swe_module
        self.require_swiss_ephemeris = require_swiss_ephemeris
        self.swe_version = str(getattr(swe_module, "version", "unknown"))
        try:
            self.pyswisseph_version = metadata.version("pyswisseph")
        except metadata.PackageNotFoundError:
            self.pyswisseph_version = str(getattr(swe_module, "__version__", "unknown"))
        self.ephe_path = resolve_ephe_path(ephe_path)
        # The binding path is process-global.  Set it for every provider,
        # including an explicit empty fallback, so a previous chart/test cannot
        # leak a different directory into this calculation.
        with _SWE_LOCK:
            self._activate_ephemeris_path()

    def _activate_ephemeris_path(self) -> None:
        """Apply this provider's path while the process-global SE lock is held."""

        self._swe.set_ephe_path(
            str(self.ephe_path) if self.ephe_path is not None else None
        )

    def calculate_positions(self, jd_ut: float) -> PositionBatch:
        if not math.isfinite(jd_ut):
            raise ValueError("jd_ut must be finite")
        swe = self._swe
        flags_date = swe.FLG_SWIEPH | swe.FLG_SPEED
        flags_j2000 = flags_date | swe.FLG_J2000
        body_numbers = _body_numbers(swe)
        raw: list[RawPosition] = []
        backends: set[str] = set()

        with _SWE_LOCK:
            # Another provider may have changed this process-global setting
            # after our constructor returned. Reapply it in the same critical
            # section as every calculation.
            self._activate_ephemeris_path()
            for body_id in BODY_IDS:
                if body_id == "south_node":
                    continue
                body_number = body_numbers[body_id]
                try:
                    position_date, returned_date = swe.calc_ut(jd_ut, body_number, flags_date)
                    position_j2000, returned_j2000 = swe.calc_ut(jd_ut, body_number, flags_j2000)
                except Exception as exc:
                    raise EphemerisError(
                        f"Swiss Ephemeris failed for {body_id} at JD(UT) {jd_ut:.9f}: {exc}"
                    ) from exc
                _validate_return_flags(swe, body_id, returned_date, require_j2000=False)
                _validate_return_flags(swe, body_id, returned_j2000, require_j2000=True)
                backends.add(_backend_name(swe, returned_date))
                backends.add(_backend_name(swe, returned_j2000))
                raw.append(
                    RawPosition(
                        id=body_id,
                        lon_date=normalize_longitude(position_date[0]),
                        lon_j2000=normalize_longitude(position_j2000[0]),
                        lat=float(position_date[1]),
                        speed_long=float(position_date[3]),
                    )
                )

        if len(backends) != 1:
            raise EphemerisError(f"Mixed or unknown ephemeris backends in one chart: {sorted(backends)}")
        backend = next(iter(backends))
        if self.require_swiss_ephemeris and backend != "swisseph":
            raise EphemerisError(
                "Swiss .se1 ephemeris files were required but unavailable; "
                "install the required files under data/ephe or select their directory "
                f"with --ephe-path (binding returned backend {backend!r})"
            )

        north = next(item for item in raw if item.id == "north_node")
        raw.append(
            RawPosition(
                id="south_node",
                lon_date=normalize_longitude(north.lon_date + 180.0),
                lon_j2000=normalize_longitude(north.lon_j2000 + 180.0),
                lat=-north.lat,
                speed_long=north.speed_long,
            )
        )
        by_id = {item.id: item for item in raw}
        ordered = tuple(by_id[body_id] for body_id in BODY_IDS)
        warnings: tuple[str, ...] = ()
        if backend == "moseph":
            warnings = (
                "Swiss ephemeris files were not found; Swiss Ephemeris used its built-in Moshier fallback.",
            )
        return PositionBatch(positions=ordered, backend=backend, warnings=warnings)

    def calculate_houses(self, jd_ut: float, lat: float, lon: float) -> RawHouseData:
        if not all(math.isfinite(value) for value in (jd_ut, lat, lon)):
            raise ValueError("House inputs must be finite")
        if not -90.0 < lat < 90.0:
            raise ValueError("lat must be strictly between -90 and 90 degrees")
        if not -180.0 <= lon <= 180.0:
            raise ValueError("lon must be between -180 and 180 degrees")
        swe = self._swe
        try:
            with _SWE_LOCK:
                self._activate_ephemeris_path()
                cusps_date, ascmc_date, cusp_speeds, ascmc_speeds = swe.houses_ex2(
                    jd_ut, lat, lon, b"E", 0
                )
                rotation = _date_to_j2000_rotation(swe, jd_ut)
                cusps_j2000 = tuple(
                    _rotate_ecliptic_longitude(value, rotation)
                    for value in cusps_date
                )
                asc_j2000 = _rotate_ecliptic_longitude(ascmc_date[0], rotation)
                mc_j2000 = _rotate_ecliptic_longitude(ascmc_date[1], rotation)
        except Exception as exc:
            raise EphemerisError(
                f"Swiss Ephemeris house calculation failed at JD(UT) {jd_ut:.9f}: {exc}"
            ) from exc
        if not (
            len(cusps_date) == len(cusps_j2000) == len(cusp_speeds) == 12
            and len(ascmc_date) >= 2
            and len(ascmc_speeds) >= 2
        ):
            raise EphemerisError("Swiss Ephemeris returned an unexpected houses_ex2 tuple shape")
        numeric_values = (
            *cusps_date,
            *cusps_j2000,
            *cusp_speeds,
            ascmc_date[0],
            ascmc_date[1],
            asc_j2000,
            mc_j2000,
            ascmc_speeds[0],
            ascmc_speeds[1],
        )
        if not all(math.isfinite(float(value)) for value in numeric_values):
            raise EphemerisError("Swiss Ephemeris returned non-finite house geometry")
        return RawHouseData(
            cusps_date=tuple(normalize_longitude(value) for value in cusps_date),
            cusps_j2000=tuple(normalize_longitude(value) for value in cusps_j2000),
            cusp_speeds_date=tuple(float(value) for value in cusp_speeds),
            asc_date=normalize_longitude(ascmc_date[0]),
            asc_j2000=asc_j2000,
            asc_speed_date=float(ascmc_speeds[0]),
            mc_date=normalize_longitude(ascmc_date[1]),
            mc_j2000=mc_j2000,
            mc_speed_date=float(ascmc_speeds[1]),
        )


def _body_numbers(swe: Any) -> dict[str, int]:
    return {
        "sun": swe.SUN,
        "moon": swe.MOON,
        "mercury": swe.MERCURY,
        "venus": swe.VENUS,
        "mars": swe.MARS,
        "jupiter": swe.JUPITER,
        "saturn": swe.SATURN,
        "uranus": swe.URANUS,
        "neptune": swe.NEPTUNE,
        "pluto": swe.PLUTO,
        "north_node": swe.TRUE_NODE,
    }


Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]


def _date_to_j2000_rotation(swe: Any, jd_ut: float) -> Matrix3:
    """Recover SE's exact date-frame to J2000 rigid rotation.

    Two non-collinear physical vectors uniquely determine an orientation.
    Selecting the widest-separated pair among the required bodies keeps the
    orthonormal basis well conditioned even near a conjunction.  The same
    rotation reproduces every other body's direct ``FLG_J2000`` vector to
    floating-point precision and remains tied to SE's configured long-term
    precession/nutation model.
    """

    flags_date = swe.FLG_SWIEPH | swe.FLG_XYZ
    flags_j2000 = flags_date | swe.FLG_J2000
    references: list[tuple[Vector3, Vector3]] = []
    for body_id, body_number in _body_numbers(swe).items():
        try:
            vector_date, returned_date = swe.calc_ut(jd_ut, body_number, flags_date)
            vector_j2000, returned_j2000 = swe.calc_ut(
                jd_ut, body_number, flags_j2000
            )
        except Exception as exc:
            raise EphemerisError(
                f"Swiss Ephemeris frame reference failed for {body_id}: {exc}"
            ) from exc
        if not returned_date & swe.FLG_XYZ or not returned_j2000 & swe.FLG_XYZ:
            raise EphemerisError(
                f"Swiss Ephemeris omitted requested Cartesian frame for {body_id}"
            )
        if not returned_j2000 & swe.FLG_J2000:
            raise EphemerisError(
                f"Swiss Ephemeris omitted requested J2000 frame for {body_id}"
            )
        references.append(
            (
                _unit_vector(tuple(float(value) for value in vector_date[:3])),
                _unit_vector(tuple(float(value) for value in vector_j2000[:3])),
            )
        )

    best_pair: tuple[int, int] | None = None
    best_score = -1.0
    for left in range(len(references) - 1):
        for right in range(left + 1, len(references)):
            cross = _cross(references[left][0], references[right][0])
            score = _dot(cross, cross)
            if score > best_score:
                best_pair = (left, right)
                best_score = score
    if best_pair is None or best_score < 1e-12:
        raise EphemerisError("Could not derive a stable date-to-J2000 frame rotation")

    left, right = best_pair
    basis_date = _orthonormal_basis(references[left][0], references[right][0])
    basis_j2000 = _orthonormal_basis(
        references[left][1], references[right][1]
    )
    # Basis vectors are columns: R = B_j2000 * transpose(B_date).
    return tuple(
        tuple(
            sum(basis_j2000[column][row] * basis_date[column][item] for column in range(3))
            for item in range(3)
        )
        for row in range(3)
    )  # type: ignore[return-value]


def _orthonormal_basis(first: Vector3, second: Vector3) -> tuple[Vector3, Vector3, Vector3]:
    axis_1 = _unit_vector(first)
    projection = _dot(second, axis_1)
    axis_2 = _unit_vector(
        tuple(second[index] - projection * axis_1[index] for index in range(3))  # type: ignore[arg-type]
    )
    axis_3 = _unit_vector(_cross(axis_1, axis_2))
    return axis_1, axis_2, axis_3


def _unit_vector(vector: Vector3) -> Vector3:
    magnitude = math.sqrt(_dot(vector, vector))
    if not math.isfinite(magnitude) or magnitude <= 0.0:
        raise EphemerisError("Swiss Ephemeris returned a degenerate frame vector")
    return tuple(value / magnitude for value in vector)  # type: ignore[return-value]


def _dot(left: Vector3, right: Vector3) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _rotate_ecliptic_longitude(longitude_deg: float, rotation: Matrix3) -> float:
    angle = math.radians(longitude_deg)
    vector = (math.cos(angle), math.sin(angle), 0.0)
    rotated = tuple(
        sum(rotation[row][column] * vector[column] for column in range(3))
        for row in range(3)
    )
    return normalize_longitude(math.degrees(math.atan2(rotated[1], rotated[0])))


def resolve_ephe_path(explicit_path: str | Path | None = None) -> Path | None:
    """Resolve local ephemeris files across editable and wheel installs."""

    if explicit_path is not None:
        return _required_directory(Path(explicit_path), "explicit ephemeris path")
    environment_path = os.environ.get(EPHE_PATH_ENV)
    if environment_path:
        return _required_directory(Path(environment_path), EPHE_PATH_ENV)

    project_path = Path(__file__).resolve().parents[2] / "data" / "ephe"
    user_path = Path(site.USER_BASE) / "share" / "sidereal" / "ephe"
    installed_path = Path(sysconfig.get_path("data")) / "share" / "sidereal" / "ephe"
    if sys.prefix != sys.base_prefix:
        installed_candidates = (installed_path,)
    elif site.ENABLE_USER_SITE:
        installed_candidates = (user_path, installed_path)
    else:
        installed_candidates = (installed_path,)
    for candidate in (project_path, *installed_candidates):
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _required_directory(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if not expanded.is_dir():
        raise FileNotFoundError(f"{label} is not a directory: {expanded}")
    return expanded.resolve()


def _backend_name(swe: Any, returned_flags: int) -> str:
    if returned_flags & swe.FLG_JPLEPH:
        return "jpl"
    if returned_flags & swe.FLG_SWIEPH:
        return "swisseph"
    if returned_flags & swe.FLG_MOSEPH:
        return "moseph"
    return "unknown"


def _validate_return_flags(
    swe: Any,
    body_id: str,
    returned_flags: int,
    *,
    require_j2000: bool,
) -> None:
    if not returned_flags & swe.FLG_SPEED:
        raise EphemerisError(f"Swiss Ephemeris omitted requested speed for {body_id}")
    if require_j2000 and not returned_flags & swe.FLG_J2000:
        raise EphemerisError(f"Swiss Ephemeris omitted requested J2000 conversion for {body_id}")
    if _backend_name(swe, returned_flags) == "unknown":
        raise EphemerisError(f"Swiss Ephemeris returned no recognized backend flag for {body_id}")


__all__ = [
    "EphemerisError",
    "EphemerisProvider",
    "PositionBatch",
    "RawHouseData",
    "RawPosition",
    "SwissEphemeris",
    "resolve_ephe_path",
]
