"""Tests for the manual release version contract."""

from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from packaging.version import Version

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_release_version.py"
_ROOT = _SCRIPT.parents[1]
validate_release_version = cast(
    Callable[[str, str], None],
    runpy.run_path(str(_SCRIPT))["validate_release_version"],
)


def test_accepts_matching_codex_rosetta_release_version():
    validate_release_version("0.144.0.r0", "v0.144.0.r0")


def test_accepts_matching_codex_prerelease_version():
    source_version = "0.145.0-alpha.23.r0"

    validate_release_version(source_version, f"v{source_version}")

    assert str(Version(source_version)) == "0.145.0a23.post0"


@pytest.mark.parametrize(
    ("source_version", "tag"),
    [
        ("0.144.0", "0.144.0"),
        ("0.144.0.r0", "0.144.0.r0"),
        ("0.144.0.r1", "v0.144.0.r0"),
        ("0.145.0-alpha..23.r0", "v0.145.0-alpha..23.r0"),
        ("0.145.0-alpha.23.r0", "v0.145.0-alpha.24.r0"),
    ],
)
def test_rejects_invalid_or_mismatched_release_versions(source_version: str, tag: str):
    with pytest.raises(ValueError):
        validate_release_version(source_version, tag)


def test_docker_build_requires_current_checkout_wheel():
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    dockerfile = (_ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")

    assert "build-docker: build-package" in makefile
    assert "--build-arg LOCAL_WHEEL=" in makefile
    assert "PACKAGE_VERSION" not in dockerfile
    assert 'test -n "$LOCAL_WHEEL"' in dockerfile
    assert '"/tmp/dist/${LOCAL_WHEEL}[gateway,profiling]"' in dockerfile
    assert '"codex-rosetta[gateway,profiling]' not in dockerfile
