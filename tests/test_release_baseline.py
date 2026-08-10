import hashlib
import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = Path(__file__).parent / "fixtures" / "baseline"
MANIFEST_PATH = BASELINE_DIR / "release_baseline.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _requirement_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_dependency_and_build_input_manifest_matches_current_files():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    python_baseline = manifest["python"]

    assert manifest["repository"] == {
        "name": "paperseek-community",
        "role": "canonical-core-application-source",
        "head": "5525a58bd72e5f1cd18b681a25d0eea72e6b24ef",
    }
    for entry in manifest["dependency_files"]:
        path = ROOT / entry["path"]
        assert path.is_file()
        assert _sha256(path) == entry["sha256"]

    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    assert pyproject["project"]["requires-python"] == python_baseline["requires_python"]
    assert pyproject["build-system"]["build-backend"] == python_baseline["build_backend"]
    assert pyproject["build-system"]["requires"] == python_baseline["build_requires"]
    assert pyproject["project"]["dependencies"] == python_baseline["project_dependencies"]
    assert pyproject["project"]["optional-dependencies"] == python_baseline["optional_dependencies"]
    assert _requirement_lines(ROOT / "requirements.txt") == python_baseline["requirements_txt"]

    lock_inventory = python_baseline["lock_inventory"]
    assert (ROOT / "uv.lock").exists() is lock_inventory["uv_lock_present"]
    assert lock_inventory == {
        "uv_lock_present": False,
        "requirements_fully_pinned": False,
        "requirements_contains_hashes": False,
    }
    assert python_baseline["observed_environment"]["capture_kind"] == (
        "observational-only-not-an-install-lock"
    )

    package_lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    node_baseline = manifest["node"]
    assert package_lock["lockfileVersion"] == node_baseline["lockfile_version"]
    assert len(package_lock["packages"]) == node_baseline["locked_package_entries"]
    assert package_lock["packages"][""]["devDependencies"] == node_baseline["root_dev_dependencies"]
    vitepress = package_lock["packages"]["node_modules/vitepress"]
    assert {
        "version": vitepress["version"],
        "integrity": vitepress["integrity"],
    } == node_baseline["resolved_direct"]["vitepress"]
    assert node_baseline["scope"] == "documentation-only"
