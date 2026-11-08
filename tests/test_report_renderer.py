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
        super().__init__(); self.tags = []; self.stack = []; self.content = []; self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append((tag, dict(attrs)))
    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                self.stack = self.stack[:i]
                break
    def handle_data(self, data):
        if data.strip() and not any(tag in {'script', 'style'} for tag, _ in self.stack):
            self.content.append((data, self.stack[:]))


class ReportRendererTests(unittest.TestCase):
    def example(self, kind):
        return json.loads((SKILL / 'examples' / f'{kind}.json').read_text())

    def test_every_problem_type_renders_offline_with_traceable_evidence(self):
        for kind in renderer.KINDS:
            with self.subTest(kind=kind):
                html = renderer.render(self.example(kind)); parsed = Elements(html)
                self.assertIn('虚构', html)
                self.assertTrue(any(tag == 'h1' for tag, _ in parsed.tags))
                self.assertTrue(any(tag == 'details' and 'open' not in a for tag, a in parsed.tags))
                self.assertIn('本次无需你作决定', html)
                self.assertFalse(any(a.get('role') == 'tablist' for _, a in parsed.tags))
                self.assertFalse(any(tag in {'iframe','img','link'} for tag, _ in parsed.tags))
                self.assertFalse(any(tag == 'script' and 'src' in a for tag, a in parsed.tags))
                self.assertNotIn('fetch(', html)
                self.assertNotIn('XMLHttpRequest', html)

    def test_external_text_cannot_escape_markup_or_json_script(self):
        d = self.example('mechanism')
        attack = '</script><img src=x onerror=alert(1)>'
        d['title'] = attack; d['scenarios'][0]['summary'] = attack
        d['decision_facts'] = [{'text': attack}]
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

    def test_peer_alternatives_keep_no_script_panels_readable(self):
        d = self.example('status')
        d['reference_tabs'] = [
            {'label': '当日自取', 'summary': '今天可取', 'evidence': []},
            {'label': '预约配送', 'summary': '明天送达', 'evidence': []}]
        d['supplementary_evidence'] = [{'label': '原始记录', 'detail': '可跳过'}]
        page = renderer.render(d); tags = Elements(page).tags
        panels = [a for _, a in tags if a.get('role') == 'tabpanel']
        self.assertEqual(len(panels), 2)
        self.assertTrue(all('hidden' not in panel for panel in panels))
        self.assertEqual(sum(tag == 'details' for tag, _ in tags), 1)
        self.assertLess(page.index('今天可取'), page.index('<details>'))
        d['reference_tabs'] = d['reference_tabs'][:1]
        with self.assertRaises(ValueError):
            renderer.render(d)

    def test_full_evidence_collapses_without_hiding_decisive_facts_or_risk(self):
        d = self.example('change')
        d['decision_facts'] = [{'text': '旧客户端无法提交，暂缓推广。',
                                'url': 'https://example.com/reproduction'}]
        d['limitations'] = ['正式设备未验收，不能声称可上线。']
        labels = ['反例', '兼容性', 'CI', '版本差异', '字段含义', '安全观测', '持续跟踪']
        d['evidence'] = [{'label': label, 'detail': label + '的完整验证记录',
                          'url': 'https://example.com/evidence/' + str(i)}
                         for i, label in enumerate(labels)]
        d['supplementary_evidence'] = [{'label': '旧输入补充', 'detail': '兼容旧字段'}]
        page = renderer.render(d); parsed = Elements(page)
        for needle in [item['detail'] for item in d['evidence']] + ['兼容旧字段']:
            contexts = [ancestors for data, ancestors in parsed.content if data == needle]
            self.assertEqual(len(contexts), 1)
            self.assertTrue(any(tag == 'details' and 'open' not in attrs for tag, attrs in contexts[0]))
            self.assertFalse(any(attrs.get('role') == 'tabpanel' for _, attrs in contexts[0]))
        for needle in [d['decision_facts'][0]['text'], d['limitations'][0]]:
            contexts = [ancestors for data, ancestors in parsed.content if data == needle]
            self.assertEqual(len(contexts), 1)
            self.assertFalse(any(tag == 'details' or attrs.get('role') == 'tabpanel' for tag, attrs in contexts[0]))
            self.assertTrue(any(tag == 'header' for tag, _ in contexts[0]))
        urls = {attrs.get('href') for tag, attrs in parsed.tags if tag == 'a'}
        self.assertTrue({e['url'] for e in d['evidence']} <= urls)
        self.assertIn('https://example.com/reproduction', urls)
        self.assertFalse(any(a.get('role') == 'tablist' for _, a in parsed.tags))

    def test_layers_follow_authored_relevance_not_topic_keywords(self):
        d = self.example('requirements')
        d['decision_facts'] = [{'text': 'CI 阻断本次提交。'}]
        d['evidence'] = [{'label': '当前决定', 'detail': '只是历史决策记录'}]
        parsed = Elements(renderer.render(d))
        for text_value, collapsed in [('CI 阻断本次提交。', False), ('只是历史决策记录', True)]:
            contexts = [ancestors for data, ancestors in parsed.content if data == text_value]
            self.assertEqual(len(contexts), 1)
            self.assertEqual(any(tag == 'details' for tag, _ in contexts[0]), collapsed)
        d['decision_facts'][0]['url'] = 'javascript:alert(1)'
        with self.assertRaises(ValueError):
            renderer.render(d)

    def test_no_empty_reference_chrome_when_no_evidence_or_comparison(self):
        d = self.example('change'); d['evidence'] = []
        tags = Elements(renderer.render(d)).tags
        self.assertFalse(any(tag == 'details' or a.get('id') == 'reference-heading' for tag, a in tags))

    def test_static_templates_keep_supplementary_records_closed(self):
        cases = [('assets/operations-report.html', '本地分层用例 · 虚构数据'),
                 ('examples/navigation.html', '示例输入')]
        for name, needle in cases:
            with self.subTest(template=name):
                parsed = Elements((SKILL / name).read_text())
                contexts = [ancestors for data, ancestors in parsed.content if data == needle]
                self.assertEqual(len(contexts), 1)
                self.assertTrue(any(tag == 'details' and 'open' not in attrs for tag, attrs in contexts[0]))
                self.assertFalse(any(attrs.get('role') == 'tabpanel' for _, attrs in contexts[0]))

    def test_reference_is_generated_from_current_synthetic_example(self):
        self.assertEqual(renderer.render(self.example('mechanism')), (SKILL / 'assets/reference-report.html').read_text())


if __name__ == '__main__':
    unittest.main()
