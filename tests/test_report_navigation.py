"""Offline integration/static contracts and mocked DOM, not browser visual acceptance."""
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/report-for-human'
spec = importlib.util.spec_from_file_location('navigation_report_controls', SKILL / 'scripts/add_report_controls.py')
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def fixture():
    groups = []
    for prefix in ['facts', 'evidence']:
        buttons = ''.join(f'<button id="{prefix}-t{i}" aria-controls="{prefix}-p{i}" type="button">项目 {i}</button>' for i in range(3))
        panels = ''.join(f'<section id="{prefix}-p{i}" role="tabpanel"><h2>必要内容 {prefix} {i}</h2></section>' for i in range(3))
        groups.append(f'<section class="rfh-tabs"><div role="tablist" aria-label="{prefix}">{buttons}</div>{panels}</section>')
    return '<!doctype html><html><head><title>测试报告</title></head><body><main class="human-report">' + ''.join(groups) + '<figure class="rfh-figure"><a class="rfh-image-link" href="data:image/png;base64,AAAA"><img src="data:image/png;base64,AAAA" alt="完整图"></a><figcaption>来源说明</figcaption></figure></main></body></html>'


class NavigationTests(unittest.TestCase):
    def test_assets_inline_once_and_existing_content_is_preserved(self):
        source = fixture()
        html = controls.enhance_report(source, source_path='/tmp/report.html')
        twice = controls.enhance_report(html)
        for name in ['report-navigation.css', 'report-navigation.js']:
            asset = (SKILL / 'assets' / name).read_text()
            self.assertEqual(html.count(asset), 1)
            self.assertEqual(twice.count(asset), 1)
        self.assertEqual(twice.count(controls.HEAD_START), 1)
        parsed = Elements(twice).tags
        self.assertEqual(sum(a.get('role') == 'tabpanel' for _, a in parsed), 6)
        for tag, attrs in parsed:
            if attrs.get('role') == 'tabpanel':
                self.assertNotIn('hidden', attrs, 'All necessary content must remain readable without JS')
            if tag == 'script':
                self.assertNotIn('src', attrs)
        self.assertEqual(sum(tag == 'img' for tag, _ in parsed), 1)
        ids = [a['id'] for _, a in parsed if 'id' in a]
        self.assertEqual(len(ids), len(set(ids)))
        for _, attrs in parsed:
            if 'aria-controls' in attrs:
                self.assertIn(attrs['aria-controls'], ids)
        self.assertIn('value="system"', html)
        self.assertIn('value="light"', html)
        self.assertIn('value="dark"', html)

    def test_synthetic_navigation_example_is_self_contained_and_unbound(self):
        html = (SKILL / 'examples/navigation.html').read_text()
        tags = Elements(html).tags
        self.assertEqual(sum(a.get('role') == 'tabpanel' for _, a in tags), 3)
        images = [a for tag, a in tags if tag == 'img']
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0]['src'].startswith('data:image/png;base64,'))
        self.assertIn('程序生成的虚构示意', html)
        self.assertNotIn('report-source-path', html.split('</head>')[0].split('<script')[0])
        for name in ('report-navigation.css', 'report-navigation.js'):
            self.assertIn((SKILL / 'assets' / name).read_text(), html)

    def test_no_js_and_print_rules_preserve_reference_content(self):
        css = (SKILL / 'assets/report-navigation.css').read_text()
        self.assertIn('.rfh-tabs:not([data-tabs-ready])>[role="tablist"]{display:none}', css)
        printing = css.split('@media print', 1)[1]
        self.assertIn('.rfh-tabs>[role="tabpanel"][hidden]{display:block!important}', printing)
        self.assertIn('.rfh-tabs>[role="tablist"],.rfh-image-dialog{display:none!important}', printing)
        self.assertNotIn('details', css)

    def test_images_are_bounded_uncropped_and_original_size_is_available(self):
        css = (SKILL / 'assets/report-navigation.css').read_text()
        preview = css.split('.rfh-image-link img{', 1)[1].split('}', 1)[0]
        for rule in ['max-height:240px', 'max-width:100%', 'height:auto', 'width:auto', 'object-fit:contain']:
            self.assertIn(rule, preview)
        original = css.split('.rfh-image-dialog[data-original="true"] .rfh-image-stage img{', 1)[1].split('}', 1)[0]
        self.assertIn('max-width:none', original)
        self.assertIn('max-height:none', original)
        self.assertIn('overflow:auto', css)
        self.assertIn('@media(max-width:600px)', css)
        self.assertIn('html[data-report-theme="dark"]', css)

    @unittest.skipUnless(shutil.which('node'), 'Node required for mocked DOM regression checks')
    def test_mocked_dom_keyboard_dialog_and_theme_behavior(self):
        result = subprocess.run(['node', str(ROOT / 'tests/report_navigation_behavior.cjs')], check=True, capture_output=True, text=True)
        self.assertIn('Mocked DOM', result.stdout)


if __name__ == '__main__':
    unittest.main()
