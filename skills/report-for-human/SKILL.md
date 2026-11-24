---
name: report-for-human
description: >-
  生成面向人类决策、跨机交接与架构深度盘点的单文件交互式 HTML 汇报（report-for-human@v2.1.0，
  强制路由 Mode A 审批态 approval / Mode B 交接态 handoff / Mode C 深度架构盘点 briefing，
  纯原生 CSS 零外部 CDN 依赖；彻底废止旧版静态/运维表格格式）。
---

# report-for-human (v2.1.0)

本技能将 GitHub PR 审批与判据签字、跨机落盘交接、项目架构深度分析渲染为**单文件、离线可用、交互一致**的 HTML5 汇报页面。**严禁**回退到旧版静态长表、Piano 模板或 `operations-report` 格式。

## 1. 三态模式路由（生成前先定态，禁止混用）

| 模式 | `mode` | 适用场景 | 模板骨架 | 示例 |
| --- | --- | --- | --- | --- |
| **Mode A** | `approval` | PR 勾选批准、前置门禁授权、判据签字并生成实时审批回执 | [`templates/approval_report.html`](templates/approval_report.html) | [`examples/approval.example.json`](examples/approval.example.json) |
| **Mode B** | `handoff` | 已授权项落盘汇报、冲突解决说明与跨机下一环启动 Prompt | [`templates/handoff_report.html`](templates/handoff_report.html) | [`examples/handoff.example.json`](examples/handoff.example.json) |
| **Mode C** | `briefing` | 系统分层架构图、能力 vs 业务盘点、缺口审计与演进路线 | [`templates/briefing_report.html`](templates/briefing_report.html) | [`examples/briefing.example.json`](examples/briefing.example.json) |

- 只要本轮仍有**待人类决策/授权**才能合入的 PR 或判据，一律路由 **Mode A**；无决策时的项目/架构盘点路由 **Mode C**；合入收口或跨机启动路由 **Mode B**。
- 新建 PR 后立即生成 Mode A 报告（标明审查仍在运行）；随事实变化刷新同一文件；纯讲解不强造 PR 或合入结论，汇报不授予合入或执行权限。

## 2. 6 项结构与视觉硬约束

1. **Sticky 吸顶控制栏**：项目名、模式徽章、可点击 `main HEAD` Commit 链接、实时计数徽章、`浅色 / 深色 / 系统` 3 态主题切换，以及全局一键复制主按钮（任意 Tab 下均可直达复制）。
2. **显式 3-Step 顺序条**：紧贴标题下方，展示 3 张卡片标明 `Step 1 → Step 2 → Step 3` 的执行方、状态与强先后依赖。
3. **4 卡 KPI 概览**：首屏展示 4 张可核验硬数字/SHA 卡片，区分事实、推断与缺口限制。
4. **3-Tab 视图隔离**（支持方向键切换，`@media print` 自动全量展开）：
   - **Mode A**：Tab 1 PR 勾选 + 可点击/键盘操作 SVG 堆叠拓扑；Tab 2 门禁开关 + 3 要素判据矩阵；Tab 1/2 底部实时同步回执；Tab 3 预备 Prompt。
   - **Mode B**：Tab 1 冲突高亮条 + 状态筛选 Pills + 关键字搜索；Tab 2 门禁审计 + 落盘矩阵；Tab 3 动态下一环 Prompt。
   - **Mode C**：Tab 1 交互式分层架构 SVG + 3 要素差距分析；Tab 2 资产/能力分类筛选与搜索；Tab 3 平台能力矩阵 + 演进路线 + 可复制执行摘要。
5. **零外部资源 + 降级复制**：纯内联原生 CSS（`prefers-color-scheme: dark` 与 `@media print`），严禁 `http(s)://` 或协议相对 `//` 外部样式/脚本/SVG 资源；复制需兼容 `clipboard.writeText` 与 `textarea` 降级且不虚报成功。
6. **版本水印**：`<footer>` 必须包含 `report-for-human@v2.1.0`。

## 3. 事实、审查与脱敏边界

- 核验真实 `base_sha` / `head_sha`、状态与证据时间；按 [PR 审查规则](references/pr-review.md) 与 [证据边界](references/evidence.md) 区分真实行为、推断与缺口；复杂分支可用只读独立审查，不提供预期结论。
- GitHub 报告一律不在 HTML 中复制 raw diff、patch 或 diff hunk；使用真实 GitHub Commit/PR 永久链接；**严禁**写入截图原图、原始 UI 树 JSON、设备序列号、明文账号或密码/PIN。

## 4. 确定性渲染与交付前校验

字段 Schema 见 [`references/data-schema.md`](references/data-schema.md)。严格通过脚本生成并复检（禁止手写拼接 HTML 或写入技能安装目录）：

```bash
python <skill-root>/scripts/render_report.py \
  --mode <approval|handoff|briefing> \
  --input <verified-data.json> \
  --output <report.html>

python <skill-root>/scripts/validate_report.py <report.html> --mode <approval|handoff|briefing>
```

输出路径优先使用 `scripts/resolve_report_path.py` 解析（用户指定路径 → 仓库 `reports/` → 工作区），交付前须确保 `validate_report.py` 退出码 `0` 且无遗留 `{{PLACEHOLDER}}`。
