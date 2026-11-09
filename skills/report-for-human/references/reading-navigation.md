# 决策、参考导航与附图

先决定读者需要看什么，再选容器。首屏回答“需要我决定什么、推荐什么、依据与限制是什么、下一步谁做什么”。纯讲解写“本次无需你作决定”，不虚构授权、审批或待办；决策与核心依据始终常显。小报告使用常显段落即可。

## 按当前决定分层

- **立即可见**：当前决定或建议、必要事实、影响该决定的风险与下一步。实质功能停用/收窄、新增交互与回退变化也是必要事实，即使无需决策也要在正文中保留。验证结论只有会改变当前选择时才提炼成一句，不连同整组记录搬到首屏。
- **按需展开**：完整来源、验证过程、版本或字段说明、观测和跟踪记录，默认放闭合 `<details>`。它们应可追溯，但不必逐项阅读；是否重要由本次问题决定，不由标题或术语决定。
- **切换对照**：确实需要比较的同级方案或业务参考才用 2–4 个 tabs。若读者只是偶尔查阅记录，应折叠而不是做 tab；单个对照不需要导航。

蓝色生成器要求显式 `decision`：`status` 为 `required` 或 `none`，两者均填 `recommendation` 和 `next_step`；`required` 另填 `question`。这是作者核验后的输入，不由渲染器推断是否需要批准。

`evidence` 与已有 `supplementary_evidence` 合并到补充证据折叠区，保留全部来源。可选 `decision_facts` 为少量 `{"text": "一句改变当前决定的事实", "url": "https://…"}`，`url` 可省略；放在首屏，不重复已有结论。`limitations` 只写会改变本次决定或建议的风险摘要，不把所有未验证项逐条升级为常显限制。例如失败导致暂缓时，首屏说“先修复问题，暂不合入”，失败数量、环境和记录放 `evidence`。输入结构无需迁移，但旧报告作者应检查是否有决定性事实需提炼。渲染器不会按关键词猜测重要性。

可选 `reference_tabs` 每项含 `label`、`summary`、`evidence`，只装同级对照，不能把 CI、日志等整个审计目录原样搬入。图片可在自定义报告用下面的组件，生成器不读取本机图片或联网取图。

## 逐项行为对照

有多项实质行为变化时填写 `behavior_changes` 数组，每项含非空 `title`、`before`、`after`、`impact`（收益与功能/操作代价）、`fallback`（取消、失败或恢复条件）、`basis`（来源及验证边界），可带 HTTP(S) `url`。标题按具体能力/场景命名，版本和 PR 归属放入 `basis` 或链接；未知写明未知，不臆造回退操作。回退会重开风险时一并说明，报告不是执行授权。

这些条目始终常显：`change` 用它们替代总括的 `before/after/impact` 主视觉，其他类型在主视觉之后显示。原单项输入仍可用，不要求把无关字段迁移成大清单；相同内容只展示一次。小改动也可在原前后对照与 `impact` 中写全必要影响。生成器仅检查结构，不能保证作者已经找全差异或正确判断事实。`examples/change.json` 示范纯收益，`examples/behavior-changes.json` 示范收益与代价并存；两者均为虚构，不能代替真实版本取证。

## 共用组件

自定义报告写好语义 HTML 后运行 `scripts/add_report_controls.py`；它自动内联 `report-navigation.css/js`，与主题、复制路径、表格控件共存。完整可复制的合成示例为 `examples/navigation.html`，其中图片是生成的示意图，不是现场证据。

```html
<section class="rfh-tabs">
  <div role="tablist" aria-label="交付方式对照">
    <button type="button" role="tab" id="tab-proof" aria-controls="panel-proof">当日自取</button>
    <button type="button" role="tab" id="tab-source" aria-controls="panel-source">次日配送</button>
  </div>
  <section role="tabpanel" id="panel-proof" aria-labelledby="tab-proof"><h3>当日自取</h3>…</section>
  <section role="tabpanel" id="panel-source" aria-labelledby="tab-source"><h3>次日配送</h3>…</section>
</section>
<figure class="rfh-figure">
  <a class="rfh-image-link" href="data:image/png;base64,…" aria-label="放大：验收截图">
    <img src="data:image/png;base64,…" alt="具体描述截图所证明的状态">
  </a>
  <figcaption>来源、时间、环境和这张图不能证明的范围；可放大查看。</figcaption>
</figure>
```

所有 ID 在整页唯一，tablist、tabpanels 是外壳直接子元素。初始不加 hidden：无脚本时所有参考常显，只隐藏无效 tablist；启用后自动加 ARIA 状态与 roving tabindex，左右键、Home/End 切换并移动焦点，Tab 到面板内容。打印强制显示所有面板，保留每个面板标题。

图片默认完整比例、最高 240px、最大宽度 100%，不裁切、不改原图字节；需要并排时窄屏改为单列。链接 href 保留同一完整内嵌原图供无脚本/不支持 dialog 时打开。组件只增强 PNG/JPEG/WebP/GIF/AVIF 的 base64 data URI，不请求网络。浏览器可能限制直接打开 data URI；此时仍能阅读内嵌预览，必要时另附原图，不宣称链接一定可用。

支持原生 dialog 的浏览器可点击或 Enter 打开，按钮切换“原始尺寸 / 适合窗口”；原尺寸可滚动。关闭按钮、Escape 或背景关闭后焦点返回原链接；焦点陷阱由原生模态 dialog 提供。caption 取同一 figure 的 figcaption，否则取 img alt；始终用 textContent，不插入原图来源里的 HTML。无脚本不显示失效放大按钮。

## 验收

实际检查约 1440px / 390px、三态主题、键盘、无脚本及打印。核对完整图片字节不变，缩略图不压过决策区；反复开关、切换 tabs、原尺寸滚动与焦点返回无误。静态/模拟 DOM 可验证契约与逻辑，但不能代替真实浏览器、屏幕阅读器或指定用户设备验收。无法实际运行时明确说明；不绕过访问或启动限制。
