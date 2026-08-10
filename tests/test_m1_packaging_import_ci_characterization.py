import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "m1" / "packaging_import_ci_baseline.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class M1PackagingImportCiCharacterizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_prechange_identity_and_target_absence_are_recorded(self):
        self.assertEqual(self.baseline["schema_version"], 1)
        self.assertEqual(self.baseline["milestone"], "M1")
        self.assertEqual(
            self.baseline["repository"]["head"],
            "5525a58bd72e5f1cd18b681a25d0eea72e6b24ef",
        )
        self.assertEqual(
            self.baseline["prechange_target_paths_absent"],
            {"backend": True, "web": True},
        )

    def test_legacy_packaging_and_ci_inputs_remain_the_characterized_baseline(self):
        for relative, expected in self.baseline["files"].items():
            path = ROOT / relative
            with self.subTest(path=relative):
                self.assertEqual(path.stat().st_size, expected["bytes"])
                self.assertEqual(sha256(path), expected["sha256"])

        with (ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)
        expected_project = self.baseline["project"]
        self.assertEqual(project["project"]["name"], expected_project["name"])
        self.assertEqual(project["project"]["version"], expected_project["version"])
        self.assertEqual(project["project"]["requires-python"], expected_project["requires_python"])
        self.assertEqual(project["project"]["scripts"], expected_project["scripts"])
        self.assertEqual(
            project["tool"]["setuptools"]["packages"]["find"]["include"],
            expected_project["package_include"],
        )

    def test_legacy_imports_resolve_to_the_root_packages(self):
        for package, expected in self.baseline["legacy_packages"].items():
            with self.subTest(package=package):
                package_root = ROOT / package
                spec = importlib.util.find_spec(package)
                self.assertIsNotNone(spec)
                self.assertEqual(Path(spec.origin).resolve(), (package_root / "__init__.py").resolve())
                self.assertEqual(sum(1 for _ in package_root.rglob("*.py")), expected["python_files"])
                self.assertEqual(sha256(package_root / "__init__.py"), expected["init_sha256"])

    def test_legacy_core_has_no_forbidden_reverse_imports(self):
        forbidden = set(self.baseline["legacy_core_forbidden_import_roots"])
        violations = []
        for path in (ROOT / "paperseek_core").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.split(".", 1)[0] in forbidden:
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno} imports {name}")
        self.assertEqual(violations, self.baseline["legacy_core_forbidden_import_violations"])


if __name__ == "__main__":
    unittest.main()
