from pathlib import Path
import tempfile
import unittest

from check_release_version import check_release_version


class ReleaseVersionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.write_projects()

    def write_projects(self, community="1.0.0b1", mcp="1.0.0b1", pin="paperseek==1.0.0b1"):
        for directory, name, version, dependencies in (
            ("backend", "paperseek", community, []),
            ("integrations/mcp", "paperseek-mcp", mcp, [pin] if pin else []),
        ):
            target = self.root / directory / "pyproject.toml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                f'[project]\nname = "{name}"\nversion = "{version}"\n'
                f"dependencies = {dependencies!r}\n", encoding="utf-8"
            )

    def test_beta_tag_normalizes_to_python_version(self):
        for tag in ("v1.0.0-beta1", "1.0.0-beta1", "v1.0.0b1"):
            with self.subTest(tag=tag):
                self.assertEqual(check_release_version(self.root, tag), "1.0.0b1")

    def test_new_tag_cannot_publish_old_packages(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            check_release_version(self.root, "v1.0.0-beta2")

    def test_each_package_must_match(self):
        for versions in ({"community": "1.0.0b2"}, {"mcp": "1.0.0b2"}):
            with self.subTest(versions=versions):
                self.write_projects(**versions)
                with self.assertRaisesRegex(ValueError, "does not match"):
                    check_release_version(self.root, "v1.0.0-beta1")

    def test_dependency_must_be_unconditional_exact_release(self):
        for pin in ("", "paperseek==1.0.0b2", "paperseek>=1.0.0b1", "paperseek==1.0.*",
                    "paperseek==1.0.0b1; python_version >= '3.12'",
                    "paperseek @ https://example.invalid/paperseek.whl"):
            with self.subTest(pin=pin):
                self.write_projects(pin=pin)
                with self.assertRaises(ValueError):
                    check_release_version(self.root, "v1.0.0-beta1")

    def test_stable_and_rc_releases(self):
        for version, tag in (("1.0.0", "v1.0.0"), ("1.0.0rc1", "v1.0.0-rc1")):
            self.write_projects(version, version, f"paperseek=={version}")
            self.assertEqual(check_release_version(self.root, tag), version)

    def test_invalid_or_development_tags_fail(self):
        for tag in ("main", "", "v1.0.0.dev1", "v1.0.0+local"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                check_release_version(self.root, tag)


if __name__ == "__main__":
    unittest.main()
