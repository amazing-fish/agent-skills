from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "explain-diff-for-human-review" / "SKILL.md"


class HumanDecisionBriefPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.instructions = SKILL.read_text(encoding="utf-8")

    def test_pr_decision_is_default_and_not_approval(self):
        for required in (
            "默认只接受已提交的 PR",
            "base_sha",
            "head_sha",
            "建议合入",
            "需要修改",
            "证据不足，暂缓决定",
            "不审批或合并 PR",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.instructions)

    def test_truthful_evidence_and_regression_boundary(self):
        for required in (
            "逐项对照需求",
            "跨文件",
            "本次引入缺陷",
            "主干既有问题",
            "未验证",
            "固定到 `base_sha...head_sha`",
            "不复制仓库源码",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.instructions)

    def test_main_instructions_stay_decision_focused(self):
        self.assertLessEqual(len(self.instructions.splitlines()), 85)
        self.assertIn("一屏可读的决策摘要", self.instructions)
        self.assertIn("按需展开", self.instructions)
        for obsolete_heading in ("### 影响矩阵", "### 替代方案", "### 检视清单与理解问答"):
            self.assertNotIn(obsolete_heading, self.instructions)

    def test_no_local_snapshot_or_extra_business_setup(self):
        self.assertIn("不要把 staged、working-tree、untracked 状态冒充已提交证据", self.instructions)
        self.assertIn("生成物不写回 Skill 安装目录", self.instructions)
        self.assertIn("单 Agent 回退", self.instructions)


if __name__ == "__main__":
    unittest.main()
