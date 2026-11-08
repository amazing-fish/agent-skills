# 决策、参考导航与附图

先决定读者需要看什么，再选容器。首屏回答“需要我决定什么、推荐什么、依据与限制是什么、下一步谁做什么”。纯讲解写“本次无需你作决定”，不虚构授权、审批或待办；决策与核心依据始终常显。小报告使用常显段落即可。

## 三种阅读层级

- **必须立即知道**：决策问题、建议、关键依据、风险和下一步，放首屏或紧邻主图，不能在 tabs 或 details 里成为唯一信息。
- **需要参考**：验收证据、候选对照、实现范围和来源。少量常显；多组同层内容使用 2–4 个明确命名的 tabs，例如“实机证据 / 验收门槛 / 方案与来源”。不要把所有正文逐段装入 tabs。
- **可以跳过**：补充原始日志、重复记录、延伸材料，才使用 `<details>`，summary 说明可跳过。长 SHA 或技术术语并不自动意味着可跳过。

蓝色生成器要求显式 `decision`：`status` 为 `required` 或 `none`，两者均填 `recommendation` 和 `next_step`；`required` 另填 `question`。这是作者核验后的输入，不由渲染器推断是否需要批准。原有 JSON 需补此字段。

`evidence` 默认常显。可选 `reference_tabs` 是 2–4 项数组，每项含 `label`、`summary`、`evidence`；仍把共同结论与重大缺口放在首屏。只有 `supplementary_evidence` 折叠。图片可在自定义报告用下面的组件，生成器不读取本机图片或联网取图。

## 共用组件

自定义报告写好语义 HTML 后运行 `scripts/add_report_controls.py`；它自动内联 `report-navigation.css/js`，与主题、复制路径、表格控件共存。完整可复制的合成示例为 `examples/navigation.html`，其中图片是生成的示意图，不是现场证据。

```html
<section class="rfh-tabs">
  <div role="tablist" aria-label="必要参考">
    <button type="button" role="tab" id="tab-proof" aria-controls="panel-proof">验收证据</button>
    <button type="button" role="tab" id="tab-source" aria-controls="panel-source">方案与来源</button>
  </div>
  <section role="tabpanel" id="panel-proof" aria-labelledby="tab-proof"><h3>验收证据</h3>…</section>
  <section role="tabpanel" id="panel-source" aria-labelledby="tab-source"><h3>方案与来源</h3>…</section>
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
