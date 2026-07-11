from __future__ import annotations

import json
import math
from pathlib import Path

from sidereal.zodiac.base import forward_arc
from sidereal.zodiac.midpoint import EXPECTED_SIGN_IDS, MidpointZodiac


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOUNDARY_FILE = PROJECT_ROOT / "data" / "boundaries" / "midpoint_j2000_v1.json"


def test_boundary_file_has_required_provenance_and_inventory() -> None:
    payload = json.loads(BOUNDARY_FILE.read_text(encoding="utf-8"))

    assert payload["id"] == "midpoint_v1"
    assert payload["frame"] == "ecliptic_j2000"
    assert payload["version"] == 1
    assert payload["license_id"] == "cc-by-nc-nd-4.0"
    assert payload["source"]["doi"] == "10.5281/zenodo.20747017"
    assert tuple(item["id"] for item in payload["signs"]) == EXPECTED_SIGN_IDS


def test_declared_lengths_and_consecutive_starts_form_one_circle() -> None:
    payload = json.loads(BOUNDARY_FILE.read_text(encoding="utf-8"))
    signs = payload["signs"]

    assert math.isclose(
        sum(item["length_deg"] for item in signs),
        360.0,
        rel_tol=0.0,
        abs_tol=0.001,
    )
    effective_lengths = []
    for index, item in enumerate(signs):
        next_item = signs[(index + 1) % len(signs)]
        effective = forward_arc(item["start_deg"], next_item["start_deg"])
        effective_lengths.append(effective)
        assert math.isclose(
            effective,
            item["length_deg"],
            rel_tol=0.0,
            abs_tol=0.001,
        )
    assert math.isclose(sum(effective_lengths), 360.0, rel_tol=0.0, abs_tol=1e-10)


def test_rounded_lengths_cannot_create_micro_gaps_or_overlaps() -> None:
    zodiac = MidpointZodiac.from_file(BOUNDARY_FILE)

    assert zodiac.map(267.07105, blend_orb_deg=0).sign == "ophiuchus"
    assert zodiac.map(267.0711, blend_orb_deg=0).sign == "sagittarius"
    assert zodiac.map(300.46219, blend_orb_deg=0).sign == "sagittarius"
    assert zodiac.map(300.46225, blend_orb_deg=0).sign == "capricorn"

