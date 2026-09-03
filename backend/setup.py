from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist


BACKEND_ROOT = Path(__file__).resolve().parent
COMMUNITY_ROOT = BACKEND_ROOT.parent
BUILD_INFO = Path("src/paperseek_app/build_info.py")


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(COMMUNITY_ROOT), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _build_identity(source: Path) -> tuple[str, bool]:
    commit = os.environ.get("PAPERSEEK_BUILD_COMMIT", "").strip()
    dirty_text = os.environ.get("PAPERSEEK_BUILD_DIRTY")
    if not commit:
        try:
            commit = _git("rev-parse", "HEAD")
        except (OSError, subprocess.CalledProcessError):
            match = re.search(
                r'^COMMUNITY_COMMIT = "([^"]+)"$',
                source.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
            commit = match.group(1) if match else "unknown"
    if dirty_text is None:
        try:
            dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
        except (OSError, subprocess.CalledProcessError):
            dirty = True
    else:
        dirty = dirty_text.strip().lower() in {"1", "true", "yes"}
    return commit, dirty


def _stamp_build_info(source: Path, target: Path) -> None:
    commit, dirty = _build_identity(source)
    content = source.read_text(encoding="utf-8")
    content = re.sub(
        r'^COMMUNITY_COMMIT = ".*"$',
        f'COMMUNITY_COMMIT = "{commit}"',
        content,
        flags=re.MULTILINE,
    )
    content = re.sub(
        r"^SOURCE_TREE_DIRTY = (?:True|False)$",
        f"SOURCE_TREE_DIRTY = {dirty}",
        content,
        flags=re.MULTILINE,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class BuildPy(_build_py):
    def run(self) -> None:
        super().run()
        _stamp_build_info(
            BACKEND_ROOT / BUILD_INFO,
            Path(self.build_lib) / "paperseek_app/build_info.py",
        )


class Sdist(_sdist):
    def make_release_tree(self, base_dir: str, files: list[str]) -> None:
        super().make_release_tree(base_dir, files)
        target = Path(base_dir) / BUILD_INFO
        _stamp_build_info(BACKEND_ROOT / BUILD_INFO, target)


setup(cmdclass={"build_py": BuildPy, "sdist": Sdist})
