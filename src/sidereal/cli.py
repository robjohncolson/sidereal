"""Command-line interface for chart calculation and interpretation data."""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import date, time
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


def _comparison_value(value: str) -> tuple[str, ...]:
    from .comparison import parse_comparison_systems

    try:
        return parse_comparison_systems(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _db_default() -> Path:
    configured = os.environ.get("SIDEREAL_DB_PATH")
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
    db_gaps.set_defaults(handler=_run_db_gaps)

    db_get = db_commands.add_parser("get", help="print one interpretation record")
    db_get.add_argument("key", help="canonical interpretation id")
    _add_db_argument(db_get)
    db_get.set_defaults(handler=_run_db_get)

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
    if (args.lat is None) != (args.lon is None):
        parser.error("--lat and --lon must be provided together")
    if args.lat is not None and not -90.0 < args.lat < 90.0:
        parser.error("--lat must be strictly between -90 and 90 degrees")
    if args.lon is not None and not -180.0 <= args.lon <= 180.0:
        parser.error("--lon must be between -180 and 180 degrees")


def _run_chart(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    _validate_location(parser, args)
    if args.out is not None and args.md is not None and _same_output_path(args.out, args.md):
        parser.error("--out and --md must refer to different files")

    # Imports stay local so `python -m sidereal --help` and DB maintenance do
    # not initialize Swiss Ephemeris or require ephemeris files.
    from .chart import compute
    from .comparison import build_comparison
    from .config import ChartConfig
    from .interpret.compose import compose_report
    from .interpret.store import InterpretationStore
    from .types import MomentInput

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
    from .interpret.store import InterpretationStore

    path = _require_db(args.db)
    with InterpretationStore(path) as store:
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


def _same_output_path(left: Path, right: Path) -> bool:
    left_path = left.expanduser()
    right_path = right.expanduser()
    try:
        if left_path.exists() and right_path.exists():
            return left_path.samefile(right_path)
    except OSError:
        pass
    return left_path.resolve(strict=False) == right_path.resolve(strict=False)


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
