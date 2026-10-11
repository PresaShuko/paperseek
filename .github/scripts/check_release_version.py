"""Fail publishing unless the tag, both packages and the MCP pin agree."""
from __future__ import annotations

import argparse
from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def check_release_version(root: Path, tag: str) -> str:
    release = Version(tag.removeprefix("v"))
    if release.local is not None or release.dev is not None:
        raise ValueError("Release tags must not contain local or development versions")
    projects = []
    for directory in ("backend", "integrations/mcp"):
        with (root / directory / "pyproject.toml").open("rb") as stream:
            projects.append(tomllib.load(stream)["project"])
    for project in projects:
        if Version(project["version"]) != release:
            raise ValueError(
                f"Tag {tag} does not match {project['name']} {project['version']}"
            )
    dependencies = [Requirement(value) for value in projects[1]["dependencies"]]
    pins = [item for item in dependencies if canonicalize_name(item.name) == "paperseek"]
    if len(pins) != 1:
        raise ValueError("MCP must have exactly one Community dependency")
    dependency = pins[0]
    specifiers = list(dependency.specifier)
    if (
        dependency.url is not None
        or dependency.marker is not None
        or len(specifiers) != 1
        or specifiers[0].operator != "=="
        or specifiers[0].version.endswith(".*")
        or Version(specifiers[0].version) != release
    ):
        raise ValueError(f"MCP must pin paperseek=={release} without a marker or URL")
    return str(release)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    try:
        version = check_release_version(Path(__file__).resolve().parents[2], args.tag)
    except ValueError as exc:
        parser.exit(1, f"Release version check failed: {exc}\n")
    print(version)


if __name__ == "__main__":
    main()
