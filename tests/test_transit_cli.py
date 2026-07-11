from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("swisseph")

from sidereal.cli import build_parser, main


def _transit_args(*, output: Path) -> list[str]:
    return [
        "--date",
        "2026-07-11",
        "--time",
        "12:00",
        "--tz",
        "UTC",
        "--out",
        str(output),
    ]


def test_saved_and_inline_transit_cli_share_geometry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    charts_dir = tmp_path / "charts"
    assert main(
        [
            "save",
            "--label",
            "Transit Demo",
            "--date",
            "2000-12-12",
            "--time",
            "12:00",
            "--tz",
            "UTC",
            "--lat",
            "0",
            "--lon",
            "0",
            "--charts-dir",
            str(charts_dir),
        ]
    ) == 0
    saved = json.loads(capsys.readouterr().out)

    saved_output = tmp_path / "saved-transit.json"
    saved_markdown = tmp_path / "saved-transit.md"
    assert main(
        [
            "transit",
            "--natal",
            "Transit Demo",
            "--charts-dir",
            str(charts_dir),
            *_transit_args(output=saved_output),
            "--md",
            str(saved_markdown),
        ]
    ) == 0
    saved_report = json.loads(saved_output.read_text(encoding="utf-8"))

    inline_output = tmp_path / "inline-transit.json"
    assert main(
        [
            "transit",
            "--natal-date",
            "2000-12-12",
            "--natal-time",
            "12:00",
            "--natal-tz",
            "UTC",
            "--natal-lat",
            "0",
            "--natal-lon",
            "0",
            "--natal-label",
            "Transit Demo",
            *_transit_args(output=inline_output),
        ]
    ) == 0
    inline_report = json.loads(inline_output.read_text(encoding="utf-8"))

    assert saved_report["report_type"] == "transit"
    assert saved_report["natal"]["source"] == "saved"
    assert saved_report["natal"]["id"] == saved["id"]
    assert inline_report["natal"]["source"] == "inline"
    assert inline_report["natal"]["id"] is None
    assert saved_report["placements"] == inline_report["placements"]
    assert saved_report["relationships"] == inline_report["relationships"]
    assert any(
        item["aspect"]["transit_body"] == "uranus"
        and item["aspect"]["natal_point"] == "jupiter"
        and item["aspect"]["aspect_id"] == "conjunction"
        and item["aspect"]["exactness"] < 1.0
        for item in saved_report["relationships"]
    )
    markdown = saved_markdown.read_text(encoding="utf-8")
    assert "not predictions" in markdown
    assert "Moon (time-sensitive)" in markdown


def test_unknown_time_inline_natal_omits_house_and_angle_features(
    tmp_path: Path,
) -> None:
    output = tmp_path / "unknown-time.json"
    assert main(
        [
            "transit",
            "--natal-date",
            "2000-12-12",
            "--natal-tz",
            "UTC",
            "--natal-lat",
            "0",
            "--natal-lon",
            "0",
            *_transit_args(output=output),
        ]
    ) == 0
    report = json.loads(output.read_text(encoding="utf-8"))

    assert report["natal"]["time_known"] is False
    assert all(item["natal_house"] is None for item in report["placements"])
    assert all(
        item["aspect"]["natal_point"] not in {"asc", "mc"}
        for item in report["relationships"]
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["transit", "--date", "2026-07-11", "--time", "12:00", "--tz", "UTC"],
        [
            "transit",
            "--natal",
            "Saved",
            "--natal-date",
            "2000-01-01",
            "--date",
            "2026-07-11",
            "--time",
            "12:00",
            "--tz",
            "UTC",
        ],
        [
            "transit",
            "--natal-date",
            "2000-01-01",
            "--natal-tz",
            "UTC",
            "--date",
            "2026-07-11",
            "--tz",
            "UTC",
        ],
    ],
)
def test_transit_parser_requires_one_natal_source_and_transit_time(
    arguments: list[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(arguments)
    assert raised.value.code == 2


@pytest.mark.parametrize(
    "extra",
    [
        ["--natal-lat", "0"],
        ["--lat", "0"],
        ["--natal-fold", "0"],
    ],
)
def test_inline_transit_rejects_incomplete_coordinates_or_fold(
    extra: list[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "transit",
                "--natal-date",
                "2000-01-01",
                "--natal-tz",
                "UTC",
                "--date",
                "2026-07-11",
                "--time",
                "12:00",
                "--tz",
                "UTC",
                *extra,
            ]
        )
    assert raised.value.code == 2


def test_saved_natal_rejects_inline_natal_options(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "transit",
                "--natal",
                "Saved",
                "--natal-label",
                "Ignored inline label",
                "--date",
                "2026-07-11",
                "--time",
                "12:00",
                "--tz",
                "UTC",
                "--charts-dir",
                str(tmp_path / "charts"),
            ]
        )
    assert raised.value.code == 2
