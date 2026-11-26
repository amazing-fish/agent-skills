# report-for-human@v2.1.0 数据契约与结构规范

`report-for-human@v2.1.0` 仅支持三类单文件交互式 HTML 汇报，均由 `scripts/render_report.py --mode <approval|handoff|briefing> --input <data.json> --output <report.html>` 渲染，并经 `scripts/validate_report.py` 强制校验。彻底废止旧版静态对比/运维长表格式。

## 1. 三态路由

| 模式 | `mode` | 适用场景 | 特色交互与校验重点 |
| --- | --- | --- | --- |
| **Mode A** | `approval` | PR 勾选批准、门禁授权开关与判据签字回执 | SVG 堆叠拓扑（可点击+键盘激活）、PR 批量栏、门禁开关（`authorized` 优先、`default_enabled` 回退）、Tab 1/2 跨 Tab 同步回执、Tab 3 预备 Prompt |
| **Mode B** | `handoff` | 合入落盘汇报、冲突解决说明与跨机启动指令 | 冲突高亮横幅、状态 Pills（含 `blocked`+`deferred`）+ 关键字搜索、门禁落盘审计、Tab 3 动态下一环 Prompt |
| **Mode C** | `briefing` | 分层架构蓝图、能力/业务资产盘点与阶段路线图 | Tab 1 交互式分层架构 SVG + 3 要素差距卡（`现状`/`目标设计`/`核心卡点 / 债务`）、Tab 2 类别筛选 + 搜索、Tab 3 平台能力矩阵 + 路线图 + 可复制执行摘要 |

> 严禁混用模式；凡存在待人类批准/授权事项，必须路由 Mode A。

## 2. 通用必填顶层字段（3 态共用）

- `mode`: `"approval" | "handoff" | "briefing"`
- `meta`: `project_name`、`main_head_sha`、`main_head_url`（合法 `http(s)://`）、可选 `main_head_short`、`report_title`、`report_subtitle`、`generated_at`
- `steps`: 长度必须为 `3`，每项含 `actor`、`status`（`done|active|pending`）、`status_label`、`title`、`description`、`dependency`
- `kpis`: 长度必须为 `4`，每项含 `label`、`value`、`subtext`，可选 `tone`（`default|accent|success|warning|danger`）、`mono`、`url`
- `prompt`: `target_machine`、`default_mode`、`preamble`、`zero_artifact_constraint`、`modes[]`（`id` 字符串比较）、`modules[]`。其中 `zero_artifact_constraint` 始终作为不可覆盖基线条款（`零图片/零文件回传约束：严禁回传截图、图片、压缩包或任何本地附件文件，仅以结构化纯文本/Markdown 汇报执行结果、关键命令摘要与可验证 GitHub 链接。`）的**补充约束**：无论自定义文本是否包含策略关键词，渲染 HTML 与拷贝 Prompt 均严格保留完整的规范基线条款。

## 3. 模式专属字段

### Mode A（`approval`）& Mode B（`handoff`）
- `prs[]`：`id`、`number`、`title`、`url`、`head_branch`、`base_branch`、`status`（Mode A：`ready|approved|warning|blocked`；Mode B：`merged|conflict_resolved|blocked|deferred`）、`status_label`、`ci_status`、`summary`；Mode A 另含 `default_checked`、`depends_on[]`；Mode B 另含 `merge_commit_sha`、`merge_commit_url`、`conflict_note`；可选 `behavior_changes[]`（默认常显、禁止折叠，每项须含非空 `capability`、`before`、`after`、`impact`、`recovery`，可选 `source` 与 `objection_status`）
- `conflicts`（Mode B 必填）：`has_conflicts`、`summary`、`items[]`
- `gates[]`（可选）：`id`、`title`、`description`、`url`、`authorized`（布尔；兼容 `default_enabled`）
- `criteria[]`：`id`、`code`、`title`、`url`、`link_label`、`default_checked`、`status`、`status_label`；强制 3 个非 `null` 且长度 >= 4 的字符串字段 `target_and_status`、`ruling`、`unlock_and_blockers`

### Mode C（`briefing`）
- `architecture`：`layers[]`（`id`、`name`、`status` `ready|partial|gap`、`gap_id`、`summary`）、`horizontals[]`（`id`、`name`、`detail`）
- `gaps[]`：`id`、`code`、`title`、`severity`（`ok|medium|high`）、`status_label`；强制 3 个非空字符串字段 `current_state`、`target_design`、`blocker`
- `filter_options[]`：`[{"id": "all", "label": "全部"}, ...]`
- `inventory[]`：`id`、`title`、`kind`、`kind_label`、`maturity`、`tone`、`summary`、`details`（支持纯文本或白名单富文本 HTML，如 `table`/`thead`/`tbody`/`tfoot`/`caption`/`tr`/`th`/`td`/`p`/`ul`/`ol`/`li`/`code`/`pre`/`h4`/`h5`/`details`/`summary`/`b`/`strong`/`i`/`em`/`span`/`div`/`br`/`hr`；属性仅允许 `class`/`colspan`/`rowspan`/`scope`/`open`，禁止脚本、事件处理器与外链资源）
- `platform_capabilities[]`：`title`、`status`、`tone`、`current`、`gap`
- `roadmap[]`：`phase`、`title`、`detail`

## 4. 跨机治理解约与安全红线

- **身份与 preflight**：配套 `execute-github-issue-pr-workflow` 时在文案/Prompt 明确 `执行者`（如 `氖基米 (neon)`）、`goal-prompt preflight` 状态与完整 `main HEAD` SHA。
- **零外传与零内网泄露**：严禁写入截图、原始 UI 树 JSON、设备序列号、明文密码/PIN 或 raw diff hunk；GitHub 变更一律使用 Commit / PR 永久链接。
- **确定性命令行**：
  ```bash
  python <skill-root>/scripts/render_report.py --mode <approval|handoff|briefing> --input <data.json> --output <report.html>
  python <skill-root>/scripts/validate_report.py <report.html> --mode <approval|handoff|briefing>
  ```
