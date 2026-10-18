import ast
from datetime import timedelta
import importlib.util
import io
import json
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

    def test_explicit_output_cache_requires_matching_sn(self):
        module = _load_fetch_module()

        class Session:
            def close(self):
                self.closed = True

        article = module.Article(
            title="New article",
            account="Account",
            summary="",
            cover_url="",
            publish_timestamp=1785311401,
            publish_time="2026-07-29T15:50:01+08:00",
            char_count=3,
            image_urls=[],
            content=None,
        )
        url = "https://mp.weixin.qq.com/s/new-sn"
        args = types.SimpleNamespace(
            url=url,
            assets=False,
            refresh=False,
            out=None,
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            args.out = output_dir
            (output_dir / "raw.html").write_bytes(b"old article")
            (output_dir / "article.md").write_text(
                '---\nsn: "old-sn"\n---\n',
                encoding="utf-8",
            )
            session = Session()
            with (
                mock.patch.object(module, "make_session", return_value=session),
                mock.patch.object(
                    module,
                    "fetch_html",
                    return_value=b"new article",
                ) as fetch_html,
                mock.patch.object(
                    module,
                    "parse_article",
                    return_value=article,
                ) as parse_article,
                mock.patch.object(
                    module,
                    "render_article_markdown",
                    return_value='---\nsn: "new-sn"\n---\n',
                ),
            ):
                result = module.run(args)

            fetch_html.assert_called_once_with(session, url)
            parse_article.assert_called_once_with(b"new article", url)
            self.assertFalse(result["cached"])
            self.assertEqual(b"new article", (output_dir / "raw.html").read_bytes())
            self.assertTrue(session.closed)

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

    def test_image_only_body_uses_src_fallback_and_is_not_empty(self):
        module = _load_fetch_module()

        class Image:
            tag = "img"
            text = None
            tail = None

            def get(self, name):
                return {"data-src": " ", "src": "//mmbiz.qpic.cn/poster.jpg"}.get(name)

            def __iter__(self):
                return iter(())

        class Content:
            tag = "div"
            text = None
            tail = None

            def text_content(self):
                return ""

            def xpath(self, expression):
                return [Image()] if expression == ".//img" else []

            def __iter__(self):
                return iter((Image(),))

        class Document:
            def xpath(self, expression, **kwargs):
                return [Content()] if expression == "//div[@id='js_content']" else []

        metadata = {
            "og:title": "Image-only article",
            "og:description": "",
            "og:image": "",
        }
        with (
            mock.patch.object(
                module.lxml_html,
                "fromstring",
                return_value=Document(),
                create=True,
            ),
            mock.patch.object(
                module,
                "_meta_content",
                side_effect=lambda document, name: metadata[name],
            ),
            mock.patch.object(module, "_extract_account", return_value="Account"),
            mock.patch.object(module, "_extract_timestamp", return_value=1785311401),
        ):
            article = module.parse_article(
                b"<html></html>",
                "https://mp.weixin.qq.com/s/example",
            )

        self.assertEqual(0, article.char_count)
        self.assertEqual(
            ["https://mmbiz.qpic.cn/poster.jpg"],
            article.image_urls,
        )
        self.assertEqual(
            "\n\n![](https://mmbiz.qpic.cn/poster.jpg)\n\n",
            module.MarkdownConverter({})._render_image(Image()),
        )

    def test_skipped_subtrees_do_not_make_an_empty_body_renderable(self):
        module = _load_fetch_module()

        class Node:
            def __init__(self, tag, text=None, children=(), attrs=None, tail=None):
                self.tag = tag
                self.text = text
                self.tail = tail
                self.children = list(children)
                self.attrs = attrs or {}

            def __iter__(self):
                return iter(self.children)

            def get(self, name):
                return self.attrs.get(name)

            def itertext(self):
                if self.text:
                    yield self.text
                for child in self.children:
                    yield from child.itertext()
                    if child.tail:
                        yield child.tail

        content = Node(
            "div",
            children=[
                Node("script", "placeholder"),
                Node(
                    "noscript",
                    children=[
                        Node(
                            "img",
                            attrs={"src": "https://mmbiz.qpic.cn/fallback.jpg"},
                        )
                    ],
                ),
                Node(
                    "pre",
                    children=[
                        Node(
                            "img",
                            attrs={"src": "https://mmbiz.qpic.cn/code-example.jpg"},
                        )
                    ],
                ),
            ],
        )

        class Document:
            def xpath(self, expression, **kwargs):
                return [content] if expression == "//div[@id='js_content']" else []

        with mock.patch.object(
            module.lxml_html,
            "fromstring",
            return_value=Document(),
            create=True,
        ):
            with self.assertRaises(module.FetchError) as raised:
                module.parse_article(
                    b"<html></html>",
                    "https://mp.weixin.qq.com/s/example",
                )

        self.assertEqual("EMPTY_CONTENT", raised.exception.code)

    def test_plain_text_escapes_markdown_without_escaping_converter_markup(self):
        module = _load_fetch_module()

        for source, expected in (
            ("# literal", r"\# literal"),
            ("1. version", r"1\. version"),
            ("> quoted", r"\> quoted"),
            ("---", r"\-\-\-"),
            ("- - -", r"\- \- \-"),
            ("~~~", r"\~\~\~"),
            ("~~text~~", r"\~\~text\~\~"),
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

    def test_split_plain_text_markers_escape_after_inline_join(self):
        module = _load_fetch_module()

        class Node:
            def __init__(self, tag, text=None, children=(), tail=None):
                self.tag = tag
                self.text = text
                self.tail = tail
                self.children = list(children)

            def __iter__(self):
                return iter(self.children)

            def get(self, name):
                return None

        converter = module.MarkdownConverter({})
        examples = (
            (
                Node("p", children=[Node("span", "1", tail=". item")]),
                "\n\n1\\. item\n\n",
            ),
            (
                Node("p", children=[Node("span", "-", tail=" item")]),
                "\n\n\\- item\n\n",
            ),
            (
                Node(
                    "p",
                    children=[
                        Node("span", "-"),
                        Node("span", "-", tail="-"),
                    ],
                ),
                "\n\n\\-\\-\\-\n\n",
            ),
        )
        for node, expected in examples:
            with self.subTest(expected=expected):
                self.assertEqual(expected, converter._render_node(node))
        self.assertEqual(
            "\n\n- 1\\. item\n\n",
            converter._render_node(
                Node(
                    "ul",
                    children=[
                        Node(
                            "li",
                            children=[Node("span", "1", tail=". item")],
                        )
                    ],
                )
            ),
        )

    def test_inline_markup_preserves_boundary_whitespace(self):
        module = _load_fetch_module()

        class Node:
            def __init__(self, tag, text=None, children=(), attrs=None, tail=None):
                self.tag = tag
                self.text = text
                self.tail = tail
                self.children = list(children)
                self.attrs = attrs or {}

            def __iter__(self):
                return iter(self.children)

            def get(self, name):
                return self.attrs.get(name)

            def itertext(self):
                yield self.text or ""

        converter = module.MarkdownConverter({})
        paragraph = Node(
            "p",
            "Hello ",
            children=[
                Node("strong", "world ", tail="again "),
                Node("em", "with emphasis ", tail="and "),
                Node(
                    "a",
                    "a link ",
                    attrs={"href": "https://example.com/"},
                    tail="plus ",
                ),
                Node("code", "code ", tail="done"),
            ],
        )

        self.assertEqual(
            "\n\nHello **world** again *with emphasis* and "
            "[a link](https://example.com/) plus `code` done\n\n",
            converter._render_node(paragraph),
        )

    def test_markdown_destinations_escape_syntax_breaking_characters(self):
        module = _load_fetch_module()

        class Node:
            def __init__(self, tag, text=None, attrs=None):
                self.tag = tag
                self.text = text
                self.tail = None
                self.attrs = attrs or {}

            def __iter__(self):
                return iter(())

            def get(self, name):
                return self.attrs.get(name)

        href = "https://example.com/a]b)c d?q=(x)"
        destination = "https://example.com/a%5Db%29c%20d?q=%28x%29"
        converter = module.MarkdownConverter({})

        self.assertEqual(
            f"[read]({destination})",
            converter._render_node(Node("a", "read", {"href": href})),
        )
        self.assertEqual(
            f"[https://example.com/a\\]b)c d?q=(x)]({destination})",
            converter._render_node(Node("a", "", {"href": href})),
        )
        article_converter = module.MarkdownConverter(
            {},
            "https://mp.weixin.qq.com/s/example",
        )
        self.assertEqual(
            "[next](https://mp.weixin.qq.com/s/next)",
            article_converter._render_node(
                Node("a", "next", {"href": "/s/next"}),
            ),
        )
        self.assertEqual(
            "[related](https://mp.weixin.qq.com/s/related.html)",
            article_converter._render_node(
                Node("a", "related", {"href": "related.html"}),
            ),
        )
        self.assertEqual(
            "[section](#section)",
            article_converter._render_node(
                Node("a", "section", {"href": "#section"}),
            ),
        )

        source = "https://mmbiz.qpic.cn/a)b c.png"
        converter = module.MarkdownConverter(
            {source: "assets/001 weird).png"},
        )
        self.assertEqual(
            "\n\n![](assets/001%20weird%29.png)\n\n",
            converter._render_node(Node("img", attrs={"data-src": source})),
        )

    def test_relative_image_sources_resolve_against_article_url(self):
        module = _load_fetch_module()

        class Node:
            def __init__(self, tag, attrs=None, children=()):
                self.tag = tag
                self.text = None
                self.tail = None
                self.attrs = attrs or {}
                self.children = list(children)

            def __iter__(self):
                return iter(self.children)

            def get(self, name):
                return self.attrs.get(name)

        article_url = "https://mp.weixin.qq.com/s/example"
        absolute_url = "https://mp.weixin.qq.com/images/picture.png"
        image = Node("img", {"src": "/images/picture.png"})
        content = Node("div", children=[image])

        self.assertEqual(
            [absolute_url],
            module._renderable_image_urls(content, article_url),
        )
        self.assertEqual(
            "\n\n![](assets/001.png)\n\n",
            module.MarkdownConverter(
                {absolute_url: "assets/001.png"},
                article_url,
            )._render_image(image),
        )
        self.assertIn("mp.weixin.qq.com", module.TRUSTED_ASSET_HOSTS)

    def test_nested_ordered_lists_indent_to_parent_content_column(self):
        module = _load_fetch_module()

        class Node:
            def __init__(self, tag, text=None, children=(), attrs=None):
                self.tag = tag
                self.text = text
                self.tail = None
                self.children = list(children)
                self.attrs = attrs or {}

            def __iter__(self):
                return iter(self.children)

            def get(self, name):
                return self.attrs.get(name)

        nested = Node("ul", children=[Node("li", "child")])
        items = [Node("li", f"item {index}") for index in range(1, 10)]
        items.append(Node("li", "parent", children=[nested]))
        rendered = module.MarkdownConverter({})._render_list(
            Node("ol", children=items),
            ordered=True,
        )

        self.assertIn("10. parent\n    - child", rendered)

    def test_ordered_list_preserves_start_and_item_value(self):
        module = _load_fetch_module()

        class Node:
            def __init__(self, tag, text=None, children=(), attrs=None):
                self.tag = tag
                self.text = text
                self.tail = None
                self.children = list(children)
                self.attrs = attrs or {}

            def __iter__(self):
                return iter(self.children)

            def get(self, name):
                return self.attrs.get(name)

        ordered = Node(
            "ol",
            attrs={"start": "5"},
            children=[
                Node("li", "five"),
                Node("li", "nine", attrs={"value": "9"}),
                Node("li", "ten"),
            ],
        )
        rendered = module.MarkdownConverter({})._render_list(
            ordered,
            ordered=True,
        )

        self.assertEqual("\n\n5. five\n9. nine\n10. ten\n\n", rendered)

    def test_nested_lists_and_continuations_keep_source_order_and_indentation(self):
        module = _load_fetch_module()

        class Node:
            def __init__(self, tag, text=None, children=(), tail=None):
                self.tag = tag
                self.text = text
                self.tail = tail
                self.children = list(children)

            def __iter__(self):
                return iter(self.children)

            def get(self, name):
                return None

        nested = Node("ul", children=[Node("li", "child")], tail="after")
        ordered_content = Node(
            "ul",
            children=[Node("li", "before", children=[nested])],
        )
        paragraphs = Node(
            "ul",
            children=[
                Node(
                    "li",
                    children=[
                        Node("p", "first"),
                        Node("p", "second"),
                    ],
                )
            ],
        )
        converter = module.MarkdownConverter({})

        self.assertEqual(
            "- before\n  - child\n  after",
            converter.convert(Node("div", children=[ordered_content])),
        )
        self.assertEqual(
            "- first\n\n  second",
            converter.convert(Node("div", children=[paragraphs])),
        )

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

            def get(self, name):
                return None

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

    def test_fenced_code_preserves_trailing_spaces_and_tabs(self):
        module = _load_fetch_module()

        class Node:
            def itertext(self):
                return iter(("first  \n```  \nsecond\t\n",))

            def xpath(self, expression):
                return []

        converter = module.MarkdownConverter({})
        rendered = converter._cleanup(converter._render_pre(Node()))

        self.assertEqual(
            "````\nfirst  \n```  \nsecond\t\n````",
            rendered,
        )

    def test_article_fetch_requires_https_and_uses_native_redirects(self):
        module = _load_fetch_module()

        with self.assertRaises(module.FetchError) as rejected:
            module.parse_sn("http://mp.weixin.qq.com/s/example")
        self.assertEqual("NOT_MP_URL", rejected.exception.code)

        class Response:
            status_code = 200
            headers = {}

            def iter_content(self, *, chunk_size):
                self.chunk_size = chunk_size
                return iter((b"<html></html>",))

            def close(self):
                self.closed = True

        class Session:
            def __init__(self):
                self.calls = []
                self.response = Response()

            def get(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return self.response

        session = Session()
        payload = module.fetch_html(
            session,
            "https://mp.weixin.qq.com/s/example",
        )

        self.assertEqual(b"<html></html>", payload)
        self.assertEqual(1, len(session.calls))
        self.assertTrue(session.calls[0][1]["stream"])
        self.assertTrue(session.calls[0][1]["allow_redirects"])
        self.assertTrue(session.response.closed)

    def test_oversized_streaming_article_is_rejected(self):
        module = _load_fetch_module()

        class Response:
            status_code = 200
            headers = {"Content-Type": "text/html"}

            def iter_content(self, *, chunk_size):
                self.chunk_size = chunk_size
                return iter((b"12345678", b"9"))

            def close(self):
                self.closed = True

        class Session:
            def __init__(self):
                self.calls = []
                self.response = Response()

            def get(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return self.response

        with mock.patch.object(module, "MAX_ARTICLE_BYTES", 8):
            session = Session()
            with self.assertRaises(module.FetchError) as oversized:
                module.fetch_html(
                    session,
                    "https://mp.weixin.qq.com/s/example",
                )

        self.assertEqual("NETWORK", oversized.exception.code)
        self.assertIn("8-byte limit", oversized.exception.message)
        self.assertEqual(module.ARTICLE_CHUNK_BYTES, session.response.chunk_size)
        self.assertTrue(session.response.closed)

    def test_emit_json_uses_utf8_bytes_with_legacy_text_encoding(self):
        module = _load_fetch_module()

        class LegacyStdout:
            encoding = "cp1252"

            def __init__(self):
                self.buffer = io.BytesIO()

            def write(self, value):
                raise AssertionError("emit_json must bypass the legacy text encoding")

        stdout = LegacyStdout()
        with mock.patch.object(module.sys, "stdout", stdout):
            module.emit_json({"title": "中文😀"})

        encoded = stdout.buffer.getvalue()
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertEqual(
            {"title": "中文😀"},
            json.loads(encoded.decode("utf-8")),
        )

    def test_non_image_200_response_is_not_cached_as_asset(self):
        module = _load_fetch_module()

        class Response:
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            content = b"<html>verification required</html>"
            url = "https://mmbiz.qpic.cn/example.jpg"

            def close(self):
                self.closed = True

        class Session:
            def __init__(self):
                self.response = Response()

            def get(self, *args, **kwargs):
                return self.response

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            module,
            "_validate_asset_url",
        ):
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

    def test_empty_image_payload_is_not_cached_as_asset(self):
        module = _load_fetch_module()

        class Response:
            status_code = 200
            headers = {"Content-Type": "image/jpeg"}
            url = "https://mmbiz.qpic.cn/empty.jpg"

            def iter_content(self, *, chunk_size):
                self.chunk_size = chunk_size
                return iter(())

            def close(self):
                self.closed = True

        class Session:
            def __init__(self):
                self.response = Response()

            def get(self, *args, **kwargs):
                return self.response

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            module,
            "_validate_asset_url",
        ):
            session = Session()
            assets_dir = Path(temporary) / "assets"
            asset_map, warnings = module.download_assets(
                session,
                ["https://mmbiz.qpic.cn/empty.jpg"],
                assets_dir,
                reuse_existing=False,
            )

            self.assertEqual({}, asset_map)
            self.assertEqual(1, len(warnings))
            self.assertIn("empty response body", warnings[0])
            self.assertEqual([], list(assets_dir.iterdir()))
            self.assertTrue(session.response.closed)

    def test_asset_download_validates_initial_url_and_uses_native_redirects(self):
        module = _load_fetch_module()

        for url in (
            "http://mmbiz.qpic.cn/image.jpg",
            "https://user@example.com/image.jpg",
            "https://mmbiz.qpic.cn:444/image.jpg",
            "https://example.com/image.jpg",
        ):
            with self.subTest(url=url), self.assertRaises(module.FetchError):
                module._validate_asset_url(url)

        class Response:
            status_code = 200
            headers = {"Content-Type": "image/jpeg"}
            url = "https://mmbiz.qpic.cn/redirected.jpg"

            def iter_content(self, *, chunk_size):
                self.chunk_size = chunk_size
                return iter((b"image",))

            def close(self):
                self.closed = True

        class Session:
            def __init__(self):
                self.calls = []
                self.response = Response()

            def get(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return self.response

        with tempfile.TemporaryDirectory() as temporary:
            session = Session()
            asset_map, warnings = module.download_assets(
                session,
                ["https://mmbiz.qpic.cn/redirect.jpg"],
                Path(temporary) / "assets",
                reuse_existing=False,
            )

            self.assertEqual(
                {"https://mmbiz.qpic.cn/redirect.jpg": "assets/001.jpg"},
                asset_map,
            )
            self.assertEqual([], warnings)
            self.assertEqual(1, len(session.calls))
            self.assertTrue(session.calls[0][1]["stream"])
            self.assertTrue(session.calls[0][1]["allow_redirects"])
            self.assertTrue(session.response.closed)

    def test_image_extension_prefers_negotiated_avif_content_type(self):
        module = _load_fetch_module()

        class Response:
            headers = {"Content-Type": "image/avif"}

        self.assertEqual(
            ".avif",
            module._image_extension(
                Response(),
                "https://mmbiz.qpic.cn/image.jpg",
            ),
        )

    def test_oversized_streaming_image_is_not_cached_as_asset(self):
        module = _load_fetch_module()

        class Response:
            status_code = 200
            headers = {"Content-Type": "image/jpeg"}
            url = "https://mmbiz.qpic.cn/oversized.jpg"

            def iter_content(self, *, chunk_size):
                self.chunk_size = chunk_size
                return iter((b"12345678", b"9"))

            def close(self):
                self.closed = True

        class Session:
            def __init__(self):
                self.response = Response()

            def get(self, *args, **kwargs):
                return self.response

        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.object(module, "_validate_asset_url"),
            mock.patch.object(module, "MAX_ASSET_BYTES", 8),
        ):
            session = Session()
            assets_dir = Path(temporary) / "assets"
            asset_map, warnings = module.download_assets(
                session,
                ["https://mmbiz.qpic.cn/oversized.jpg"],
                assets_dir,
                reuse_existing=False,
            )

            self.assertEqual({}, asset_map)
            self.assertEqual(1, len(warnings))
            self.assertIn("8-byte limit", warnings[0])
            self.assertEqual([], list(assets_dir.iterdir()))
            self.assertEqual(module.ASSET_CHUNK_BYTES, session.response.chunk_size)
            self.assertTrue(session.response.closed)

    def test_network_cache_and_provenance_contracts_remain_explicit(self):
        for required_script_contract in (
            "TIMEOUT_SECONDS = 30",
            "RETRY_DELAYS = (1, 2, 4)",
            "MAX_ARTICLE_BYTES = 10 * 1024 * 1024",
            'TRUSTED_ARTICLE_HOSTS = frozenset({"mp.weixin.qq.com"})',
            "MAX_ASSET_BYTES = 20 * 1024 * 1024",
            'TRUSTED_ASSET_HOSTS = frozenset({"mmbiz.qpic.cn", "mp.weixin.qq.com"})',
            "allow_redirects=True",
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
            "written as UTF-8 bytes",
            "performs no article network request",
            "Only HTTPS article URLs",
            "Article response bodies use Requests' 30-second timeout and are streamed",
            "10 MiB",
            "refresh invalidates the existing `assets/` directory",
            "Marker phrases inside a non-empty `div#js_content` are article text",
            "stock Windows Python does not need an external IANA timezone database",
            "Plain article text escapes Markdown control syntax",
            "Markdown link and image destinations",
            "default `%LOCALAPPDATA%` cache remains valid",
            "Valid UTF-16 surrogate pairs become one supplementary Unicode character",
            "known non-image `Content-Type` is an image failure",
            "empty image payload is an image failure",
            "HTTPS on port 443",
            "trusted WeChat image hosts",
            "Requests follows redirects",
            "20 MiB",
            "Skipped subtrees do not contribute",
            "Nested list rows are indented to the parent marker's content column",
            "a `<td>`-only table receives an empty synthetic header",
            "Cell pipes are escaped",
            "cell line breaks become `<br>`",
            "Fenced code preserves trailing spaces and tabs",
            "visible text or at least one image URL",
            "prefer `data-src` and fall back to `src`",
            "`~~~`, or `~~text~~`",
            "Ordered lists preserve `<ol start>` and `<li value>` numbering",
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
