import copy
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/report-for-human'
spec = importlib.util.spec_from_file_location('report_renderer', SKILL / 'scripts/render_report.py')
renderer = importlib.util.module_from_spec(spec)
with patch.object(sys, 'path', [str(SKILL / 'scripts'), *sys.path]):
    spec.loader.exec_module(renderer)


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.tags = []; self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class ReportRendererTests(unittest.TestCase):
    def example(self, kind):
        return json.loads((SKILL / 'examples' / f'{kind}.json').read_text())

    def test_every_problem_type_renders_offline_with_traceable_evidence(self):
        for kind in renderer.KINDS:
            with self.subTest(kind=kind):
                html = renderer.render(self.example(kind)); parsed = Elements(html)
                self.assertIn('虚构', html)
                self.assertTrue(any(tag == 'h1' for tag, _ in parsed.tags))
                self.assertFalse(any(tag == 'details' for tag, _ in parsed.tags))
                self.assertIn('本次无需你作决定', html)
                self.assertIn('判断依据与必要参考', html)
                self.assertFalse(any(tag in {'iframe','img','link'} for tag, _ in parsed.tags))
                self.assertFalse(any(tag == 'script' and 'src' in a for tag, a in parsed.tags))
                self.assertNotIn('fetch(', html)
                self.assertNotIn('XMLHttpRequest', html)

    def test_external_text_cannot_escape_markup_or_json_script(self):
        d = self.example('mechanism')
        attack = '</script><img src=x onerror=alert(1)>'
        d['title'] = attack; d['scenarios'][0]['summary'] = attack
        html = renderer.render(d); parsed = Elements(html)
        self.assertFalse(any(tag == 'img' for tag, _ in parsed.tags))
        self.assertEqual(sum(tag == 'script' for tag, _ in parsed.tags), 3)
        self.assertIn('&lt;/script&gt;', html)
        self.assertIn('\\u003c/script\\u003e', html)

    def test_dangerous_evidence_urls_are_rejected(self):
        for url in ['javascript:alert(1)', 'data:text/html,hello', 'file:///private', '//example.com']:
            d = self.example('status'); d['evidence'][0]['url'] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                renderer.render(d)

    def test_unknown_stage_is_not_presented_as_completed(self):
        d = self.example('status'); d['stages'] = [{'state':'unknown','title':'实机验收','detail':'未读取设备'}]
        html = renderer.render(d)
        stage_states = [a['data-state'] for tag, a in Elements(html).tags if tag == 'li' and 'data-state' in a]
        self.assertEqual(stage_states, ['unknown'])

    def test_graph_and_scenarios_reject_unresolvable_relations(self):
        d = self.example('mechanism')
        for mutate in [lambda x: x['graph']['edges'][0].update(to='missing'),
                       lambda x: x['scenarios'][0].update(active_nodes=['missing']),
                       lambda x: x['graph']['nodes'][1].update(id=x['graph']['nodes'][0]['id'])]:
            invalid = copy.deepcopy(d); mutate(invalid)
            with self.assertRaises(ValueError):
                renderer.render(invalid)

    def test_decision_must_be_explicit_and_stays_before_main_visual(self):
        d = self.example('change')
        d.pop('decision')
        with self.assertRaisesRegex(ValueError, 'Explicit decision'):
            renderer.render(d)
        d['decision'] = {'status': 'required', 'question': '是否试用？',
                         'recommendation': '先验收', 'next_step': '维护者补证据'}
        page = renderer.render(d)
        self.assertLess(page.index('需要你决定：是否试用？'), page.index('id="visual-heading"'))
        self.assertIn('维护者补证据', page)
        for field in ('question', 'recommendation', 'next_step'):
            invalid = copy.deepcopy(d); invalid['decision'][field] = ''
            with self.assertRaises(ValueError):
                renderer.render(invalid)

    def test_only_explicit_supplements_collapse_and_tabs_start_visible(self):
        d = self.example('status')
        d['reference_tabs'] = [
            {'label': '验收', 'summary': '必要结果', 'evidence': d['evidence']},
            {'label': '来源', 'summary': '必要来源', 'evidence': []}]
        d['supplementary_evidence'] = [{'label': '原始记录', 'detail': '可跳过'}]
        page = renderer.render(d); tags = Elements(page).tags
        panels = [a for _, a in tags if a.get('role') == 'tabpanel']
        self.assertEqual(len(panels), 2)
        self.assertTrue(all('hidden' not in panel for panel in panels))
        self.assertEqual(sum(tag == 'details' for tag, _ in tags), 1)
        self.assertIn('<details><summary>补充材料（可跳过）</summary>', page)
        self.assertLess(page.index('必要结果'), page.index('<details>'))
        d['reference_tabs'] = d['reference_tabs'][:1]
        with self.assertRaises(ValueError):
            renderer.render(d)

    def test_reference_is_generated_from_current_synthetic_example(self):
        self.assertEqual(renderer.render(self.example('mechanism')), (SKILL / 'assets/reference-report.html').read_text())


if __name__ == '__main__':
    unittest.main()
