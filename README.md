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
- `report-for-human`：解释改动、要求、现状与机制，并在新 PR 创建后主动生成简洁、可核验的可视化 HTML 汇报。

复杂任务或存在会实质改变实现的歧义时，可先由独立子 Agent 生成 goal prompt；简单、范围清楚的 Issue 直接进入现有流程。prompt 只作为执行 brief，事实需要复核，是否继续实现仍只取决于用户原始请求的授权。

组合路由有两种明确模式：`standalone prompt optimization` 由 `optimize-prompt` 直接响应，只返回 prompt 并等待后续执行指令；`workflow-owned preflight` 由 `execute-github-issue-pr-workflow` 启动独立、只读的 optimizer 子 Agent，父工作流复核结果后仅依据 `original user request` 判断继续或停止。子 Agent 的 rewrite-only 边界不会撤销父工作流已有授权，生成的 prompt 也不会新增实现、发布或合并授权。工作流会披露 preflight 为 `used`、`skipped` 或 `fallback`。

### optimize-prompt

将粗略要求、任务说明或已有 prompt 改写为清晰、自包含、可直接使用的 prompt。

- 定义：[skills/optimize-prompt/SKILL.md](skills/optimize-prompt/SKILL.md)
- 模式：`source-only` 用于纯改写；`context-grounded` 用于需要当前 workspace、repo、file、PR、Issue 或连接来源证据的改写
- 边界：只生成 prompt，不执行其中的实现、发布、发送、部署或其他外部动作

### report-for-human

由 `explain-diff-for-human-review` 演进重构为 **`report-for-human@v2.1.0`**，彻底废止旧版静态长表与运维范例，统一采用单文件、零外部 CDN、支持 `浅色 / 深色 / 系统` 三态主题的交互式 3-Tab HTML5 汇报体系：

- **Mode A（`approval`）**：PR 勾选批准、可点击/键盘操作 SVG 堆叠依赖拓扑、前置门禁开关、3 要素判据签字矩阵与跨 Tab 实时同步回执。
- **Mode B（`handoff`）**：合入落盘汇报、冲突解决高亮条、状态筛选 Pills、关键字搜索、门禁落盘审计与下一环动态启动 Prompt。
- **Mode C（`briefing`）**：系统分层架构图（SVG + 差距分析卡）、资产与能力重审计筛选、使用能力/跨端矩阵与分阶段演进路线。
- 共用确定性 CLI：`skills/report-for-human/scripts/render_report.py --mode <approval|handoff|briefing>` 与 `skills/report-for-human/scripts/validate_report.py`。
- 严格遵守零外链/零凭据外传/GitHub diff 仅保留永久链接与可选只读独立审查规则；汇报本身不授予实现或合入权限。
- 定义：[skills/report-for-human/SKILL.md](skills/report-for-human/SKILL.md) · 数据契约：[skills/report-for-human/references/data-schema.md](skills/report-for-human/references/data-schema.md)
- 原始来源：[GitHubxsy/agent-skills](https://github.com/GitHubxsy/agent-skills/tree/main/skills/explain-diff-for-human-review)，Apache-2.0，演进记录见 `sources.lock.json`。

### execute-github-issue-pr-workflow

按受控闭环推进 GitHub Issue、实现、PR、CodeRabbit 等 AI Reviewer 审查、评论修复、人工 diff 审查、合并授权和文档更新，并在协作产出中显式标注执行者身份（如 `neon` 调度器为 `氖基米`、`carbon` 调度器为 `碳基米`）。

- 定义：[skills/execute-github-issue-pr-workflow/SKILL.md](skills/execute-github-issue-pr-workflow/SKILL.md)
- 默认模式：人工批准当前 PR 合入并进入下一 Issue
- 自动暂存模式：低风险 PR 保持未合并并继续推进，最终由人类统一决定方向
- 评审节拍：依次等待 6+4+2+8 分钟，累计第 6、10、12、20 分钟检查（覆盖 CodeRabbit 等已配置 AI reviewer 检查与未解决线程；不依赖远端 GitHub Actions CI，测试与校验在本地执行）；每次只设一个一次性定时器，触发后刷新一次，完成即停止，第 20 分钟仍未完成则记录 pending。跨会话保留阶段和截止时间，并报告目标本地时间、目标时区和已核验 next run。完整规则以 [workflow Skill](skills/execute-github-issue-pr-workflow/SKILL.md) 为事实来源

### douyin-video-analysis

把抖音分享链接或分享文本转成证据驱动的学习型研究报告。

- 定义：[skills/douyin-video-analysis/SKILL.md](skills/douyin-video-analysis/SKILL.md)
- 证据：页面文案、免费/本地转写、关键帧和必要的浏览器诊断
- 输出：解释主题、结构、术语、技巧、原理、学习路径与验证边界，不把完整转写或中间产物清单当作正文
- 运行时边界：Skill 不自带抓取器或转写模型；优先复用当前工作区已有的兼容解析器，否则按 Skill 的降级流程收集证据


## 管理约定

1. 外部 Skill 首次引入时保持内容语义不变，并在 `sources.lock.json` 同时记录上游 blob SHA 与导入版本。
2. 本地修改必须通过 Issue 说明动机、验收标准和兼容性影响。
3. 修改过的外部文件应在 PR 中明确标注变更，不覆盖来源记录。
4. 合入前检查 frontmatter、链接、敏感信息和生成物。
5. PR 合入前必须在本地通过仓库策略测试（`python -m unittest discover -s tests`）与 `git diff --check`，不依赖远端 GitHub Actions CI。

## License

本仓库采用 [Apache License 2.0](LICENSE)。外部 Skill 的来源、固定版本和修改记录见 `sources.lock.json`。
