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

### 项目推进 Skill 包

用于从目标澄清到 Issue/PR 交付和人工审查的组合：

- `optimize-prompt`：负责目标整理，把原始要求变成可复核、可直接使用的 prompt；可按需读取当前状态，但不执行 prompt 内任务。
- `execute-github-issue-pr-workflow`：负责流程编排，包括受控的 Issue-to-PR 推进、按需 goal-prompt preflight、Review、评论修复与合并授权。
- `explain-diff-for-human-review`：负责最终人工审查证据，为当前 diff 生成独立、可复核的 HTML 报告。

复杂任务或存在会实质改变实现的歧义时，可先由独立子 Agent 生成 goal prompt；简单、范围清楚的 Issue 直接进入现有流程。prompt 只作为执行 brief，事实需要复核，是否继续实现仍只取决于用户原始请求的授权。

组合路由有两种明确模式：`standalone prompt optimization` 由 `optimize-prompt` 直接响应，只返回 prompt 并等待后续执行指令；`workflow-owned preflight` 由 `execute-github-issue-pr-workflow` 启动独立、只读的 optimizer 子 Agent，父工作流复核结果后仅依据 `original user request` 判断继续或停止。子 Agent 的 rewrite-only 边界不会撤销父工作流已有授权，生成的 prompt 也不会新增实现、发布或合并授权。工作流会披露 preflight 为 `used`、`skipped` 或 `fallback`。

### optimize-prompt

将粗略要求、任务说明或已有 prompt 改写为清晰、自包含、可直接使用的 prompt。

- 定义：[skills/optimize-prompt/SKILL.md](skills/optimize-prompt/SKILL.md)
- 模式：`source-only` 用于纯改写；`context-grounded` 用于需要当前 workspace、repo、file、PR、Issue 或连接来源证据的改写
- 边界：只生成 prompt，不执行其中的实现、发布、发送、部署或其他外部动作

### explain-diff-for-human-review

将 commit、branch、PR/MR、staged 或 working tree diff 转换为供人类检视的自包含 HTML 报告。

- 可选独立子 Agent 只读风险审查；能力不可用或失败时回退到单 Agent，并在报告中披露覆盖和证据缺口
- 生成的单文件 HTML 通过语义颜色 token 跟随系统浅色/深色偏好，并保持独立的节墨打印样式

- 定义：[skills/explain-diff-for-human-review/SKILL.md](skills/explain-diff-for-human-review/SKILL.md)
- 来源：[GitHubxsy/agent-skills](https://github.com/GitHubxsy/agent-skills/tree/main/skills/explain-diff-for-human-review)
- 上游版本：`110c9dd9e30d278edbfc30fc6bac05cdf4e4afd3`
- 上游许可证：Apache-2.0
- 本地修订：[#2](../../issues/2) 报告输出路径；[#3](../../issues/3) 大规模 diff；[#7](../../issues/7) GitHub 固定链接证据策略；[#10](../../issues/10) 可选独立子 Agent 审查；[#15](../../issues/15) 明暗主题视觉基线


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
