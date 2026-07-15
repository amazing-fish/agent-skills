# Agent Skills

个人使用的 Agent Skills 集合。每个 Skill 保持独立、可追溯、可验证。

## 目录

```text
skills/
└── <skill-name>/
    ├── SKILL.md
    ├── agents/       # 可选：界面元数据
    ├── scripts/      # 可选：确定性脚本
    ├── references/   # 可选：按需加载的参考资料
    └── assets/       # 可选：输出模板或静态资源
```

仓库级文件：

- `sources.lock.json`：记录外部 Skill 的来源、固定版本和许可证。
- `.github/ISSUE_TEMPLATE/`：统一改进项与缺陷的描述格式。
- Skill 运行生成的 `reports/` 不提交。

## 已收录 Skills

### explain-diff-for-human-review

将 commit、branch、PR/MR、staged 或 working tree diff 转换为供人类检视的自包含 HTML 报告。

- 定义：[skills/explain-diff-for-human-review/SKILL.md](skills/explain-diff-for-human-review/SKILL.md)
- 来源：[GitHubxsy/agent-skills](https://github.com/GitHubxsy/agent-skills/tree/main/skills/explain-diff-for-human-review)
- 上游版本：`110c9dd9e30d278edbfc30fc6bac05cdf4e4afd3`
- 上游许可证：Apache-2.0
- 本地修订：[#2](../../issues/2) 报告输出路径；[#3](../../issues/3) 大规模 diff；[#7](../../issues/7) GitHub 固定链接证据策略


### execute-github-issue-pr-workflow

按受控闭环推进 GitHub Issue、实现、PR、Codex Review、评论修复、人工 diff 审查、合并授权和文档更新。

- 定义：[skills/execute-github-issue-pr-workflow/SKILL.md](skills/execute-github-issue-pr-workflow/SKILL.md)
- 默认模式：人工批准当前 PR 合入并进入下一 Issue
- 自动暂存模式：低风险 PR 保持未合并并继续推进，最终由人类统一决定方向
- 评审节拍：每次只设一个一次性 6 分钟定时器；触发后刷新一次，以 PR 上 Codex 机器人的 👍 为通过信号


## 管理约定

1. 外部 Skill 首次引入时保持内容语义不变，并在 `sources.lock.json` 同时记录上游 blob SHA 与导入版本。
2. 本地修改必须通过 Issue 说明动机、验收标准和兼容性影响。
3. 修改过的外部文件应在 PR 中明确标注变更，不覆盖来源记录。
4. 合入前检查 frontmatter、链接、敏感信息和生成物。

## License

本仓库采用 [Apache License 2.0](LICENSE)。外部 Skill 的来源、固定版本和修改记录见 `sources.lock.json`。
