# 双态审批与跨机交接规范（Mode A Approval / Mode B Handoff）

当汇报面向**多 PR 堆叠审查 / 判据签字回执**或**多机流水线交接（如云端机 / 家庭机 ↔ 内网工作机）**时，使用本规范与随附的双态确定性渲染器（`scripts/render_dual_mode_report.py`）和校验器（`scripts/validate_dual_mode_report.py`）。

- 既有单问题解释报告（`change` / `requirements` / `status` / `mechanism`）与运维模板（`references/operations-reports.md`）保持 100% 不变；
- 凡涉及 PR 勾选审批、前置门禁授权或跨机状态交接与启动 Prompt，必须先判定进入 **Mode A（`approval`）** 或 **Mode B（`handoff`）**，严禁混用。

## 1. 模式路由表

| 维度 | Mode A · 审批态（`approval`） | Mode B · 完成交接态（`handoff`） |
| --- | --- | --- |
| **适用场景** | 需人类勾选批准 PR、签字确认判据、审批前置门禁开关，并生成结构化文本回执发回执行机 | 批准项已完成合入/签字落盘，需汇报冲突解决说明、主干新 SHA，并生成下一环启动 Prompt |
| **强制模板骨架** | `templates/approval_report.html` | `templates/handoff_report.html` |
| **示例载荷** | `examples/approval.example.json` | `examples/handoff.example.json` |
| **顶栏主复制目标** | 实时审批回执（PR 勾选 + 门禁开关 + 判据签字 + 备注） | 实时下一环启动 Prompt（执行模式 + 勾选模块 + 零外传约束） |
| **Tab 1 特色交互** | PR 勾选框、批量快捷按钮、SVG 堆叠依赖拓扑、依赖冲突提醒 | 冲突解决高亮条、状态筛选 Pills、关键字搜索框 |
| **混合进度裁决** | 只要本轮仍有待人类批准/授权的 PR 或判据，统一路由 **Mode A**（已合入项可在 KPI/说明交代） | 本轮所有待执行决策均已落盘，仅余跨机启动或下轮验证项，路由 **Mode B** |

## 2. 6 项结构硬约束

1. **Sticky 吸顶控制栏**：固定在视口顶部，包含项目名、模式徽章、锚定 `main HEAD`（带直达 GitHub Commit 链接）、实时计数徽章、3 态主题切换（`浅色 / 深色 / 系统`）与全局一键复制主按钮。
2. **显式 3-Step 顺序条**：紧贴顶栏与标题下方，以 `Step 1 → Step 2 → Step 3` 3 列卡片明确执行主体、当前状态与强依赖顺序，消除“先发回执还是先启动下一台机器”的歧义。
3. **4 卡 KPI 概览**：首屏给出 4 张可核验硬数字卡片（如待批/合入数、冲突或阻塞守护数、签字数、锚定 `main HEAD` 短 SHA）。
4. **3 Tab 视图隔离**（支持键盘方向键切换，`@media print` 自动全量展开）：
   - **Tab 1**：PR 明细（Mode A 含勾选、批量按钮、SVG 堆叠拓扑；Mode B 含冲突说明条、状态筛选 Pills、搜索框）。
   - **Tab 2**：判据 / 签字矩阵（每张卡片必须写清 **对应对象与现状 / 具体口径与作用 / 解锁效果与残余卡点** 3 要素；存在前置门禁授权时，Mode A 提供独立开关，Mode B 提供落盘审计条）。
   - **Tab 3**：下一环启动 Prompt（支持执行模式切换与任务模块勾选，实时重算文本与字符数，强制锁定并展示 **零图片/零文件回传约束**）。
5. **跨 Tab 实时回执联动（Mode A 强制）**：Tab 1 与 Tab 2 底部均需提供实时同步的回执预览框、备注输入与一键复制按钮；`clipboard.writeText` 失败时降级选中只读文本区并准确提示，不得误报成功。
6. **单文件零外网 CDN + 版本水印**：内联原生 CSS 变量（含 `prefers-color-scheme: dark` 与 `@media print`），`<footer>` 必须包含 `report-for-human@v2.0.0`。

## 3. 跨机治理与脱敏实践约定

- **执行者与 preflight 归属**：配套 `execute-github-issue-pr-workflow` 使用时，汇报正文与 Prompt 中保留 `执行者` 标识、`goal-prompt preflight` 状态行及确切 `main HEAD` SHA + 可点击链接，防止多机多 Agent 协作时口径错位。
- **零外传 / 零凭据泄漏红线**：严禁向 GitHub Issue/PR 评论、HTML 报告或跨机 Prompt 写入原始截图、完整 UI 树/日志原文、真实设备序列号、内网 `IP:PORT` 凭据、手机号明文或密码/PIN；只回传脱敏 `run_id`、测试统计与可点击 GitHub 永久链接。
- **防同回合自批自合**：新建 PR 的首次提交可随附 Mode A 初版报告与最新 SHA；合入完成后切换生成 Mode B 交接报告，严禁绕过人工审核在同一回合自建自合。

## 4. 数据契约与确定性命令

### 顶层 JSON 字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `mode` | `"approval" \| "handoff"` | 是 | 强制双态路由，禁止混用 |
| `meta` | object | 是 | `project_name`、`report_title`、`report_subtitle`、`generated_at`、`main_head_sha`、`main_head_short`、`main_head_url` |
| `steps` | array(长度=3) | 是 | 每项含 `actor`、`status`（`done\|active\|pending`）、`status_label`、`title`、`description`、`dependency` |
| `kpis` | array(长度=4) | 是 | 每项含 `label`、`value`、`subtext`、可选 `tone` / `mono` / `url` |
| `prs` | array | 是 | Mode A 含 `default_checked`、`depends_on`、`status`(`ready\|approved\|warning\|blocked`)；Mode B 含 `status`(`merged\|conflict_resolved\|blocked\|deferred`)、`merge_commit_sha`、`merge_commit_url`、`conflict_note` |
| `conflicts` | object | Mode B 必填 | `has_conflicts` 与 `summary`（无冲突亦需显式声明） |
| `gates` | array | 可选 | 前置门禁开关/审计项（`id`、`title`、`description`、`url`、`authorized`） |
| `criteria` | array | 是 | 每条强制包含 `target_and_status`、`ruling`、`unlock_and_blockers` 三要素 |
| `prompt` | object | 是 | `target_machine`、`default_mode`、`preamble`、`zero_artifact_constraint`、`modes`、`modules` |

### 渲染与独立复检

```bash
python <skill-root>/scripts/render_dual_mode_report.py \
  --mode <approval|handoff> \
  --input <verified-data.json> \
  --output <output-report.html>

python <skill-root>/scripts/validate_dual_mode_report.py <output-report.html> --mode <approval|handoff>
```

输出路径应置于项目交付目录（如 `reports/`）或用户指定路径，禁止写入技能安装目录；提交给决策者前必须确认退出码为 `0` 且无遗留 `{{PLACEHOLDER}}`。
