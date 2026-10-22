from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'report-for-human'


class HumanReportPolicyTests(unittest.TestCase):
    def test_discovery_covers_explanation_and_new_pr(self):
        main = (SKILL / 'SKILL.md').read_text()
        for value in ('name: report-for-human', '没看懂改动', '不清楚要求或规范', '当前现状',
                      '提交新的 PR 后也主动生成', '`change`', '`requirements`', '`status`', '`mechanism`'):
            self.assertIn(value, main)
        self.assertIn('纯讲解不强造 PR 或合入结论', main)
        self.assertIn('汇报不授予实现、发送、发布或合并权限', main)
        self.assertLessEqual(len(main.splitlines()), 100)
        for ref in re.findall(r'\]\(((?:references|assets)/[^)]+)\)', main):
            self.assertTrue((SKILL / ref).is_file(), ref)

    def test_new_pr_report_is_delivered_before_review_finishes(self):
        workflow = (ROOT / 'skills/execute-github-issue-pr-workflow/SKILL.md').read_text()
        self.assertIn('After creating each new PR', workflow)
        self.assertIn('immediately deliver a concise visual HTML report', workflow)
        self.assertIn('while CI or review is pending', workflow)
        self.assertIn('`report-for-human`', workflow)
        self.assertNotIn('`explain-diff-for-human-review`', workflow)
        self.assertLess(workflow.index('After creating each new PR'), workflow.index('## Check Codex Review'))

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

    def test_design_is_reproducible_and_sources_stay_truthful(self):
        main = (SKILL / 'SKILL.md').read_text()
        patterns = (SKILL / 'references/explanation-patterns.md').read_text()
        for value in ('render_report.py', 'reference-report.html', 'reference-preview.png', '内联到 HTML', '390px'):
            self.assertIn(value, main)
        for value in ('接口条件／规范要求', '单条记录采集时间', '不证明上游已产生新数据',
                      '不请求网络、不改配置', '无脚本', '打印', 'textContent', 'aria-live'):
            self.assertIn(value, patterns)
        css = (SKILL / 'assets/report-layout.css').read_text()
        self.assertNotRegex(css, r'#[0-9a-fA-F]{3,8}\b|rgba?\(')
        self.assertNotIn('url(', css)
        self.assertNotIn('@import', css)
        for value in ('.human-report', '.rf-flow-mobile', 'max-width: 760px', '@media print', 'min-height: 44px'):
            self.assertIn(value, css)


if __name__ == '__main__':
    unittest.main()
