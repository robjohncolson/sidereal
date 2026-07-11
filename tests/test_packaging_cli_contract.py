"""Packaging and command-surface acceptance checks owned by the CLI layer."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_installable_src_package_and_tools() -> None:
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))

    assert config["build-system"]["build-backend"] == "setuptools.build_meta"
    assert config["project"]["requires-python"] == ">=3.11"
    assert any(
        dependency.startswith("pyswisseph")
        for dependency in config["project"]["dependencies"]
    )
    assert any(
        dependency.startswith("tzdata")
        for dependency in config["project"]["dependencies"]
    )
    assert any(
        dependency.startswith("pytest")
        for dependency in config["project"]["optional-dependencies"]["dev"]
    )
    assert config["project"]["scripts"]["sidereal"] == "sidereal.cli:main"
    assert config["tool"]["setuptools"]["package-dir"] == {"": "src"}


def test_required_data_is_declared_for_wheel_installation() -> None:
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))
    data_files = config["tool"]["setuptools"]["data-files"]

    assert data_files["share/sidereal/boundaries"] == ["data/boundaries/*.json"]
    assert data_files["share/sidereal/seeds"] == ["data/seeds/*.json"]
    assert (PROJECT_ROOT / "data/boundaries/midpoint_j2000_v1.json").is_file()


def test_optional_web_stack_and_static_assets_are_packaged() -> None:
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))
    web_dependencies = config["project"]["optional-dependencies"]["web"]

    assert any(item.startswith("fastapi") for item in web_dependencies)
    assert any(item.startswith("httpx>=") for item in web_dependencies)
    assert any(item.startswith("httpx2") for item in web_dependencies)
    assert any(item.startswith("uvicorn") for item in web_dependencies)
    assert config["tool"]["setuptools"]["package-data"]["sidereal.web"] == [
        "static/*.html",
        "static/*.css",
        "static/*.js",
    ]


def test_module_help_works_without_loading_the_geometry_stack() -> None:
    env = os.environ.copy()
    src = str(PROJECT_ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-m", "sidereal", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "chart" in completed.stdout
    assert "db" in completed.stdout
