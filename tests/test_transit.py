from __future__ import annotations

from dataclasses import replace
from datetime import date, time
import json
from pathlib import Path

import pytest

pytest.importorskip("swisseph")

from sidereal.chart import compute
from sidereal.config import ChartConfig
from sidereal.houses import assign_house
from sidereal.interpret.store import InterpretationStore
from sidereal.interpret.transit import (
    TRANSIT_EPISTEMIC_NOTE,
    TRANSIT_MOON_WARNING,
    compose_transit_report,
)
from sidereal.transit import TransitGeometry, compute_transit_geometry
from sidereal.types import MomentInput, TransitAspectHit


SEED_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "seeds"


@pytest.fixture(scope="module")
def live_geometry() -> TransitGeometry:
    config = ChartConfig()
    natal = compute(
        MomentInput(
            date(2000, 12, 12),
            time(12),
            "UTC",
            0.0,
            0.0,
            "Ophiuchus natal",
        ),
        config,
    )
    transit = compute(
        MomentInput(
            date(2026, 7, 11),
            time(12),
            "UTC",
            label="Transit fixture",
        ),
        config,
    )
    return compute_transit_geometry(natal, transit, config)


def _seeded_store(tmp_path: Path) -> InterpretationStore:
    store = InterpretationStore(tmp_path / "interpretations.db")
    store.initialize()
    for seed_file in sorted(SEED_DIRECTORY.glob("*.json")):
        if seed_file.name != "seed_13_offline_ai_v1.json":
            store.import_path(seed_file)
    return store


def test_known_natal_geometry_adds_house_overlays_and_angle_hits(
    live_geometry: TransitGeometry,
) -> None:
    placements = {placement.id: placement for placement in live_geometry.placements}

    assert len(placements) == 12
    assert all(placement.natal_house in range(1, 13) for placement in placements.values())
    assert placements["uranus"].natal_house == 3
    natal_angle_ids = {
        hit.natal_point
        for hit in live_geometry.aspects
        if hit.natal_point in {"asc", "mc"}
    }
    assert natal_angle_ids == {"asc", "mc"}


def test_unknown_time_natal_omits_house_overlays_and_angle_hits() -> None:
    config = ChartConfig()
    natal = compute(
        MomentInput(date(2000, 12, 12), None, "UTC", label="Unknown time"),
        config,
    )
    transit = compute(
        MomentInput(date(2026, 7, 11), time(12), "UTC"),
        config,
    )

    geometry = compute_transit_geometry(natal, transit, config)

    assert all(placement.natal_house is None for placement in geometry.placements)
    assert all(hit.natal_point not in {"asc", "mc"} for hit in geometry.aspects)


def test_transit_geometry_rejects_boundary_and_runtime_config_mismatches(
    live_geometry: TransitGeometry,
) -> None:
    natal = live_geometry.natal
    transit = live_geometry.transit

    wrong_boundary = replace(
        natal,
        meta=replace(natal.meta, boundary_version="different-boundary"),
    )
    with pytest.raises(ValueError, match="different boundary versions"):
        compute_transit_geometry(wrong_boundary, transit, ChartConfig())

    changed_orbs = replace(ChartConfig(), luminary_orb_bonus_deg=2.0)
    with pytest.raises(ValueError, match="orb modifiers"):
        compute_transit_geometry(natal, transit, changed_orbs)


def test_transit_report_is_strict_and_marks_source_moon_and_blends(
    live_geometry: TransitGeometry,
) -> None:
    blended_sun = replace(
        live_geometry.placements[0],
        blend=True,
        secondary_sign="gemini",
    )
    geometry = replace(
        live_geometry,
        placements=(blended_sun, *live_geometry.placements[1:]),
        aspects=(),
    )
    report = compose_transit_report(
        geometry,
        natal_source="saved",
        natal_id="ophiuchus-natal",
    )

    payload = json.loads(report.to_json())
    assert payload["report_version"] == 1
    assert payload["report_type"] == "transit"
    assert payload["epistemic_note"] == TRANSIT_EPISTEMIC_NOTE
    assert payload["natal"]["source"] == "saved"
    assert payload["natal"]["id"] == "ophiuchus-natal"
    assert payload["warnings"][0] == TRANSIT_MOON_WARNING
    assert next(item for item in payload["placements"] if item["id"] == "moon")[
        "time_sensitive"
    ] is True

    markdown = report.to_markdown()
    assert "# Sky ↔ Natal transit study: Ophiuchus natal" in markdown
    assert "Moving sky at" in markdown
    assert TRANSIT_EPISTEMIC_NOTE in markdown
    assert TRANSIT_MOON_WARNING in markdown
    assert "not predictions" in markdown
    assert "↔ Gemini" in markdown
    assert "No configured major sky–natal transit aspects were found." in markdown

    invalid = replace(
        report,
        placements=(replace(blended_sun, degree_in_sign=float("nan")),),
    )
    with pytest.raises(ValueError, match="Out of range float"):
        invalid.to_json()


def test_transit_interpretations_surface_ready_stub_and_missing_in_force_order(
    tmp_path: Path,
    live_geometry: TransitGeometry,
) -> None:
    # Deliberately reverse the desired order. The report must lead with force,
    # then exactness, while keeping transit and natal roles explicit.
    aspects = (
        TransitAspectHit(
            "uranus", "neptune", "opposition", 178.0, 6.0, 2.0, 0.60, True
        ),
        TransitAspectHit(
            "uranus", "uranus", "square", 89.7, 5.0, 0.3, 0.70, False
        ),
        TransitAspectHit("sun", "asc", "trine", 120.5, 9.0, 0.5, 0.80, False),
        TransitAspectHit("sun", "sun", "conjunction", 0.1, 9.0, 0.1, 0.95, True),
    )
    geometry = replace(live_geometry, aspects=aspects)
    store = _seeded_store(tmp_path)
    try:
        report = compose_transit_report(geometry, store)
    finally:
        store.close()

    ordered = [
        (
            item["aspect"]["transit_body"],
            item["aspect"]["natal_point"],
            item["reading"]["status"],
        )
        for item in report.relationships
    ]
    assert ordered == [
        ("sun", "sun", "ready"),
        ("sun", "asc", "ready"),
        ("uranus", "uranus", "stub"),
        ("uranus", "neptune", "stub"),
    ]
    assert {(gap.key, gap.kind) for gap in report.gaps} == {
        ("aspect:neptune:opposition:uranus", "stub"),
        ("aspect:uranus:square:uranus", "stub"),
    }
    markdown = report.to_markdown()
    # Titles include Midpoint sign character when placements are known.
    sun_self = next(
        line
        for line in markdown.splitlines()
        if line.startswith("#### Transit Sun") and "conjunction natal Sun" in line
    )
    sun_asc = next(
        line
        for line in markdown.splitlines()
        if line.startswith("#### Transit Sun") and "trine natal Ascendant" in line
    )
    assert markdown.index(sun_self) < markdown.index(sun_asc)
    assert "### Same-body sky–natal contacts" in markdown
    assert "### Other sky–natal contacts" in markdown
    assert "same planetary principle across two chart moments" in markdown
    assert "interpretation record missing" not in markdown
    assert "_(stub)_" in markdown
    # Sign-colored synthesis is attached when both sides have signs.
    assert "Midpoint" in markdown or "sign character" in markdown.lower()


def test_live_transit_golden_has_uranus_conjunct_natal_jupiter(
    live_geometry: TransitGeometry,
) -> None:
    hit = next(
        item
        for item in live_geometry.aspects
        if item.transit_body == "uranus"
        and item.natal_point == "jupiter"
        and item.aspect_id == "conjunction"
    )

    assert hit.exactness == pytest.approx(0.39703, abs=0.0003)
    assert hit.exactness < 1.0
    assert hit.applying is True


def test_natal_house_overlay_uses_a_common_j2000_frame_near_a_cusp() -> None:
    config = ChartConfig()
    natal = compute(
        MomentInput(date(1950, 1, 1), time(12), "UTC", 0.0, 0.0, "Natal"),
        config,
    )
    transit = compute(
        MomentInput(date(2050, 1, 1), time(12), "UTC", label="Transit"),
        config,
    )

    geometry = compute_transit_geometry(natal, transit, config)
    venus_placement = next(item for item in geometry.placements if item.id == "venus")
    natal_asc = next(item for item in natal.points if item.id == "asc")
    transit_venus = next(item for item in transit.points if item.id == "venus")

    assert venus_placement.natal_house == 9
    assert assign_house(transit_venus.lon_date, natal_asc.lon_date) == 10
    assert assign_house(transit_venus.lon_j2000, natal_asc.lon_j2000) == 9
