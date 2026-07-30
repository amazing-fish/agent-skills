import ast
from datetime import timedelta
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "wechat-article-fetch"


def _load_fetch_module():
    requests_stub = types.ModuleType("requests")
    requests_stub.Session = type("Session", (), {})
    requests_stub.Response = type("Response", (), {})
    requests_stub.RequestException = type("RequestException", (Exception,), {})

    etree_stub = types.ModuleType("lxml.etree")
    etree_stub.ParserError = type("ParserError", (Exception,), {})
    html_stub = types.ModuleType("lxml.html")
    lxml_stub = types.ModuleType("lxml")
    lxml_stub.etree = etree_stub
    lxml_stub.html = html_stub

    module_name = "_wechat_article_fetch_policy_target"
    script_path = SKILL_ROOT / "scripts" / "fetch_mp_article.py"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    previous_bytecode_setting = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        with mock.patch.dict(
            sys.modules,
            {
                module_name: module,
                "requests": requests_stub,
                "lxml": lxml_stub,
                "lxml.etree": etree_stub,
                "lxml.html": html_stub,
            },
        ):
            spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_bytecode_setting
    return module


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

    def test_refresh_invalidation_removes_stale_assets(self):
        module = _load_fetch_module()
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            assets_dir = output_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "001.png").write_bytes(b"stale")

            module.invalidate_asset_cache(output_dir)

            self.assertFalse(assets_dir.exists())
            module.invalidate_asset_cache(output_dir)

        self.assertIn("invalidate_asset_cache(output_dir)", self.script)

    def test_default_cache_is_allowed_when_profile_directory_is_cwd(self):
        module = _load_fetch_module()
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary)
            local_app_data = profile / "AppData" / "Local"
            with (
                mock.patch.dict(
                    module.os.environ,
                    {"LOCALAPPDATA": str(local_app_data)},
                    clear=False,
                ),
                mock.patch.object(module.Path, "cwd", return_value=profile),
            ):
                output_dir = module.choose_output_dir("safe-sn", None)
                self.assertEqual(
                    (local_app_data / "mp-article-cache" / "safe-sn").resolve(),
                    output_dir,
                )

                with self.assertRaises(module.FetchError) as raised:
                    module.choose_output_dir("safe-sn", profile / "explicit")
                self.assertEqual("PARSE_FAILED", raised.exception.code)

    def test_error_markers_are_scoped_to_missing_or_invalid_content(self):
        tree = ast.parse(self.script)
        parse_article = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "parse_article"
        )
        parents = {
            child: parent
            for parent in ast.walk(parse_article)
            for child in ast.iter_child_nodes(parent)
        }
        marker_calls = [
            node
            for node in ast.walk(parse_article)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "detect_page_error"
        ]

        self.assertEqual(3, len(marker_calls))
        for call in marker_calls:
            with self.subTest(line=call.lineno):
                ancestor = parents[call]
                is_scoped = False
                while ancestor is not parse_article:
                    if isinstance(ancestor, (ast.If, ast.ExceptHandler)):
                        is_scoped = True
                        break
                    ancestor = parents[ancestor]
                self.assertTrue(is_scoped)

    def test_publish_time_uses_windows_safe_fixed_china_offset(self):
        module = _load_fetch_module()

        self.assertEqual(timedelta(hours=8), module.CHINA_STANDARD_TIME.utcoffset(None))
        rendered = module.datetime.fromtimestamp(
            1785311401,
            tz=module.CHINA_STANDARD_TIME,
        ).isoformat(timespec="seconds")
        self.assertTrue(rendered.endswith("+08:00"))
        self.assertNotIn("ZoneInfo", self.script)

    def test_js_string_decoder_combines_utf16_surrogate_pairs(self):
        module = _load_fetch_module()

        decoded = module._decode_js_string(r"CSDN \uD83D\uDE00")
        self.assertEqual("CSDN 😀", decoded)
        self.assertEqual(b"CSDN \xf0\x9f\x98\x80", decoded.encode("utf-8"))
        self.assertEqual("\ufffd", module._decode_js_string(r"\uD83D"))

    def test_plain_text_escapes_markdown_without_escaping_converter_markup(self):
        module = _load_fetch_module()

        for source, expected in (
            ("# literal", r"\# literal"),
            ("1. version", r"1\. version"),
            ("> quoted", r"\> quoted"),
            ("---", r"\-\-\-"),
            ("- - -", r"\- \- \-"),
            ("*stars* and [brackets]", r"\*stars\* and \[brackets\]"),
        ):
            with self.subTest(source=source):
                self.assertEqual(expected, module._plain_text(source))

        class Node:
            def __init__(self, tag, text):
                self.tag = tag
                self.text = text
                self.tail = None

            def __iter__(self):
                return iter(())

        converter = module.MarkdownConverter({})
        self.assertEqual("**bold**", converter._render_node(Node("strong", "bold")))
        self.assertEqual(
            "\n\n# \\# literal\n\n",
            converter._render_node(Node("h1", "# literal")),
        )

    def test_nested_ordered_lists_indent_to_parent_content_column(self):
        module = _load_fetch_module()

        class Node:
            def __init__(self, tag, text=None, children=()):
                self.tag = tag
                self.text = text
                self.tail = None
                self.children = list(children)

            def __iter__(self):
                return iter(self.children)

        nested = Node("ul", children=[Node("li", "child")])
        items = [Node("li", f"item {index}") for index in range(1, 10)]
        items.append(Node("li", "parent", children=[nested]))
        rendered = module.MarkdownConverter({})._render_list(
            Node("ol", children=items),
            ordered=True,
        )

        self.assertIn("10. parent\n    - child", rendered)

    def test_td_only_table_retains_first_row_as_data(self):
        module = _load_fetch_module()

        class Node:
            def __init__(self, tag, text=None, children=()):
                self.tag = tag
                self.text = text
                self.tail = None
                self.children = list(children)

            def __iter__(self):
                return iter(self.children)

            def xpath(self, expression):
                return self.children if expression == ".//tr" else []

        table = Node(
            "table",
            children=[
                Node("tr", children=[Node("td", "first"), Node("td", "row")]),
                Node("tr", children=[Node("td", "second"), Node("td", "row")]),
            ],
        )
        rendered = module.MarkdownConverter({})._render_table(table)

        self.assertEqual(
            "\n\n|  |  |\n| --- | --- |\n"
            "| first | row |\n| second | row |\n\n",
            rendered,
        )

    def test_non_image_200_response_is_not_cached_as_asset(self):
        module = _load_fetch_module()

        class Response:
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            content = b"<html>verification required</html>"

            def close(self):
                self.closed = True

        class Session:
            def __init__(self):
                self.response = Response()

            def get(self, *args, **kwargs):
                return self.response

        with tempfile.TemporaryDirectory() as temporary:
            session = Session()
            assets_dir = Path(temporary) / "assets"
            asset_map, warnings = module.download_assets(
                session,
                ["https://mmbiz.qpic.cn/example.jpg"],
                assets_dir,
                reuse_existing=False,
            )

            self.assertEqual({}, asset_map)
            self.assertEqual(1, len(warnings))
            self.assertIn("non-image Content-Type text/html", warnings[0])
            self.assertEqual([], list(assets_dir.iterdir()))
            self.assertTrue(session.response.closed)

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
            "refresh invalidates the existing `assets/` directory",
            "Marker phrases inside a non-empty `div#js_content` are article text",
            "stock Windows Python does not need an external IANA timezone database",
            "Plain article text escapes Markdown control syntax",
            "default `%LOCALAPPDATA%` cache remains valid",
            "Valid UTF-16 surrogate pairs become one supplementary Unicode character",
            "known non-image `Content-Type` is an image failure",
            "Nested list rows are indented to the parent marker's content column",
            "a `<td>`-only table receives an empty synthetic header",
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
