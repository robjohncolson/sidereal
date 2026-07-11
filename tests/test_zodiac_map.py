from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from sidereal.zodiac.midpoint import MidpointZodiac, resolve_boundary_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOUNDARY_FILE = PROJECT_ROOT / "data" / "boundaries" / "midpoint_j2000_v1.json"


@pytest.fixture(scope="module")
def zodiac() -> MidpointZodiac:
    return MidpointZodiac.from_file(BOUNDARY_FILE)


@pytest.mark.parametrize(
    ("longitude", "sign", "degree"),
    [
        (31.2816, "aries", 0.0),
        (40.0, "aries", 8.7184),
        (51.0083, "taurus", 0.0),
        (254.7132, "ophiuchus", 0.0),
        (260.0, "ophiuchus", 5.2868),
        (267.0711, "sagittarius", 0.0),
        (0.0, "pisces", 10.7041),
        (360.0, "pisces", 10.7041),
        (-0.5, "pisces", 10.2041),
    ],
)
def test_circular_half_open_mapping(
    zodiac: MidpointZodiac,
    longitude: float,
    sign: str,
    degree: float,
) -> None:
    placement = zodiac.map(longitude, blend_orb_deg=0.0)
    assert placement.sign == sign
    assert placement.degree_in_sign == pytest.approx(degree, abs=1e-9)


def test_blend_chooses_adjacent_sign_across_nearest_boundary(zodiac: MidpointZodiac) -> None:
    at_start = zodiac.map(254.7132)
    inside = zodiac.map(260.0)
    near_end = zodiac.map(266.0)

    assert (at_start.blend, at_start.secondary_sign) == (True, "scorpio")
    assert (inside.blend, inside.secondary_sign) == (False, None)
    assert (near_end.blend, near_end.secondary_sign) == (True, "sagittarius")


def test_blend_orb_is_inclusive(zodiac: MidpointZodiac) -> None:
    placement = zodiac.map(31.2816 + 3.0, blend_orb_deg=3.0)
    assert placement.blend is True
    assert placement.secondary_sign == "pisces"


def test_nonfinite_inputs_fail_loudly(zodiac: MidpointZodiac) -> None:
    with pytest.raises(ValueError, match="finite"):
        zodiac.map(math.nan)
    with pytest.raises(ValueError, match="non-negative"):
        zodiac.map(0.0, blend_orb_deg=-1.0)


def test_default_resolver_finds_editable_root_data() -> None:
    assert resolve_boundary_path() == BOUNDARY_FILE.resolve()


def test_missing_explicit_or_environment_boundary_never_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match="explicit boundary path"):
        resolve_boundary_path(missing)

    monkeypatch.setenv("SIDEREAL_BOUNDARY_PATH", str(missing))
    with pytest.raises(FileNotFoundError, match="SIDEREAL_BOUNDARY_PATH"):
        resolve_boundary_path()


@pytest.mark.parametrize("missing_field", ["version", "license", "license_id", "source"])
def test_canonical_boundary_requires_provenance_metadata(
    missing_field: str, tmp_path: Path
) -> None:
    payload = json.loads(BOUNDARY_FILE.read_text(encoding="utf-8"))
    payload.pop(missing_field)
    path = tmp_path / f"missing-{missing_field}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        MidpointZodiac.from_file(path)


def test_boundary_version_rejects_json_boolean(tmp_path: Path) -> None:
    payload = json.loads(BOUNDARY_FILE.read_text(encoding="utf-8"))
    payload["version"] = True
    path = tmp_path / "boolean-version.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="integer version"):
        MidpointZodiac.from_file(path)


def test_midpoint_v1_rejects_internally_coherent_but_noncanonical_starts(
    tmp_path: Path,
) -> None:
    payload = json.loads(BOUNDARY_FILE.read_text(encoding="utf-8"))
    for sign in payload["signs"]:
        sign["start_deg"] += 1.0
    path = tmp_path / "shifted.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="start longitudes"):
        MidpointZodiac.from_file(path)
