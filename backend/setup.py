from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

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


def _bundle_web_sources(target: Path) -> None:
    web = COMMUNITY_ROOT / "web"
    if not (web / "src").is_dir():
        # An sdist already carries the archive made from the original checkout.
        if not target.is_file():
            raise RuntimeError("Shared Vue sources are missing from the build input.")
        return
    paths = [web / "package.json", web / "package-lock.json"]
    paths.extend(path for path in (web / "src").rglob("*") if path.suffix in {".vue", ".ts", ".css"})
    paths.extend((web / "public").glob("*.png"))
    target.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            entry = ZipInfo(path.relative_to(web).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, path.read_bytes())
        entry = ZipInfo("tools/generate_openapi_types.py", date_time=(1980, 1, 1, 0, 0, 0))
        entry.compress_type = ZIP_DEFLATED
        entry.external_attr = 0o644 << 16
        archive.writestr(entry, (BACKEND_ROOT / "scripts/generate_openapi_types.py").read_bytes())


class BuildPy(_build_py):
    def run(self) -> None:
        super().run()
        _stamp_build_info(
            BACKEND_ROOT / BUILD_INFO,
            Path(self.build_lib) / "paperseek_app/build_info.py",
        )
        _bundle_web_sources(Path(self.build_lib) / "paperseek_community/web_source.zip")


class Sdist(_sdist):
    def make_release_tree(self, base_dir: str, files: list[str]) -> None:
        super().make_release_tree(base_dir, files)
        target = Path(base_dir) / BUILD_INFO
        _stamp_build_info(BACKEND_ROOT / BUILD_INFO, target)
        _bundle_web_sources(Path(base_dir) / "src/paperseek_community/web_source.zip")


setup(cmdclass={"build_py": BuildPy, "sdist": Sdist})
