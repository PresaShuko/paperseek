import ast
import re
import unittest

from tests.helpers import ROOT, assert_contains_all, read_text


class PackagingTest(unittest.TestCase):
    def test_runtime_package_parses_with_python310_grammar(self):
        for package in ("paperseek", "paperseek_core"):
            for path in (ROOT / package).rglob("*.py"):
                with self.subTest(path=path.relative_to(ROOT)):
                    ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path), feature_version=(3, 10))

    def test_project_metadata_is_release_ready(self):
        pyproject = read_text("pyproject.toml")
        assert_contains_all(
            self,
            pyproject,
            (
                'name = "paperseek"',
                'version = "0.3.0"',
                'Homepage = "https://www.paperseek.xyz/"',
                'Repository = "https://github.com/MingfengHong/paperseek"',
                'Documentation = "https://docs.paperseek.xyz/"',
                'license-files = ["LICENSE", "THIRD_PARTY_NOTICES.md"]',
            ),
        )
        self.assertNotIn("modelscope.cn/studios", pyproject)
        self.assertNotRegex(pyproject, re.compile(r"^wos-search\s*=", re.MULTILINE))
        self.assertNotRegex(pyproject, re.compile(r"^wos-search-web\s*=", re.MULTILINE))

    def test_python310_and_harness_dependencies_are_declared(self):
        pyproject = read_text("pyproject.toml")
        ci = read_text(".github/workflows/ci.yml")
        assert_contains_all(
            self,
            pyproject,
            (
                'requires-python = ">=3.10"',
                '"Programming Language :: Python :: 3.10"',
                '"Programming Language :: Python :: 3.11"',
                '"Programming Language :: Python :: 3.12"',
                '"langchain-core>=1.5"',
                '"langgraph>=1.2"',
                '"pydantic-ai-slim>=2"',
            ),
        )
        self.assertNotIn('"Programming Language :: Python :: 3.8"', pyproject)
        self.assertNotIn('"Programming Language :: Python :: 3.9"', pyproject)
        assert_contains_all(self, ci, ('python-version: ["3.10", "3.11", "3.12"]',))
        self.assertNotIn('"3.8"', ci)
        self.assertNotIn('"3.9"', ci)

    def test_readmes_cover_installation_and_primary_links(self):
        expected_install_paths = (
            "python -m pip install paperseek",
            "git clone https://github.com/MingfengHong/paperseek.git",
            "python -m pip install -e .",
        )
        expected_links = (
            "https://pypi.org/project/paperseek/",
            "https://github.com/MingfengHong/paperseek",
            "docs/assets/paperseek-web.png",
            "docs/user-manual.md",
            "docs/deployment.md",
            "docs/online-demo.md",
            "https://www.paperseek.xyz/",
        )
        for path in ("README.md", "README.en.md"):
            readme = read_text(path)
            with self.subTest(path=path):
                self.assertFalse(readme.startswith("---\n"))
                self.assertNotIn("<repo-url>", readme)
                assert_contains_all(self, readme, expected_install_paths)
                assert_contains_all(self, readme, expected_links)
                self.assertNotIn("https://modelscope.cn/studios/HongMingfeng/paperseek", readme)

    def test_readmes_acknowledge_public_dependencies_and_integrations(self):
        expected_links = (
            "https://github.com/Yupu-Wang/paper-hub",
            "https://github.com/bytedance/pasa",
            "https://github.com/pydantic/pydantic-ai",
            "https://github.com/langchain-ai/langgraph",
            "THIRD_PARTY_NOTICES.md",
        )
        internal_reference_links = (
            "https://github.com/666ghj/MiroFish",
            "https://github.com/clarivate/wosstarter_python_client",
        )
        for path in ("README.md", "README.en.md"):
            readme = read_text(path)
            with self.subTest(path=path):
                assert_contains_all(self, readme, expected_links)
                for link in internal_reference_links:
                    self.assertNotIn(link, readme)

    def test_third_party_notice_records_dependencies_and_data_source(self):
        notice = read_text("THIRD_PARTY_NOTICES.md")
        manifest = read_text("MANIFEST.in")
        assert_contains_all(
            self,
            notice,
            (
                "Apache License 2.0",
                "PydanticAI",
                "LangGraph",
                "PaperHub",
                "Runtime dependencies",
                "PaperHub integration",
            ),
        )
        self.assertNotIn("MiroFish", notice)
        self.assertNotIn("clarivate/wosstarter_python_client", notice)
        self.assertNotIn("bytedance/pasa", notice)
        assert_contains_all(
            self,
            manifest,
            (
                "include THIRD_PARTY_NOTICES.md",
                "prune benchmarks",
                "exclude tests/test_benchmark_runner.py",
            ),
        )

    def test_user_manual_covers_main_workflows(self):
        manual = read_text("docs/user-manual.md")
        assert_contains_all(
            self,
            manual,
            (
                "## Get started",
                "## Install",
                "## Configuration",
                "## Models",
                "## Data sources",
                "## CLI",
                "## Web UI",
                "## Deployment",
                "## Agent Skill",
                "## MCP Server",
                "## Diagnostics and troubleshooting",
                "python -m pip install paperseek",
                "git clone https://github.com/MingfengHong/paperseek.git",
            ),
        )

    def test_online_demo_guide_exists(self):
        guide = read_text("docs/online-demo.md")
        assert_contains_all(
            self,
            guide,
            (
                "https://www.paperseek.xyz/",
                "ModelScope",
                "API Inference",
                "历史记录按登录账号隔离",
            ),
        )

    def test_docs_site_files_exist(self):
        for path in (
            "docs/.vitepress/config.mts",
            "docs/public/README.md",
            "docs/deployment.md",
            "docs/v0.3.0.md",
            "docs/assets/deploy-modelscope.svg",
            "THIRD_PARTY_NOTICES.md",
        ):
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())

    def test_deployment_entry_files_exist(self):
        for path in (
            "Dockerfile",
            ".dockerignore",
            "docker-compose.yml",
            "app.py",
            "api/index.py",
            "vercel.json",
            "ms_deploy.json",
        ):
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())


if __name__ == "__main__":
    unittest.main()
