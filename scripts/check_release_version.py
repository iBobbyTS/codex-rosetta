"""Validate the source version and manual GitHub Release tag contract."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

SOURCE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+\.r\d+$")
RELEASE_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+\.r\d+$")
SOURCE_LITERAL_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
DEFAULT_VERSION_FILE = Path("src/codex_rosetta/__init__.py")


def read_source_version(path: Path = DEFAULT_VERSION_FILE) -> str:
    """Read the literal Codex-Rosetta version from the package source."""
    match = SOURCE_LITERAL_RE.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"could not find __version__ in {path}")
    return match.group(1)


def validate_release_version(source_version: str, tag: str) -> None:
    """Require ``v{codex_version}.rN`` tag for a matching source version."""
    if SOURCE_VERSION_RE.fullmatch(source_version) is None:
        raise ValueError(
            f"source version '{source_version}' must match <major>.<minor>.<patch>.rN"
        )
    if RELEASE_TAG_RE.fullmatch(tag) is None:
        raise ValueError(f"tag '{tag}' must match v<major>.<minor>.<patch>.rN")
    if tag[1:] != source_version:
        raise ValueError(
            f"tag '{tag}' does not match source version '{source_version}'"
        )


def main() -> int:
    """Run the release-version validation CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="Exact GitHub Release tag")
    parser.add_argument(
        "--version-file",
        type=Path,
        default=DEFAULT_VERSION_FILE,
        help="Package file containing __version__",
    )
    args = parser.parse_args()

    try:
        source_version = read_source_version(args.version_file)
        validate_release_version(source_version, args.tag)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"release version OK: {source_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
