from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

pytest.importorskip("swisseph")

from sidereal.cli import main


SVG = "{http://www.w3.org/2000/svg}"


def _chart_args() -> list[str]:
    return [
        "chart",
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
        "--label",
        "Wheel CLI",
    ]


def _parse_svg(path: Path) -> ElementTree.Element:
    return ElementTree.fromstring(path.read_text(encoding="utf-8"))


def _groups(root: ElementTree.Element, class_name: str) -> list[ElementTree.Element]:
    return [
        element
        for element in root.iter(f"{SVG}g")
        if class_name in element.attrib.get("class", "").split()
    ]


def test_chart_cli_writes_explicit_svg_and_markdown_reference(tmp_path: Path) -> None:
    output = tmp_path / "chart.json"
    markdown = tmp_path / "notes" / "chart.md"
    wheel = tmp_path / "images" / "wheel.svg"

    assert main(
        [
            *_chart_args(),
            "--out",
            str(output),
            "--md",
            str(markdown),
            "--svg",
            str(wheel),
        ]
    ) == 0

    assert json.loads(output.read_text(encoding="utf-8"))["chart"]
    root = _parse_svg(wheel)
    assert len(_groups(root, "sign-segment")) == 13
    assert "Ophiuchus" in "".join(root.itertext())
    assert "![13-sign Midpoint wheel](<../images/wheel.svg>)" in (
        markdown.read_text(encoding="utf-8")
    )


def test_chart_cli_derives_svg_from_json_or_markdown_and_svg_counts_as_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "auto.json"
    assert main([*_chart_args(), "--out", str(output)]) == 0
    assert output.with_suffix(".svg").is_file()
    capsys.readouterr()

    markdown = tmp_path / "markdown-only.md"
    assert main([*_chart_args(), "--md", str(markdown)]) == 0
    assert markdown.with_suffix(".svg").is_file()
    assert "markdown-only.svg" in markdown.read_text(encoding="utf-8")
    capsys.readouterr()

    explicit = tmp_path / "only.svg"
    assert main([*_chart_args(), "--svg", str(explicit)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert explicit.is_file()


def test_chart_cli_rejects_derived_or_explicit_output_collisions(
    tmp_path: Path,
) -> None:
    collision = tmp_path / "same.svg"
    with pytest.raises(SystemExit) as raised:
        main([*_chart_args(), "--out", str(collision)])
    assert raised.value.code == 2

    with pytest.raises(SystemExit) as raised:
        main(
            [
                *_chart_args(),
                "--out",
                str(tmp_path / "chart.json"),
                "--md",
                str(collision),
                "--svg",
                str(collision),
            ]
        )
    assert raised.value.code == 2


def test_transit_cli_svg_has_natal_and_moving_sky_layers(tmp_path: Path) -> None:
    wheel = tmp_path / "transit.svg"
    markdown = tmp_path / "transit.md"
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
            "--date",
            "2026-07-11",
            "--time",
            "12:00",
            "--tz",
            "UTC",
            "--md",
            str(markdown),
            "--svg",
            str(wheel),
        ]
    ) == 0
    root = _parse_svg(wheel)
    assert len(_groups(root, "point-marker-natal")) == 12
    assert len(_groups(root, "point-marker-overlay")) == 12
    assert root.find(f".//*[@id='point-natal-sun']") is not None
    assert root.find(f".//*[@id='point-overlay-sun']") is not None
    assert "moving-sky overlay" in markdown.read_text(encoding="utf-8")


def test_transit_svg_cannot_overwrite_a_saved_chart(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    charts_dir = tmp_path / "charts"
    assert main(
        [
            "save",
            "--label",
            "Protected natal",
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

    with pytest.raises(SystemExit) as raised:
        main(
            [
                "transit",
                "--natal",
                "Protected natal",
                "--charts-dir",
                str(charts_dir),
                "--date",
                "2026-07-11",
                "--time",
                "12:00",
                "--tz",
                "UTC",
                "--svg",
                saved["path"],
            ]
        )
    assert raised.value.code == 2
    assert Path(saved["path"]).is_file()


def test_web_chart_saved_interpret_and_transit_return_safe_wheels(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from sidereal.web import create_app

    client = TestClient(
        create_app(
            db_path=tmp_path / "absent.db",
            charts_dir=tmp_path / "charts",
        )
    )
    moment = {
        "date": "2000-12-12",
        "time": "12:00",
        "tz": "UTC",
        "lat": 0,
        "lon": 0,
        "label": "Web wheel",
    }

    chart_response = client.post("/api/chart", json={"moment": moment})
    assert chart_response.status_code == 200, chart_response.text
    chart_wheel = chart_response.json()["wheel"]
    assert chart_wheel["kind"] == "natal"
    assert chart_wheel["orientation"] == "ascendant_at_9_oclock"
    assert len(_groups(ElementTree.fromstring(chart_wheel["svg"]), "sign-segment")) == 13

    saved = client.post("/api/charts", json={"moment": moment}).json()
    shown = client.get(f"/api/charts/{saved['id']}")
    assert shown.status_code == 200
    assert shown.json()["wheel"]["kind"] == "natal"
    interpreted = client.post(f"/api/charts/{saved['id']}/interpret")
    assert interpreted.status_code == 200
    assert interpreted.json()["wheel"]["media_type"] == "image/svg+xml"

    transit = client.post(
        "/api/transit",
        json={
            "natal_id": saved["id"],
            "transit": {"date": "2026-07-11", "time": "12:00", "tz": "UTC"},
        },
    )
    assert transit.status_code == 200, transit.text
    transit_wheel = transit.json()["wheel"]
    assert transit_wheel["kind"] == "transit_overlay"
    transit_root = ElementTree.fromstring(transit_wheel["svg"])
    assert len(_groups(transit_root, "point-marker-overlay")) == 12

    shell = client.get("/").text
    assert "img-src 'self' data:" in shell
