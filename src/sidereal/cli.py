"""Command-line interface for chart calculation and interpretation data."""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass, replace
from datetime import date, datetime, time
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence


DEFAULT_DB_PATH = Path("data/sidereal.db")
DEFAULT_CHARTS_PATH = Path("charts")


def _date_value(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; expected YYYY-MM-DD"
        ) from exc


def _sky_day_date_value(value: str) -> date:
    from .skyday import parse_skyday_date

    try:
        return parse_skyday_date(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _time_value(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid time {value!r}; expected HH:MM or HH:MM:SS"
        ) from exc
    if parsed.tzinfo is not None:
        raise argparse.ArgumentTypeError(
            "--time must be a local wall-clock time without an offset; use --tz"
        )
    return parsed


def _when_value(value: str) -> datetime:
    from .skypack import parse_local_datetime

    try:
        return parse_local_datetime(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _comparison_value(value: str) -> tuple[str, ...]:
    from .comparison import parse_comparison_systems

    try:
        return parse_comparison_systems(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid positive integer: {value!r}"
        ) from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid non-negative integer: {value!r}"
        ) from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative integer")
    return parsed


def _db_default() -> Path:
    configured = os.environ.get("SIDEREAL_DB") or os.environ.get("SIDEREAL_DB_PATH")
    return Path(configured).expanduser() if configured else DEFAULT_DB_PATH


def _charts_default() -> Path:
    configured = os.environ.get("SIDEREAL_CHARTS_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_CHARTS_PATH


def build_parser() -> argparse.ArgumentParser:
    """Build the stable v1 command-line grammar."""

    parser = argparse.ArgumentParser(
        prog="sidereal",
        description=(
            "Compute a 13-sign Midpoint chart and join symbolic study notes."
        ),
    )
    parser.set_defaults(handler=None)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    chart = commands.add_parser("chart", help="compute a chart and reports")
    chart.add_argument("--date", required=True, type=_date_value, dest="local_date")
    chart.add_argument("--time", type=_time_value, dest="local_time")
    chart.add_argument(
        "--tz",
        required=True,
        help="IANA timezone (for example America/New_York) or UTC offset",
    )
    chart.add_argument(
        "--fold",
        choices=(0, 1),
        type=int,
        help="choose the first (0) or second (1) occurrence of an ambiguous local time",
    )
    chart.add_argument("--lat", type=float, help="latitude in decimal degrees")
    chart.add_argument("--lon", type=float, help="longitude in decimal degrees")
    chart.add_argument("--label", default="", help="chart label")
    chart.add_argument("--out", type=Path, help="write the full JSON report")
    chart.add_argument("--md", type=Path, help="write the Markdown report")
    chart.add_argument(
        "--svg",
        type=Path,
        help="write a standalone 13-sign wheel (default: beside --out)",
    )
    chart.add_argument(
        "--no-houses",
        action="store_true",
        help="suppress houses and angles even when time/location are supplied",
    )
    chart.add_argument(
        "--db",
        type=Path,
        default=_db_default(),
        help="interpretation SQLite database (default: %(default)s)",
    )
    chart.add_argument(
        "--boundary-path",
        type=Path,
        help="override the packaged Midpoint boundary JSON",
    )
    chart.add_argument(
        "--ephe-path",
        type=Path,
        help="directory containing Swiss Ephemeris .se1 files",
    )
    chart.add_argument(
        "--require-swiss-ephemeris",
        action="store_true",
        help="fail instead of accepting Swiss Ephemeris' Moshier fallback",
    )
    chart.add_argument(
        "--compare",
        type=_comparison_value,
        dest="comparison_systems",
        help="compare Midpoint labels with tropical (tropical or midpoint,tropical)",
    )
    chart.set_defaults(handler=_run_chart)

    save = commands.add_parser("save", help="save chart geometry to the local library")
    _add_saved_moment_arguments(save)
    save.add_argument("--label", required=True, help="saved chart label")
    save.add_argument(
        "--no-houses",
        action="store_true",
        help="suppress houses and angles even when time/location are supplied",
    )
    save.add_argument(
        "--boundary-path",
        type=Path,
        help="override the packaged Midpoint boundary JSON",
    )
    save.add_argument(
        "--ephe-path",
        type=Path,
        help="directory containing Swiss Ephemeris .se1 files",
    )
    save.add_argument(
        "--require-swiss-ephemeris",
        action="store_true",
        help="fail instead of accepting Swiss Ephemeris' Moshier fallback",
    )
    save.add_argument(
        "--compare",
        type=_comparison_value,
        dest="comparison_systems",
        help="remember a Midpoint/tropical comparison with this chart",
    )
    _add_charts_argument(save)
    save.set_defaults(handler=_run_save)

    list_command = commands.add_parser("list", help="list locally saved charts")
    _add_charts_argument(list_command)
    list_command.set_defaults(handler=_run_list)

    show = commands.add_parser("show", help="show a saved chart geometry snapshot")
    show.add_argument("chart", help="saved chart id or label")
    show.add_argument("--out", type=Path, help="write the saved JSON record")
    show.add_argument("--md", type=Path, help="write a Markdown geometry summary")
    _add_charts_argument(show)
    show.set_defaults(handler=_run_show)

    interpret = commands.add_parser(
        "interpret",
        help="re-compose a saved geometry snapshot with the current interpretation DB",
    )
    interpret.add_argument("chart", help="saved chart id or label")
    interpret.add_argument("--out", type=Path, help="write the full JSON report")
    interpret.add_argument("--md", type=Path, help="write the Markdown report")
    _add_db_argument(interpret)
    _add_charts_argument(interpret)
    interpret.set_defaults(handler=_run_interpret)

    transit = commands.add_parser(
        "transit",
        help="study a moving sky against saved or inline natal geometry",
    )
    natal_source = transit.add_mutually_exclusive_group(required=True)
    natal_source.add_argument(
        "--natal",
        help="saved natal chart id or label",
    )
    natal_source.add_argument(
        "--natal-date",
        type=_date_value,
        help="inline natal civil date (YYYY-MM-DD)",
    )
    transit.add_argument("--natal-time", type=_time_value)
    transit.add_argument("--natal-tz", help="inline natal IANA timezone or UTC offset")
    transit.add_argument("--natal-fold", choices=(0, 1), type=int)
    transit.add_argument("--natal-lat", type=float)
    transit.add_argument("--natal-lon", type=float)
    transit.add_argument("--natal-label")
    transit.add_argument("--date", required=True, type=_date_value, dest="local_date")
    transit.add_argument("--time", required=True, type=_time_value, dest="local_time")
    transit.add_argument(
        "--tz",
        required=True,
        help="transit IANA timezone (for example America/New_York) or UTC offset",
    )
    transit.add_argument("--fold", choices=(0, 1), type=int)
    transit.add_argument("--lat", type=float, help="optional transit latitude")
    transit.add_argument("--lon", type=float, help="optional transit longitude")
    transit.add_argument("--label", default="Transit", help="transit moment label")
    transit.add_argument(
        "--save",
        action="store_true",
        help="save the study to charts/transits/ for later reopen or agent context",
    )
    transit.add_argument(
        "--save-label",
        help="label for the saved transit snapshot (default: natal · transit label)",
    )
    transit.add_argument(
        "--save-id",
        help="optional stable id for the saved transit snapshot",
    )
    transit.add_argument("--out", type=Path, help="write the transit JSON report")
    transit.add_argument("--md", type=Path, help="write the transit Markdown report")
    transit.add_argument(
        "--svg",
        type=Path,
        help="write a natal wheel with moving-sky overlay (default: beside --out)",
    )
    transit.add_argument(
        "--boundary-path",
        type=Path,
        help="override the packaged Midpoint boundary JSON",
    )
    transit.add_argument(
        "--ephe-path",
        type=Path,
        help="directory containing Swiss Ephemeris .se1 files",
    )
    transit.add_argument(
        "--require-swiss-ephemeris",
        action="store_true",
        help="fail instead of accepting Swiss Ephemeris' Moshier fallback",
    )
    _add_db_argument(transit)
    _add_charts_argument(transit)
    transit.set_defaults(handler=_run_transit)

    skypack = commands.add_parser(
        "skypack",
        help="export local sky and natal geometry as skypack_v2 JSON",
    )
    skypack.add_argument(
        "--natal",
        required=True,
        help="saved natal chart id or label",
    )
    skypack.add_argument(
        "--when",
        type=_when_value,
        metavar="ISO_LOCAL",
        help="moving-sky local datetime (default: now)",
    )
    skypack.add_argument(
        "--tz",
        help="IANA timezone or UTC offset (default: saved natal timezone)",
    )
    skypack.add_argument(
        "--ephe-path",
        type=Path,
        help="directory containing Swiss Ephemeris .se1 files",
    )
    skypack.add_argument("-o", "--out", type=Path, help="write pretty JSON")
    _add_charts_argument(skypack)
    skypack.set_defaults(handler=_run_skypack)

    sky_day = commands.add_parser(
        "sky-day",
        help="export public natal-free daily sky geometry as skyday_v1 JSON",
    )
    sky_day.add_argument(
        "--tz",
        default="UTC",
        help="IANA timezone for the civil day boundary (default: %(default)s)",
    )
    sky_day.add_argument(
        "--date",
        type=_sky_day_date_value,
        dest="cache_date",
        help="civil cache date (default: today in --tz)",
    )
    sky_day.add_argument(
        "--boundary-path",
        type=Path,
        help="override the packaged Midpoint boundary JSON",
    )
    sky_day.add_argument(
        "--ephe-path",
        type=Path,
        help="directory containing Swiss Ephemeris .se1 files",
    )
    sky_day.add_argument(
        "--require-swiss-ephemeris",
        action="store_true",
        help="fail instead of accepting Swiss Ephemeris' Moshier fallback",
    )
    sky_day.add_argument("-o", "--out", type=Path, help="write pretty JSON")
    sky_day.set_defaults(handler=_run_sky_day)

    transit_list = commands.add_parser(
        "transit-list",
        help="list saved transit study snapshots",
    )
    _add_charts_argument(transit_list)
    transit_list.set_defaults(handler=_run_transit_list)

    transit_show = commands.add_parser(
        "transit-show",
        help="print a saved transit snapshot (JSON) for agent/human context",
    )
    transit_show.add_argument("snapshot", help="saved transit id or label")
    transit_show.add_argument(
        "--md-only",
        action="store_true",
        help="print only the companion markdown context pack",
    )
    transit_show.add_argument("--out", type=Path, help="write the snapshot JSON")
    transit_show.add_argument("--md", type=Path, help="write the companion markdown")
    _add_charts_argument(transit_show)
    transit_show.set_defaults(handler=_run_transit_show)

    synastry = commands.add_parser(
        "synastry",
        help="compare two fixed saved or inline natal/event charts",
    )
    source_a = synastry.add_mutually_exclusive_group(required=True)
    source_a.add_argument("--a", help="saved chart A id or label")
    source_a.add_argument("--a-date", type=_date_value, help="inline chart A date")
    source_b = synastry.add_mutually_exclusive_group(required=True)
    source_b.add_argument("--b", help="saved chart B id or label")
    source_b.add_argument("--b-date", type=_date_value, help="inline chart B date")
    for prefix, label in (("a", "chart A"), ("b", "chart B")):
        synastry.add_argument(f"--{prefix}-time", type=_time_value)
        synastry.add_argument(
            f"--{prefix}-tz",
            help=f"inline {label} IANA timezone or UTC offset",
        )
        synastry.add_argument(f"--{prefix}-fold", choices=(0, 1), type=int)
        synastry.add_argument(f"--{prefix}-lat", type=float)
        synastry.add_argument(f"--{prefix}-lon", type=float)
        synastry.add_argument(f"--{prefix}-label")
    synastry.add_argument("--out", type=Path, help="write the synastry JSON report")
    synastry.add_argument("--md", type=Path, help="write the synastry Markdown report")
    synastry.add_argument(
        "--boundary-path",
        type=Path,
        help="override the packaged Midpoint boundary JSON for inline charts",
    )
    synastry.add_argument(
        "--ephe-path",
        type=Path,
        help="directory containing Swiss Ephemeris .se1 files",
    )
    synastry.add_argument(
        "--require-swiss-ephemeris",
        action="store_true",
        help="fail instead of accepting Swiss Ephemeris' Moshier fallback",
    )
    _add_db_argument(synastry)
    _add_charts_argument(synastry)
    synastry.set_defaults(handler=_run_synastry)

    db = commands.add_parser("db", help="manage interpretation records")
    db_commands = db.add_subparsers(dest="db_command", metavar="DB_COMMAND")

    db_init = db_commands.add_parser("init", help="create the SQLite schema")
    _add_db_argument(db_init)
    db_init.set_defaults(handler=_run_db_init)

    db_import = db_commands.add_parser("import", help="import a seed file/directory")
    db_import.add_argument(
        "source",
        nargs="?",
        type=Path,
        help="JSON seed file/directory (default: packaged seeds)",
    )
    _add_db_argument(db_import)
    db_import.set_defaults(handler=_run_db_import)

    db_gaps = db_commands.add_parser("gaps", help="audit missing and stub records")
    _add_db_argument(db_gaps)
    gap_scope = db_gaps.add_mutually_exclusive_group()
    gap_scope.add_argument(
        "--chart",
        type=Path,
        help="scope the audit to interpretation keys in a full report JSON",
    )
    gap_scope.add_argument(
        "--chart-id",
        help="scope the audit to a saved chart id or label",
    )
    _add_charts_argument(db_gaps)
    db_gaps.set_defaults(handler=_run_db_gaps)

    db_get = db_commands.add_parser("get", help="print one interpretation record")
    db_get.add_argument("key", help="canonical interpretation id")
    _add_db_argument(db_get)
    db_get.set_defaults(handler=_run_db_get)

    ai_seed = commands.add_parser(
        "ai-seed",
        help="author shared interpretation gaps with the configured AI service",
    )
    ai_seed_commands = ai_seed.add_subparsers(
        dest="ai_seed_command",
        metavar="AI_SEED_COMMAND",
    )

    ai_seed_dry_run = ai_seed_commands.add_parser(
        "dry-run",
        help="print the generated request without calling the AI service",
    )
    ai_seed_dry_run.add_argument(
        "--id",
        required=True,
        dest="entry_id",
        help="canonical interpretation id",
    )
    ai_seed_dry_run.set_defaults(handler=_run_ai_seed_dry_run)

    ai_seed_fill = ai_seed_commands.add_parser(
        "fill",
        help="generate and store one missing or stub interpretation",
    )
    ai_seed_fill.add_argument(
        "--id",
        required=True,
        dest="entry_id",
        help="canonical interpretation id",
    )
    _add_db_argument(ai_seed_fill)
    ai_seed_fill.set_defaults(handler=_run_ai_seed_fill)

    ai_seed_fill_gaps = ai_seed_commands.add_parser(
        "fill-gaps",
        help="generate and store a bounded batch of interpretation gaps",
    )
    ai_seed_fill_gaps.add_argument(
        "--limit",
        required=True,
        type=_positive_int,
        help="maximum number of gaps to fill",
    )
    _add_db_argument(ai_seed_fill_gaps)
    ai_seed_fill_gaps.set_defaults(handler=_run_ai_seed_fill_gaps)

    ai_seed_export = ai_seed_commands.add_parser(
        "export-prompts",
        help="export key-free prompt payloads for an offline author",
    )
    ai_seed_export.add_argument(
        "--limit",
        required=True,
        type=_positive_int,
        help="maximum number of supported gaps to export",
    )
    ai_seed_export.add_argument(
        "-o",
        "--output",
        required=True,
        type=Path,
        dest="out",
        help="write one prompt payload per JSONL line",
    )
    ai_seed_export.add_argument(
        "--few-shot",
        type=_nonnegative_int,
        default=0,
        help="attach up to N ready same-type examples (default: %(default)s)",
    )
    ai_seed_export.add_argument(
        "--notes-dir",
        type=Path,
        help="attach relevant .md/.markdown/.txt cultural source notes",
    )
    _add_db_argument(ai_seed_export)
    ai_seed_export.set_defaults(handler=_run_ai_seed_export_prompts)

    ai_seed_apply = ai_seed_commands.add_parser(
        "apply-json",
        help="validate and store records authored by an offline model",
    )
    ai_seed_apply.add_argument(
        "--file",
        required=True,
        type=Path,
        help="generated record or schema-versioned record batch",
    )
    _add_db_argument(ai_seed_apply)
    ai_seed_apply.set_defaults(handler=_run_ai_seed_apply_json)

    serve = commands.add_parser(
        "serve",
        help="serve the local browser UI and JSON API",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address (default: %(default)s; non-loopback requires --allow-lan)",
    )
    serve.add_argument("--port", type=int, default=8742, help="TCP port (default: %(default)s)")
    serve.add_argument(
        "--allow-lan",
        action="store_true",
        help="explicitly permit a non-loopback bind; exposes sensitive chart data",
    )
    serve.add_argument(
        "--trusted-host",
        action="append",
        default=[],
        help="allow an exact additional Host header (repeatable; no wildcards)",
    )
    serve.add_argument("--boundary-path", type=Path)
    serve.add_argument("--ephe-path", type=Path)
    serve.add_argument("--require-swiss-ephemeris", action="store_true")
    _add_db_argument(serve)
    _add_charts_argument(serve)
    serve.set_defaults(handler=_run_serve)

    return parser


def _add_saved_moment_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date", required=True, type=_date_value, dest="local_date")
    parser.add_argument("--time", type=_time_value, dest="local_time")
    parser.add_argument(
        "--tz",
        required=True,
        help="IANA timezone (for example America/New_York) or UTC offset",
    )
    parser.add_argument(
        "--fold",
        choices=(0, 1),
        type=int,
        help="choose the first (0) or second (1) occurrence of an ambiguous local time",
    )
    parser.add_argument("--lat", type=float, help="latitude in decimal degrees")
    parser.add_argument("--lon", type=float, help="longitude in decimal degrees")


def _add_charts_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--charts-dir",
        type=Path,
        default=_charts_default(),
        help="local saved-chart directory (default: %(default)s)",
    )


def _add_db_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        type=Path,
        default=_db_default(),
        help="SQLite database path (default: %(default)s)",
    )


def _validate_location(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    _validate_coordinate_pair(parser, args.lat, args.lon)


def _validate_coordinate_pair(
    parser: argparse.ArgumentParser,
    lat: float | None,
    lon: float | None,
    *,
    prefix: str = "",
) -> None:
    option = f"--{prefix}" if prefix else "--"
    if (lat is None) != (lon is None):
        parser.error(f"{option}lat and {option}lon must be provided together")
    if lat is not None and not -90.0 < lat < 90.0:
        parser.error(f"{option}lat must be strictly between -90 and 90 degrees")
    if lon is not None and not -180.0 <= lon <= 180.0:
        parser.error(f"{option}lon must be between -180 and 180 degrees")


def _run_chart(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    _validate_location(parser, args)
    svg_path = _resolved_svg_path(args.svg, args.out, args.md)
    _validate_output_paths(
        parser,
        (("--out", args.out), ("--md", args.md), ("--svg", svg_path)),
    )

    # Imports stay local so `python -m sidereal --help` and DB maintenance do
    # not initialize Swiss Ephemeris or require ephemeris files.
    from .chart import compute
    from .comparison import build_comparison
    from .config import ChartConfig
    from .interpret.compose import compose_report
    from .interpret.store import InterpretationStore
    from .types import MomentInput
    from .wheel import render_svg

    moment = MomentInput(
        local_date=args.local_date,
        local_time=args.local_time,
        tz=args.tz,
        lat=args.lat,
        lon=args.lon,
        label=args.label,
        fold=args.fold,
    )
    config = ChartConfig(
        boundary_path=args.boundary_path,
        ephe_path=args.ephe_path,
        require_swiss_ephemeris=args.require_swiss_ephemeris,
        include_houses=not args.no_houses,
    )
    chart = compute(moment, config)
    comparison = (
        build_comparison(chart, args.comparison_systems)
        if args.comparison_systems is not None
        else None
    )

    db_path = args.db.expanduser()
    if db_path.is_file():
        with InterpretationStore(db_path) as store:
            report = compose_report(chart, store, comparison=comparison)
    else:
        report = compose_report(chart, None, comparison=comparison)

    json_text = report.to_json(indent=2)
    markdown_text = report.to_markdown()
    if args.md is not None and svg_path is not None:
        markdown_text = _markdown_with_wheel(
            markdown_text,
            svg_path=svg_path,
            markdown_path=args.md,
            title="13-sign Midpoint wheel",
        )
    wrote_output = False
    if args.out is not None:
        _write_text(args.out, json_text)
        wrote_output = True
    if args.md is not None:
        _write_text(args.md, markdown_text)
        wrote_output = True
    if svg_path is not None:
        _write_text(svg_path, render_svg(chart))
        wrote_output = True
    if not wrote_output:
        print(json_text)
    return 0


def _run_save(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    _validate_location(parser, args)
    if not args.label.strip():
        parser.error("--label must not be blank")

    from .chart import compute
    from .config import ChartConfig
    from .library import save_chart
    from .types import MomentInput

    moment = MomentInput(
        local_date=args.local_date,
        local_time=args.local_time,
        tz=args.tz,
        lat=args.lat,
        lon=args.lon,
        label=args.label.strip(),
        fold=args.fold,
    )
    config = ChartConfig(
        boundary_path=args.boundary_path,
        ephe_path=args.ephe_path,
        require_swiss_ephemeris=args.require_swiss_ephemeris,
        include_houses=not args.no_houses,
    )
    chart = compute(moment, config)
    systems = args.comparison_systems or (chart.meta.zodiac_system,)
    record = save_chart(
        chart,
        config,
        charts_dir=args.charts_dir.expanduser(),
        systems=systems,
    )
    print(
        json.dumps(
            {
                "id": record.id,
                "label": record.label,
                "path": str(record.source_path),
                "systems": list(record.systems),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _run_list(args: argparse.Namespace, _parser: argparse.ArgumentParser) -> int:
    from .library import list_charts

    records = list_charts(args.charts_dir.expanduser())
    print("ID\tLABEL\tLOCAL DATETIME\tTZ\tSYSTEMS")
    for record in records:
        values = (
            record.id,
            record.label,
            record.local_datetime,
            record.tz,
            ",".join(record.systems),
        )
        print("\t".join(_single_line(value) for value in values))
    return 0


def _run_show(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.out is not None and args.md is not None and _same_output_path(args.out, args.md):
        parser.error("--out and --md must refer to different files")

    from .library import load_chart

    record = load_chart(args.chart, args.charts_dir.expanduser())
    _reject_saved_chart_overwrite(parser, record.source_path, args.out, args.md)
    wrote_output = False
    if args.out is not None:
        _write_text(args.out, record.to_json(indent=2))
        wrote_output = True
    if args.md is not None:
        _write_text(args.md, _saved_chart_markdown(record))
        wrote_output = True
    if not wrote_output:
        print(record.to_json(indent=2))
    return 0


def _run_interpret(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.out is not None and args.md is not None and _same_output_path(args.out, args.md):
        parser.error("--out and --md must refer to different files")

    from .comparison import build_comparison
    from .interpret.compose import compose_report
    from .interpret.store import InterpretationStore
    from .library import load_chart, update_last_report_path

    record = load_chart(args.chart, args.charts_dir.expanduser())
    _reject_saved_chart_overwrite(parser, record.source_path, args.out, args.md)
    chart = record.chart_object()
    comparison = (
        build_comparison(chart, record.systems)
        if "tropical" in record.systems
        else None
    )
    db_path = args.db.expanduser()
    if db_path.is_file():
        with InterpretationStore(db_path) as store:
            report = compose_report(chart, store, comparison=comparison)
    else:
        report = compose_report(chart, None, comparison=comparison)

    json_text = report.to_json(indent=2)
    markdown_text = report.to_markdown()
    wrote_output = False
    if args.out is not None:
        _write_text(args.out, json_text)
        wrote_output = True
    if args.md is not None:
        _write_text(args.md, markdown_text)
        wrote_output = True
    if wrote_output:
        last_path = args.md if args.md is not None else args.out
        update_last_report_path(
            record.id,
            last_path,
            charts_dir=args.charts_dir.expanduser(),
        )
    else:
        print(json_text)
    return 0


def _run_transit(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    _validate_location(parser, args)
    _validate_coordinate_pair(
        parser,
        args.natal_lat,
        args.natal_lon,
        prefix="natal-",
    )
    svg_path = _resolved_svg_path(args.svg, args.out, args.md)
    _validate_output_paths(
        parser,
        (("--out", args.out), ("--md", args.md), ("--svg", svg_path)),
    )

    from .chart import compute
    from .config import ChartConfig
    from .interpret.store import InterpretationStore
    from .interpret.transit import calculate_transit_study
    from .library import load_chart
    from .types import MomentInput
    from .wheel import render_svg

    natal_id: str | None = None
    natal_source = "inline"
    saved_source_path: Path | None = None
    if args.natal is not None:
        inline_values = (
            args.natal_time,
            args.natal_tz,
            args.natal_fold,
            args.natal_lat,
            args.natal_lon,
            args.natal_label,
        )
        if any(value is not None for value in inline_values):
            parser.error("--natal cannot be combined with inline --natal-* options")
        record = load_chart(args.natal, args.charts_dir.expanduser())
        natal = record.chart_object()
        base_config = record.chart_config()
        natal_id = record.id
        natal_source = "saved"
        saved_source_path = record.source_path
    else:
        if not args.natal_tz:
            parser.error("--natal-tz is required with --natal-date")
        if args.natal_fold is not None and args.natal_time is None:
            parser.error("--natal-fold requires --natal-time")
        base_config = ChartConfig(
            boundary_path=args.boundary_path,
            ephe_path=args.ephe_path,
            require_swiss_ephemeris=args.require_swiss_ephemeris,
            include_houses=True,
        )
        natal_moment = MomentInput(
            local_date=args.natal_date,
            local_time=args.natal_time,
            tz=args.natal_tz,
            lat=args.natal_lat,
            lon=args.natal_lon,
            label=(args.natal_label or "Inline natal").strip(),
            fold=args.natal_fold,
        )
        natal = compute(natal_moment, base_config)

    if saved_source_path is not None:
        _reject_saved_chart_overwrite(
            parser,
            saved_source_path,
            args.out,
            args.md,
            svg_path,
        )
    transit_config = replace(
        base_config,
        boundary_path=(
            args.boundary_path
            if args.boundary_path is not None
            else base_config.boundary_path
        ),
        ephe_path=(args.ephe_path if args.ephe_path is not None else base_config.ephe_path),
        require_swiss_ephemeris=(
            args.require_swiss_ephemeris
            or base_config.require_swiss_ephemeris
        ),
        include_houses=args.lat is not None,
        include_patterns=False,
    )
    transit_moment = MomentInput(
        local_date=args.local_date,
        local_time=args.local_time,
        tz=args.tz,
        lat=args.lat,
        lon=args.lon,
        label=args.label.strip(),
        fold=args.fold,
    )

    db_path = args.db.expanduser()
    if db_path.is_file():
        with InterpretationStore(db_path) as store:
            report, geometry = calculate_transit_study(
                natal,
                transit_moment,
                transit_config,
                store,
                natal_source=natal_source,
                natal_id=natal_id,
            )
    else:
        report, geometry = calculate_transit_study(
            natal,
            transit_moment,
            transit_config,
            None,
            natal_source=natal_source,
            natal_id=natal_id,
        )

    json_text = report.to_json(indent=2)
    markdown_text = report.to_markdown()
    if args.md is not None and svg_path is not None:
        markdown_text = _markdown_with_wheel(
            markdown_text,
            svg_path=svg_path,
            markdown_path=args.md,
            title="Natal wheel with moving-sky overlay",
        )
    saved_summary: dict[str, Any] | None = None
    if getattr(args, "save", False):
        from .transit_library import save_transit_snapshot

        report_dict = report.to_dict()
        save_label = (args.save_label or "").strip()
        if not save_label:
            natal_label = str(report_dict.get("natal", {}).get("label") or "natal")
            transit_label = str(report_dict.get("transit", {}).get("label") or "transit")
            save_label = f"{natal_label} · {transit_label}"
        snapshot = save_transit_snapshot(
            report_dict,
            label=save_label,
            markdown=report.to_markdown(),
            charts_dir=args.charts_dir.expanduser(),
            snapshot_id=(args.save_id or None),
            natal_id=natal_id,
        )
        saved_summary = snapshot.summary_dict()
    wrote_output = False
    if args.out is not None:
        _write_text(args.out, json_text)
        wrote_output = True
    if args.md is not None:
        _write_text(args.md, markdown_text)
        wrote_output = True
    if svg_path is not None:
        _write_text(
            svg_path,
            render_svg(geometry.natal, overlay_chart=geometry.transit),
        )
        wrote_output = True
    if saved_summary is not None:
        print(json.dumps(saved_summary, ensure_ascii=False, indent=2, sort_keys=True))
        wrote_output = True
    if not wrote_output:
        print(json_text)
    return 0


def _run_skypack(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .library import load_chart
    from .skypack import build_skypack_from_saved_chart

    record = load_chart(args.natal, args.charts_dir.expanduser())
    _reject_saved_chart_overwrite(parser, record.source_path, args.out)
    payload = build_skypack_from_saved_chart(
        record,
        when=args.when,
        tz=args.tz,
        ephe_path=args.ephe_path,
    )
    json_text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    if args.out is not None:
        _write_text(args.out, json_text)
    else:
        print(json_text)
    return 0


def _run_sky_day(args: argparse.Namespace, _parser: argparse.ArgumentParser) -> int:
    from .skyday import build_skyday

    payload = build_skyday(
        tz=args.tz,
        date=args.cache_date,
        boundary_path=args.boundary_path,
        ephe_path=args.ephe_path,
        require_swiss_ephemeris=args.require_swiss_ephemeris,
    )
    json_text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    if args.out is not None:
        _write_text(args.out, json_text)
    else:
        print(json_text)
    return 0


def _run_transit_list(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .transit_library import list_transits

    rows = list_transits(args.charts_dir.expanduser())
    if not rows:
        print("No saved transit studies.")
        return 0
    print("ID\tLABEL\tNATAL\tTRANSIT\tASPECTS")
    for item in rows:
        summary = item.summary_dict()
        print(
            f"{summary['id']}\t{summary['label']}\t{summary['natal_label']}\t"
            f"{summary['transit_local_datetime']}\t{summary['relationship_count']}"
        )
    return 0


def _run_transit_show(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .transit_library import load_transit

    record = load_transit(args.snapshot, args.charts_dir.expanduser())
    if args.out is not None:
        _write_text(args.out, json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if args.md is not None:
        _write_text(args.md, record.markdown if record.markdown.endswith("\n") else record.markdown + "\n")
    if args.md_only:
        print(record.markdown if record.markdown.endswith("\n") else record.markdown + "\n", end="")
    elif args.out is None and args.md is None:
        print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_synastry(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    for prefix in ("a", "b"):
        _validate_coordinate_pair(
            parser,
            getattr(args, f"{prefix}_lat"),
            getattr(args, f"{prefix}_lon"),
            prefix=f"{prefix}-",
        )
        if getattr(args, prefix) is None:
            if not getattr(args, f"{prefix}_tz"):
                parser.error(f"--{prefix}-tz is required with --{prefix}-date")
            if (
                getattr(args, f"{prefix}_fold") is not None
                and getattr(args, f"{prefix}_time") is None
            ):
                parser.error(f"--{prefix}-fold requires --{prefix}-time")
    if args.out is not None and args.md is not None and _same_output_path(args.out, args.md):
        parser.error("--out and --md must refer to different files")

    from .chart import compute
    from .config import ChartConfig
    from .interpret.store import InterpretationStore
    from .interpret.synastry import calculate_synastry_report
    from .library import load_chart
    from .types import MomentInput

    records: dict[str, Any] = {}
    charts: dict[str, Any] = {}
    sources = {"a": "inline", "b": "inline"}
    ids: dict[str, str | None] = {"a": None, "b": None}
    source_paths: list[Path] = []

    for prefix in ("a", "b"):
        saved_identifier = getattr(args, prefix)
        if saved_identifier is None:
            continue
        inline_values = tuple(
            getattr(args, f"{prefix}_{name}")
            for name in ("time", "tz", "fold", "lat", "lon", "label")
        )
        if any(value is not None for value in inline_values):
            parser.error(
                f"--{prefix} cannot be combined with inline --{prefix}-* options"
            )
        record = load_chart(saved_identifier, args.charts_dir.expanduser())
        records[prefix] = record
        charts[prefix] = record.chart_object()
        sources[prefix] = "saved"
        ids[prefix] = record.id
        source_paths.append(record.source_path)

    base_record = records.get("a") or records.get("b")
    base_config = base_record.chart_config() if base_record is not None else ChartConfig()
    config = replace(
        base_config,
        boundary_path=(
            args.boundary_path
            if args.boundary_path is not None
            else base_config.boundary_path
        ),
        ephe_path=(args.ephe_path if args.ephe_path is not None else base_config.ephe_path),
        require_swiss_ephemeris=(
            args.require_swiss_ephemeris or base_config.require_swiss_ephemeris
        ),
        include_houses=True,
        include_patterns=False,
    )

    for prefix, fallback_label in (("a", "Chart A"), ("b", "Chart B")):
        if prefix in charts:
            continue
        tz = getattr(args, f"{prefix}_tz")
        local_time = getattr(args, f"{prefix}_time")
        fold = getattr(args, f"{prefix}_fold")
        label = (getattr(args, f"{prefix}_label") or fallback_label).strip()
        moment = MomentInput(
            local_date=getattr(args, f"{prefix}_date"),
            local_time=local_time,
            tz=tz,
            lat=getattr(args, f"{prefix}_lat"),
            lon=getattr(args, f"{prefix}_lon"),
            label=label,
            fold=fold,
        )
        charts[prefix] = compute(moment, config)

    for source_path in source_paths:
        _reject_saved_chart_overwrite(parser, source_path, args.out, args.md)

    db_path = args.db.expanduser()
    if db_path.is_file():
        with InterpretationStore(db_path) as store:
            report = calculate_synastry_report(
                charts["a"],
                charts["b"],
                config,
                store,
                source_a=sources["a"],
                id_a=ids["a"],
                source_b=sources["b"],
                id_b=ids["b"],
            )
    else:
        report = calculate_synastry_report(
            charts["a"],
            charts["b"],
            config,
            None,
            source_a=sources["a"],
            id_a=ids["a"],
            source_b=sources["b"],
            id_b=ids["b"],
        )

    json_text = report.to_json(indent=2)
    markdown_text = report.to_markdown()
    wrote_output = False
    if args.out is not None:
        _write_text(args.out, json_text)
        wrote_output = True
    if args.md is not None:
        _write_text(args.md, markdown_text)
        wrote_output = True
    if not wrote_output:
        print(json_text)
    return 0


def _run_db_init(args: argparse.Namespace, _parser: argparse.ArgumentParser) -> int:
    from .interpret.store import InterpretationStore

    path = args.db.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with InterpretationStore(path) as store:
        store.initialize()
    print(f"Initialized interpretation database: {path}")
    return 0


def _run_db_import(args: argparse.Namespace, _parser: argparse.ArgumentParser) -> int:
    from .interpret.generate_seeds import resolve_seed_directory
    from .interpret.store import InterpretationStore

    source = (
        args.source.expanduser()
        if args.source is not None
        else resolve_seed_directory()
    )
    if not source.exists():
        raise FileNotFoundError(f"Seed path does not exist: {source}")
    path = args.db.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with InterpretationStore(path) as store:
        store.initialize()
        result = store.import_path(source)
    print(json.dumps(_json_ready(result), indent=2, sort_keys=True))
    return 0


def _run_db_gaps(args: argparse.Namespace, _parser: argparse.ArgumentParser) -> int:
    from .interpret.audit import report_interpretation_ids
    from .interpret.compose import compose_report
    from .interpret.store import InterpretationStore
    from .library import load_chart

    path = _require_db(args.db)
    with InterpretationStore(path) as store:
        if args.chart is not None:
            report_payload = _read_json_object(args.chart)
            audit = store.audit(report_interpretation_ids(report_payload))
        elif args.chart_id is not None:
            record = load_chart(args.chart_id, args.charts_dir.expanduser())
            report = compose_report(record.chart_object(), store)
            audit = store.audit(report_interpretation_ids(report.to_dict()))
        else:
            audit = store.audit()
    print(json.dumps(_json_ready(audit), indent=2, sort_keys=True))
    return 0


def _run_db_get(args: argparse.Namespace, _parser: argparse.ArgumentParser) -> int:
    from .interpret.store import InterpretationStore

    path = _require_db(args.db)
    with InterpretationStore(path) as store:
        entry = store.get(args.key)
    if entry is None:
        print(f"Interpretation key not found: {args.key}", file=sys.stderr)
        return 1
    print(json.dumps(_json_ready(entry), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _run_ai_seed_dry_run(
    args: argparse.Namespace,
    _parser: argparse.ArgumentParser,
) -> int:
    from .interpret.ai_seed import dry_run_interpretation

    result = dry_run_interpretation(args.entry_id)
    print(json.dumps(_json_ready(result), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _run_ai_seed_fill(
    args: argparse.Namespace,
    _parser: argparse.ArgumentParser,
) -> int:
    from .interpret.ai_seed import fill_interpretation
    from .interpret.store import InterpretationStore

    path = _require_db(args.db)
    with InterpretationStore(path) as store:
        result = fill_interpretation(args.entry_id, store)
    print(json.dumps(_json_ready(result), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _run_ai_seed_fill_gaps(
    args: argparse.Namespace,
    _parser: argparse.ArgumentParser,
) -> int:
    from .interpret.ai_seed import fill_interpretation_gaps
    from .interpret.store import InterpretationStore

    path = _require_db(args.db)
    with InterpretationStore(path) as store:
        result = fill_interpretation_gaps(store, limit=args.limit)
    print(json.dumps(_json_ready(result), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _run_ai_seed_export_prompts(
    args: argparse.Namespace,
    _parser: argparse.ArgumentParser,
) -> int:
    from .interpret.ai_seed import export_offline_seed_prompts
    from .interpret.store import InterpretationStore

    database = _require_db(args.db)
    output = args.out.expanduser()
    if _same_output_path(output, database):
        raise ValueError("prompt output must not overwrite the interpretation database")
    with InterpretationStore(database) as store:
        records = export_offline_seed_prompts(
            store,
            limit=args.limit,
            few_shot=args.few_shot,
            notes_dir=args.notes_dir,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = "".join(
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for record in records
    )
    output.write_text(rendered, encoding="utf-8")
    print(
        json.dumps(
            {"exported": len(records), "output": str(output)},
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    )
    return 0


def _run_ai_seed_apply_json(
    args: argparse.Namespace,
    _parser: argparse.ArgumentParser,
) -> int:
    from .interpret.ai_seed import (
        apply_offline_generated_records,
        load_offline_generated_records,
    )
    from .interpret.store import InterpretationStore

    database = _require_db(args.db)
    records = load_offline_generated_records(args.file)
    with InterpretationStore(database) as store:
        result = apply_offline_generated_records(records, store)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 1 if result.invalid else 0


def _run_serve(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    import ipaddress

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    host = args.host.strip()
    if not host:
        parser.error("--host must not be blank")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.casefold() == "localhost"
    if not loopback and not args.allow_lan:
        parser.error(
            "refusing a non-loopback bind without --allow-lan; birth data is sensitive"
        )
    if not loopback:
        print(
            "WARNING: sidereal is exposed beyond localhost; legacy desk routes "
            "have no authentication.",
            file=sys.stderr,
        )

    try:
        import uvicorn
        from .web import create_app
    except ImportError as exc:
        raise RuntimeError(
            "web dependencies are not installed; run `python -m pip install -e '.[web]'`"
        ) from exc

    app = create_app(
        db_path=args.db.expanduser(),
        charts_dir=args.charts_dir.expanduser(),
        boundary_path=(
            args.boundary_path.expanduser()
            if args.boundary_path is not None
            else None
        ),
        ephe_path=(args.ephe_path.expanduser() if args.ephe_path is not None else None),
        require_swiss_ephemeris=args.require_swiss_ephemeris,
        bind_host=host,
        allow_lan=args.allow_lan,
        trusted_hosts=tuple(args.trusted_host),
    )
    uvicorn.run(app, host=host, port=args.port)
    return 0


def _require_db(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_file():
        raise FileNotFoundError(
            f"Interpretation database does not exist: {expanded}. Run `sidereal db init`."
        )
    return expanded


def _json_ready(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _write_text(path: Path, content: str) -> None:
    expanded = path.expanduser()
    expanded.parent.mkdir(parents=True, exist_ok=True)
    expanded.write_text(content.rstrip() + "\n", encoding="utf-8")


def _read_json_object(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    try:
        payload = json.loads(expanded.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Report JSON does not exist: {expanded}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read report JSON {expanded}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Report JSON must contain an object: {expanded}")
    return payload


def _same_output_path(left: Path, right: Path) -> bool:
    left_path = left.expanduser()
    right_path = right.expanduser()
    try:
        if left_path.exists() and right_path.exists():
            return left_path.samefile(right_path)
    except OSError:
        pass
    return left_path.resolve(strict=False) == right_path.resolve(strict=False)


def _resolved_svg_path(
    explicit: Path | None,
    json_path: Path | None,
    markdown_path: Path | None,
) -> Path | None:
    if explicit is not None:
        return explicit
    source = json_path if json_path is not None else markdown_path
    return source.with_suffix(".svg") if source is not None else None


def _validate_output_paths(
    parser: argparse.ArgumentParser,
    outputs: tuple[tuple[str, Path | None], ...],
) -> None:
    active = tuple((name, path) for name, path in outputs if path is not None)
    for index, (left_name, left_path) in enumerate(active):
        for right_name, right_path in active[index + 1 :]:
            if _same_output_path(left_path, right_path):
                parser.error(f"{left_name} and {right_name} must refer to different files")


def _markdown_with_wheel(
    markdown: str,
    *,
    svg_path: Path,
    markdown_path: Path,
    title: str,
) -> str:
    expanded_svg = svg_path.expanduser().resolve(strict=False)
    expanded_markdown = markdown_path.expanduser().resolve(strict=False)
    try:
        reference = Path(
            os.path.relpath(expanded_svg, start=expanded_markdown.parent)
        ).as_posix()
    except ValueError:
        reference = expanded_svg.as_posix()
    return (
        markdown.rstrip()
        + f"\n\n## {title}\n\n![{title}](<{reference}>)\n"
    )


def _single_line(value: object) -> str:
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _reject_saved_chart_overwrite(
    parser: argparse.ArgumentParser,
    source_path: Path,
    *output_paths: Path | None,
) -> None:
    if any(
        output_path is not None and _same_output_path(source_path, output_path)
        for output_path in output_paths
    ):
        parser.error("report output must not overwrite the saved chart JSON")


def _saved_chart_markdown(record: Any) -> str:
    chart = record.chart
    points = chart.get("points", ())
    cusps = chart.get("cusps") or ()
    aspects = chart.get("aspects", ())
    patterns = chart.get("patterns", ())
    lines = [
        f"# Saved chart: {record.label or 'Untitled'}",
        "",
        "This local file contains sensitive birth data; keep the charts directory private.",
        "",
        f"ID: `{record.id}`",
        f"Moment: {record.local_datetime} ({record.tz})",
        f"Systems: {', '.join(record.systems)}",
        "",
        "## Points",
        "",
    ]
    for point in points:
        if not isinstance(point, dict):
            continue
        description = (
            f"{str(point.get('id', 'unknown')).replace('_', ' ').title()}: "
            f"{str(point.get('sign', 'unknown')).replace('_', ' ').title()} "
            f"{_saved_degree(point.get('degree_in_sign'))}°"
        )
        if point.get("house") is not None:
            description += f", house {point['house']}"
        if point.get("retro"):
            description += ", retrograde"
        lines.append(f"- {description}")

    lines.extend(("", "## House cusps", ""))
    if cusps:
        for cusp in cusps:
            if not isinstance(cusp, dict):
                continue
            lines.append(
                f"- House {cusp.get('number', 'unknown')}: "
                f"{str(cusp.get('sign', 'unknown')).replace('_', ' ').title()} "
                f"{_saved_degree(cusp.get('degree_in_sign'))}°"
            )
    else:
        lines.append("Houses were not calculated for this chart.")

    lines.extend(("", "## Geometry inventory", ""))
    lines.append(f"- Major aspects: {len(aspects) if isinstance(aspects, list) else 0}")
    lines.append(f"- Structural patterns: {len(patterns) if isinstance(patterns, list) else 0}")
    lines.append(
        "- Use `sidereal interpret <id-or-label>` to join this geometry to the current interpretation database."
    )
    return "\n".join(lines).rstrip() + "\n"


def _saved_degree(value: object) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "unknown"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    handler = args.handler
    if handler is None:
        parser.print_help()
        return 2
    try:
        return int(handler(args, parser))
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        print(f"sidereal: error: {exc}", file=sys.stderr)
        return 1


__all__ = ["build_parser", "main"]
