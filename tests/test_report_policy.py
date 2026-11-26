from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'report-for-human'


class HumanReportPolicyTests(unittest.TestCase):
    def test_v21_three_modes_and_legacy_retirement(self):
        main = (SKILL / 'SKILL.md').read_text(encoding='utf-8')
        for value in (
            'name: report-for-human',
            'report-for-human@v2.1.0',
            'approval',
            'handoff',
            'briefing',
            'render_report.py',
            'validate_report.py',
            '汇报不授予合入或执行权限',
        ):
            self.assertIn(value, main)
        self.assertLessEqual(len(main.splitlines()), 100)
        for ref in re.findall(r'\]\(((?:references|templates|examples)/[^)]+)\)', main):
            self.assertTrue((SKILL / ref).is_file(), ref)
        self.assertFalse((SKILL / 'assets').exists())
        self.assertFalse((SKILL / 'scripts' / 'add_report_controls.py').exists())
        for legacy_example in ('change.json', 'requirements.json', 'status.json', 'mechanism.json', 'navigation.html', 'tables.html'):
            self.assertFalse((SKILL / 'examples' / legacy_example).exists(), legacy_example)

    def test_new_pr_report_is_delivered_before_review_finishes(self):
        workflow = (ROOT / 'skills/execute-github-issue-pr-workflow/SKILL.md').read_text()
        self.assertIn('After creating each new PR', workflow)
        self.assertIn('immediately deliver a concise visual HTML report', workflow)
        self.assertIn('while review is pending', workflow)
        self.assertIn('`report-for-human`', workflow)
        self.assertNotIn('`explain-diff-for-human-review`', workflow)
        self.assertLess(workflow.index('After creating each new PR'), workflow.index('## Check AI Review'))

    def test_pr_review_and_merge_authority_survive_rename(self):
        review = (SKILL / 'references/pr-review.md').read_text()
        workflow = (ROOT / 'skills/execute-github-issue-pr-workflow/SKILL.md').read_text()
        for value in ('默认只接受已提交的 PR', 'base_sha', 'head_sha', '不审批或合并 PR',
                      '本次引入缺陷', '主干既有问题', '未验证', '不要把 staged、working-tree、untracked 状态冒充已提交证据'):
            self.assertIn(value, review)
        verdict = re.search(r'^- \*\*结论：\*\* `([^`]+)`', review, re.M).group(1)
        accepted = re.search(r'stage only when the report says `([^`]+)`', workflow).group(1)
        self.assertEqual(verdict, accepted)
        self.assertIn('Automatic staging never authorizes merging.', workflow)

    def test_references_links_and_screenshot_boundary(self):
        refs_dir = SKILL / 'references'
        for md_path in sorted(refs_dir.glob('*.md')):
            content = md_path.read_text(encoding='utf-8')
            for target in re.findall(r'\]\(([^)#]+\.md)\)', content):
                if target.startswith(('http://', 'https://')):
                    continue
                resolved = (md_path.parent / target).resolve()
                self.assertTrue(resolved.is_file(), f'Broken link in {md_path.name}: {target}')

        evidence = (refs_dir / 'evidence.md').read_text(encoding='utf-8')
        self.assertNotIn('reading-navigation.md', evidence)
        self.assertNotIn('蓝色生成器', evidence)
        self.assertNotIn('自包含 HTML 可内嵌必要截图', evidence)
        self.assertIn('严禁', evidence)
        self.assertIn('待补截图', evidence)
        self.assertIn('data-schema.md', evidence)


if __name__ == '__main__':
    unittest.main()
