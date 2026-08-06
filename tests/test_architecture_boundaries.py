import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "paperseek_core"


class ArchitectureBoundaryTest(unittest.TestCase):
    def test_core_does_not_import_edition_or_web_dependencies(self):
        forbidden_roots = {"fastapi", "paperseek", "supabase"}
        violations = []
        for path in CORE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.split(".", 1)[0] in forbidden_roots:
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno} imports {name}")
        self.assertEqual(violations, [], "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
