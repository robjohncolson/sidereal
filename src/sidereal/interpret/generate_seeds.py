"""Generate checked-in interpretation seed JSON deterministically."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import site
import sys
import sysconfig
from typing import Sequence

from .schema import (
    generate_seed0_entries,
    generate_seed1_entries,
    generate_seed2_entries,
    generate_seed3_entries,
    generate_seed4_entries,
    generate_seed5_entries,
    generate_seed7_entries,
    seed_payload,
)


SEED_PATH_ENV = "SIDEREAL_SEED_PATH"


def default_seed_directory() -> Path:
    """Return the checked-in directory for development or installed data."""

    project_root = Path(__file__).resolve().parents[3]
    project_path = project_root / "data" / "seeds"
    if (project_root / "pyproject.toml").is_file() or project_path.is_dir():
        return project_path.resolve()
    user_path = Path(site.USER_BASE) / "share" / "sidereal" / "seeds"
    active_path = Path(sysconfig.get_path("data")) / "share" / "sidereal" / "seeds"
    if sys.prefix != sys.base_prefix:
        candidates = (active_path,)
    elif site.ENABLE_USER_SITE:
        candidates = (user_path, active_path)
    else:
        candidates = (active_path,)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return candidates[-1].resolve()


def resolve_seed_directory(explicit_path: str | Path | None = None) -> Path:
    """Resolve seed input without silently replacing an explicit selection."""

    if explicit_path is not None:
        return _required_seed_directory(Path(explicit_path), "explicit seed path")
    environment_path = os.environ.get(SEED_PATH_ENV)
    if environment_path:
        return _required_seed_directory(Path(environment_path), SEED_PATH_ENV)
    return _required_seed_directory(default_seed_directory(), "default seed path")


def _required_seed_directory(path: Path, label: str) -> Path:
    candidate = path.expanduser()
    if not candidate.is_dir():
        raise FileNotFoundError(f"{label} is not a directory: {candidate}")
    return candidate.resolve()


def rendered_seed_files() -> dict[str, str]:
    payloads = {
        "seed_0_inventory_v1.json": seed_payload("seed_0_inventory_v1", generate_seed0_entries()),
        "seed_1_core_v1.json": seed_payload("seed_1_core_v1", generate_seed1_entries()),
        "seed_2_personal_aspects_v1.json": seed_payload(
            "seed_2_personal_aspects_v1", generate_seed2_entries()
        ),
        "seed_3_placements_v1.json": seed_payload(
            "seed_3_placements_v1", generate_seed3_entries()
        ),
        "seed_4_placements_v1.json": seed_payload(
            "seed_4_placements_v1", generate_seed4_entries()
        ),
        "seed_5_relationships_v1.json": seed_payload(
            "seed_5_relationships_v1", generate_seed5_entries()
        ),
        "seed_7_sign_character_v1.json": seed_payload(
            "seed_7_sign_character_v1", generate_seed7_entries()
        ),
    }
    return {
        name: json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        for name, payload in payloads.items()
    }


def write_seed_files(directory: str | Path) -> tuple[Path, ...]:
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, content in rendered_seed_files().items():
        path = destination / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return tuple(written)


def check_seed_files(directory: str | Path) -> tuple[str, ...]:
    destination = Path(directory)
    mismatches: list[str] = []
    for name, expected in rendered_seed_files().items():
        path = destination / name
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            mismatches.append(name)
    return tuple(mismatches)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=default_seed_directory())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        mismatches = check_seed_files(args.output)
        if mismatches:
            parser.error("seed files differ: " + ", ".join(mismatches))
        return 0
    write_seed_files(args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "check_seed_files",
    "default_seed_directory",
    "main",
    "resolve_seed_directory",
    "rendered_seed_files",
    "write_seed_files",
]
