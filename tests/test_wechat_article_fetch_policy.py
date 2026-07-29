import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "wechat-article-fetch"


class WechatArticleFetchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.contract = (
            SKILL_ROOT / "references" / "output-contract.md"
        ).read_text(encoding="utf-8")
        self.script = (
            SKILL_ROOT / "scripts" / "fetch_mp_article.py"
        ).read_text(encoding="utf-8")
        self.metadata = (
            SKILL_ROOT / "agents" / "openai.yaml"
        ).read_text(encoding="utf-8")

    def test_package_contains_only_declared_skill_files(self):
        files = {
            path.relative_to(SKILL_ROOT).as_posix()
            for path in SKILL_ROOT.rglob("*")
            if path.is_file()
        }
        self.assertEqual(
            {
                "SKILL.md",
                "agents/openai.yaml",
                "references/output-contract.md",
                "scripts/fetch_mp_article.py",
            },
            files,
        )

    def test_skill_keeps_fetching_separate_from_downstream_capture(self):
        for required_policy in (
            "data-acquisition layer",
            "Do not summarize, classify, interpret, or archive",
            "Delegate those downstream responsibilities to `kb-capture`",
            "parse its single JSON object",
            "read `markdown_path`",
        ):
            with self.subTest(required_policy=required_policy):
                self.assertIn(required_policy, self.skill)

    def test_failure_contract_is_complete_and_fail_closed(self):
        for error_code in (
            "NOT_MP_URL",
            "DELETED",
            "NEEDS_VERIFY",
            "EXPIRED_LINK",
            "EMPTY_CONTENT",
            "NETWORK",
            "PARSE_FAILED",
        ):
            with self.subTest(error_code=error_code):
                self.assertIn(error_code, self.skill)
                self.assertIn(f'"{error_code}"', self.script)
        self.assertIn(
            "Never weaken these error boundaries",
            self.skill,
        )

    def test_script_uses_only_declared_runtime_dependencies(self):
        tree = ast.parse(self.script)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])

        third_party = {"requests", "lxml"}
        disallowed = {"playwright", "selenium", "bs4"}
        self.assertTrue(third_party.issubset(imports))
        self.assertTrue(disallowed.isdisjoint(imports))
        self.assertNotIn("shell=True", self.script)

    def test_network_cache_and_provenance_contracts_remain_explicit(self):
        for required_script_contract in (
            "TIMEOUT_SECONDS = 30",
            "RETRY_DELAYS = (1, 2, 4)",
            "cached=cache_hit",
            '"cached": cached',
            'f"原文链接：{source_url}"',
            'image.get("data-src")',
            '"mp-article-cache"',
        ):
            with self.subTest(required_script_contract=required_script_contract):
                self.assertIn(required_script_contract, self.script)

        for required_output_contract in (
            "%LOCALAPPDATA%\\mp-article-cache\\<sn>\\",
            "source_url",
            "Stdout contains exactly one UTF-8 JSON object",
            "performs no article network request",
        ):
            with self.subTest(required_output_contract=required_output_contract):
                self.assertIn(required_output_contract, self.contract)

    def test_agent_metadata_matches_skill(self):
        for required_metadata in (
            'display_name: "WeChat Article Fetch"',
            "Fetch WeChat articles into structured Markdown files",
            "Use $wechat-article-fetch",
        ):
            with self.subTest(required_metadata=required_metadata):
                self.assertIn(required_metadata, self.metadata)


if __name__ == "__main__":
    unittest.main()
