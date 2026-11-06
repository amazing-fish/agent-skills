"""Regression coverage for offline reading controls and source-path binding."""
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/report-for-human'
spec = importlib.util.spec_from_file_location('report_controls', SKILL / 'scripts/add_report_controls.py')
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)
PAGE = '<!doctype html><html lang="zh-CN"><head><title>示例</title></head><body><main><h1>正文</h1></main></body></html>'


class Tags(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.items = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.items.append((tag, dict(attrs)))


def source_paths(html):
    return [attrs['content'] for tag, attrs in Tags(html).items
            if tag == 'meta' and attrs.get('name') == 'report-source-path']


class ReportControlsTests(unittest.TestCase):
    def test_controls_are_inline_light_by_default_and_leave_content_readable(self):
        page = controls.enhance_report(PAGE)
        tags = Tags(page).items
        self.assertIn(('html', {'lang': 'zh-CN', 'data-report-theme': 'light'}), tags)
        self.assertIn('<h1>正文</h1>', page)
        self.assertTrue(any(tag == 'noscript' for tag, _ in tags))
        self.assertEqual(sum('data-rfh-theme-toggle' in a for _, a in tags), 1)
        self.assertEqual(sum('data-rfh-copy-path' in a for _, a in tags), 1)
        self.assertFalse(any(tag in {'link', 'iframe', 'img'} or
                             (tag == 'script' and 'src' in a) for tag, a in tags))
        self.assertEqual(source_paths(page), [])

    def test_theme_selector_has_three_accessible_options(self):
        page = controls.enhance_report(PAGE)
        tags = Tags(page).items
        selects = [attrs for tag, attrs in tags if tag == 'select' and 'data-rfh-theme-toggle' in attrs]
        self.assertEqual(len(selects), 1)
        self.assertEqual(selects[0]['aria-label'], '报告主题')
        self.assertEqual([attrs['value'] for tag, attrs in tags if tag == 'option'],
                         ['system', 'light', 'dark'])
        for name in ('reference-report.html', 'operations-report.html'):
            template = (SKILL / 'assets' / name).read_text(encoding='utf-8')
            self.assertIn('<option value="system">跟随系统</option>', template)
            self.assertIn((SKILL / 'assets/report-controls.js').read_text(encoding='utf-8'), template)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for mocked DOM behavior checks')
    def test_theme_behavior_in_mocked_dom(self):
        subprocess.run(['node', str(ROOT / 'tests/report_theme_behavior.cjs')],
                       check=True, capture_output=True, text=True)

    def test_repeat_enhancement_preserves_one_toolbar_and_the_source_path(self):
        path = r'C:\Reports\中文 空格 #1.html'
        page = controls.enhance_report(PAGE, source_path=path)
        page = controls.enhance_report(page)
        self.assertEqual(source_paths(page), [path])
        self.assertEqual(page.count(controls.HEAD_START), 1)
        self.assertEqual(page.count(controls.TOOLS_START), 1)
        self.assertEqual(page.count('<h1>正文</h1>'), 1)

    def test_source_path_cannot_inject_markup(self):
        path = '/reports/中文 #1 "><script>alert(1)</script>.html'
        page = controls.enhance_report(PAGE, source_path=path)
        self.assertEqual(source_paths(page), [path])
        self.assertEqual(sum(tag == 'script' for tag, _ in Tags(page).items), 1)

    def test_relative_paths_preview_urls_and_control_characters_are_rejected(self):
        for path in ('report.html', 'C:report.html', 'https://preview.example/report',
                     'sandbox:/report.html', '/reports/a\n.html', '/reports/a\x00.html'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                controls.enhance_report(PAGE, source_path=path)

    def test_windows_unc_and_posix_paths_are_accepted(self):
        for path in (r'C:\Reports\a.html', r'\\server\share\a.html', '/reports/a.html'):
            with self.subTest(path=path):
                self.assertEqual(source_paths(controls.enhance_report(PAGE, path)), [path])

    def test_conflicting_existing_source_paths_fail_unless_explicitly_rebound(self):
        page = PAGE.replace('</head>', '<meta name="report-source-path" content="/a.html">'
                            '<meta name="report-source-path" content="/b.html"></head>')
        with self.assertRaises(ValueError):
            controls.enhance_report(page)
        self.assertEqual(source_paths(controls.enhance_report(page, '/new.html')), ['/new.html'])

    def test_incomplete_html_is_rejected(self):
        with self.assertRaises(ValueError):
            controls.enhance_report('<p>fragment</p>')

    def test_helper_cli_binds_output_rebinds_after_move_and_honors_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / '中文 空格 #1.html'
            moved = Path(tmp) / '新位置 #2.html'
            original.write_text(PAGE, encoding='utf-8')
            command = [sys.executable, str(SKILL / 'scripts/add_report_controls.py')]
            subprocess.run([*command, '--input', str(original)], check=True, capture_output=True)
            self.assertEqual(source_paths(original.read_text(encoding='utf-8')), [str(original.resolve())])
            subprocess.run([*command, '--input', str(original), '--output', str(moved)], check=True, capture_output=True)
            self.assertEqual(source_paths(moved.read_text(encoding='utf-8')), [str(moved.resolve())])
            actual = r'D:\交付\真实位置 #3.html'
            subprocess.run([*command, '--input', str(moved), '--source-path', actual], check=True, capture_output=True)
            self.assertEqual(source_paths(moved.read_text(encoding='utf-8')), [actual])

    def test_renderer_cli_binds_final_output_and_explicit_delivery_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / '中文 report #1.html'
            command = [sys.executable, str(SKILL / 'scripts/render_report.py'), '--input',
                       str(SKILL / 'examples/change.json'), '--output', str(output)]
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(source_paths(output.read_text(encoding='utf-8')), [str(output.resolve())])
            actual = '/delivered/真实 report #1.html'
            subprocess.run([*command, '--source-path', actual], check=True, capture_output=True)
            self.assertEqual(source_paths(output.read_text(encoding='utf-8')), [actual])

    def test_checked_in_templates_are_unbound_and_operations_css_is_inlined(self):
        for name in ('reference-report.html', 'operations-report.html'):
            page = (SKILL / 'assets' / name).read_text(encoding='utf-8')
            with self.subTest(name=name):
                self.assertEqual(source_paths(page), [])
                self.assertIn('虚构', page)
                self.assertIn('data-rfh-copy-path', page)
        css = (SKILL / 'assets/operations-theme.css').read_text(encoding='utf-8')
        self.assertIn(css, (SKILL / 'assets/operations-report.html').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
