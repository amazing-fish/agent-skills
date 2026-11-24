#!/usr/bin/env python3
"""
report-for-human@v2.0.0 pre-delivery HTML validator.

Verifies all 6 structural hard constraints and anti-degradation rules
for both Mode A (approval) and Mode B (handoff) single-file HTML reports.
"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple


WATERMARK = "report-for-human@v2.0.0"

EXTERNAL_RESOURCE_PATTERNS = [
    (re.compile(r"<link[^>]+href\s*=\s*['\"]https?://", re.IGNORECASE), "禁止引入外网 <link> 样式/字体 CDN"),
    (re.compile(r"<script[^>]+src\s*=\s*['\"]https?://", re.IGNORECASE), "禁止引入外网 <script> CDN"),
    (re.compile(r"@import\s+url\(\s*['\"]?https?://", re.IGNORECASE), "禁止在 CSS 中 @import 外网资源"),
    (re.compile(r"cdn\.tailwindcss\.com|fonts\.googleapis\.com|fonts\.gstatic\.com|unpkg\.com|jsdelivr\.net|cdnjs\.cloudflare\.com", re.IGNORECASE), "检测到外网 CDN 域名残留"),
]

PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")


class StructureInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.report_mode: Optional[str] = None
        self.has_sticky_bar = False
        self.theme_values: set[str] = set()
        self.has_global_copy_btn = False
        self.has_step_bar = False
        self.step_card_count = 0
        self.has_kpi_grid = False
        self.kpi_card_count = 0
        self.tab_panel_indices: set[str] = set()
        self.has_svg_topology = False
        self.has_svg_tag = False
        self.has_pr_batch_bar = False
        self.synced_receipt_slots: set[str] = set()
        self.has_conflict_banner = False
        self.has_filter_bar = False
        self.has_search_input = False
        self.has_zero_artifact_constraint = False
        self.in_footer = False
        self.footer_text_parts: List[str] = []
        self.external_links_missing_attrs: List[str] = []
        self.external_link_count = 0
        self.criteria_card_count = 0
        self._in_criteria_card_depth = 0
        self._current_criteria_text: List[str] = []
        self.criteria_texts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr_map: Dict[str, str] = {k.lower(): (v or "") for k, v in attrs}
        cls_tokens = set(attr_map.get("class", "").split())
        rfh_role = attr_map.get("data-rfh-role", "")

        if tag == "html":
            self.report_mode = attr_map.get("data-report-mode") or None

        if rfh_role == "sticky-bar":
            self.has_sticky_bar = True
        elif rfh_role == "step-bar":
            self.has_step_bar = True
        elif rfh_role == "kpi-grid":
            self.has_kpi_grid = True
        elif rfh_role == "tab-panel":
            idx = attr_map.get("data-tab-index", "")
            if idx:
                self.tab_panel_indices.add(idx)
        elif rfh_role == "svg-topology":
            self.has_svg_topology = True
        elif rfh_role == "pr-batch-bar":
            self.has_pr_batch_bar = True
        elif rfh_role == "synced-receipt":
            slot = attr_map.get("data-receipt-slot", "")
            if slot:
                self.synced_receipt_slots.add(slot)
        elif rfh_role == "conflict-banner":
            self.has_conflict_banner = True
        elif rfh_role == "pr-filter-bar":
            self.has_filter_bar = True
        elif rfh_role == "zero-artifact-constraint":
            self.has_zero_artifact_constraint = True

        if "step-card" in cls_tokens:
            self.step_card_count += 1
        if "kpi-card" in cls_tokens:
            self.kpi_card_count += 1
        if "conflict-banner" in cls_tokens:
            self.has_conflict_banner = True
        if attr_map.get("data-theme-value"):
            self.theme_values.add(attr_map["data-theme-value"])
        if attr_map.get("id") == "global-copy-btn":
            self.has_global_copy_btn = True
        if tag == "svg":
            self.has_svg_tag = True
        if tag == "input" and (attr_map.get("type") == "search" or attr_map.get("id") == "pr-search-input"):
            self.has_search_input = True

        if tag == "footer":
            self.in_footer = True

        if tag == "a":
            href = attr_map.get("href", "").strip()
            if href.startswith("http://") or href.startswith("https://"):
                self.external_link_count += 1
                target = attr_map.get("target", "").strip()
                rel_tokens = set(attr_map.get("rel", "").lower().split())
                if target != "_blank" or "noopener" not in rel_tokens or "noreferrer" not in rel_tokens:
                    self.external_links_missing_attrs.append(href)

        if "criteria-card" in cls_tokens:
            self.criteria_card_count += 1
            self._in_criteria_card_depth = 1
            self._current_criteria_text = []
        elif self._in_criteria_card_depth > 0:
            self._in_criteria_card_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "footer":
            self.in_footer = False
        if self._in_criteria_card_depth > 0:
            self._in_criteria_card_depth -= 1
            if self._in_criteria_card_depth == 0:
                self.criteria_texts.append(" ".join(self._current_criteria_text))
                self._current_criteria_text = []

    def handle_data(self, data: str) -> None:
        if self.in_footer:
            self.footer_text_parts.append(data)
        if self._in_criteria_card_depth > 0:
            text = data.strip()
            if text:
                self._current_criteria_text.append(text)


def validate_html(html_text: str, expected_mode: Optional[str] = None) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Leftover placeholders check
    leftovers = sorted(set(PLACEHOLDER_RE.findall(html_text)))
    if leftovers:
        errors.append(f"遗留未替换占位符: {', '.join(leftovers)}")

    # 2. Zero external CDN/network resource check
    for pattern, msg in EXTERNAL_RESOURCE_PATTERNS:
        if pattern.search(html_text):
            errors.append(msg)

    # 3. Parse DOM structure
    inspector = StructureInspector()
    inspector.feed(html_text)

    mode = inspector.report_mode
    if mode not in ("approval", "handoff"):
        errors.append(f"<html> 缺少合法的 data-report-mode 属性（需为 approval 或 handoff，当前: {mode!r}）")
    elif expected_mode and mode != expected_mode:
        errors.append(f"模式不匹配：期望 {expected_mode}，实际 {mode}")

    # Constraint 1: Sticky top bar + 3-state theme + global copy
    if not inspector.has_sticky_bar:
        errors.append("缺少 Sticky 吸顶控制栏 (data-rfh-role=\"sticky-bar\")")
    missing_themes = {"light", "dark", "system"} - inspector.theme_values
    if missing_themes:
        errors.append(f"主题切换不完整，缺少: {', '.join(sorted(missing_themes))}")
    if not inspector.has_global_copy_btn:
        errors.append("顶部 Sticky 栏缺少全局一键复制主按钮 (#global-copy-btn)")

    # Constraint 2: Explicit 3-Step sequence bar
    if not inspector.has_step_bar or inspector.step_card_count != 3:
        errors.append(f"缺少显式 3-Step 顺序条或卡片数量不为 3（当前: {inspector.step_card_count}）")

    # Constraint 3: 4-Card KPI overview
    if not inspector.has_kpi_grid or inspector.kpi_card_count != 4:
        errors.append(f"缺少 4 卡 KPI 概览或卡片数量不为 4（当前: {inspector.kpi_card_count}）")

    # Constraint 4: 3 isolated tabs
    if inspector.tab_panel_indices != {"1", "2", "3"}:
        errors.append(f"3 Tab 视图不完整，当前检测到 Tab 索引: {sorted(inspector.tab_panel_indices)}")

    # Mode-specific constraints
    if mode == "approval":
        if not (inspector.has_svg_topology and inspector.has_svg_tag):
            errors.append("Mode A（审批态）Tab 1 缺少 SVG 堆叠依赖拓扑")
        if not inspector.has_pr_batch_bar:
            errors.append("Mode A（审批态）Tab 1 缺少批量快捷按钮栏")
        if inspector.synced_receipt_slots != {"tab1", "tab2"}:
            errors.append(
                f"Mode A（审批态）强制要求 Tab 1 与 Tab 2 底部均提供实时同步回执预览框与复制按钮（当前: {sorted(inspector.synced_receipt_slots)}）"
            )
    elif mode == "handoff":
        if not inspector.has_conflict_banner:
            errors.append("Mode B（交接态）Tab 1 缺少冲突解决高亮条")
        if not inspector.has_filter_bar:
            errors.append("Mode B（交接态）Tab 1 缺少状态筛选 Pills 栏")
        if not inspector.has_search_input:
            errors.append("Mode B（交接态）Tab 1 缺少关键字搜索框")

    # Tab 2 criteria 3 mandatory fields
    required_criteria_labels = ("对应对象与现状", "具体口径与作用", "解锁效果与残余卡点")
    if inspector.criteria_card_count == 0:
        warnings.append("Tab 2 未检测到判据卡片（若本轮确无判据项可忽略，否则需补充）")
    else:
        for idx, ctext in enumerate(inspector.criteria_texts, start=1):
            missing_lbls = [lbl for lbl in required_criteria_labels if lbl not in ctext]
            if missing_lbls:
                errors.append(f"Tab 2 第 {idx} 条判据卡片缺少必填维度: {', '.join(missing_lbls)}")

    # Tab 3 zero-image / zero-file return constraint & char counter
    if not inspector.has_zero_artifact_constraint or ("零图片" not in html_text and "零文件" not in html_text):
        errors.append("Tab 3 缺少明确的零图片/零文件回传约束标注")
    if "prompt-char-count" not in html_text:
        errors.append("Tab 3 缺少实时字符数统计 (#prompt-char-count)")

    # Constraint 6: Clipboard dual-path + Toast + @media print + Footer Watermark
    if "navigator.clipboard.writeText" not in html_text or "document.createElement('textarea')" not in html_text:
        errors.append("复制逻辑未同时实现 navigator.clipboard.writeText 与 textarea 降级复制")
    if 'id="toast"' not in html_text:
        errors.append("缺少复制 Toast 提示容器 (#toast)")
    if "@media print" not in html_text:
        errors.append("内联 CSS 缺少 @media print 打印样式")
    if "@media (prefers-color-scheme: dark)" not in html_text:
        errors.append("内联 CSS 缺少系统深色模式媒体查询")

    footer_text = " ".join(inspector.footer_text_parts)
    if WATERMARK not in footer_text:
        errors.append(f"<footer> 缺少版本水印: {WATERMARK}")

    # Anti-degradation: External links must have target="_blank" rel="noopener noreferrer"
    if inspector.external_link_count == 0:
        warnings.append("未检测到真实外部 GitHub http(s) 链接，请核查是否遗漏 PR/Issue/Commit 直达链接")
    if inspector.external_links_missing_attrs:
        sample = ", ".join(inspector.external_links_missing_attrs[:3])
        errors.append(f"存在 {len(inspector.external_links_missing_attrs)} 个外链缺少 target=\"_blank\" rel=\"noopener noreferrer\"（如: {sample}）")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a report-for-human@v2.0.0 HTML report.")
    parser.add_argument("html_file", help="Path to generated HTML file")
    parser.add_argument("--mode", choices=["approval", "handoff"], default=None, help="Expected report mode")
    args = parser.parse_args()

    path = Path(args.html_file)
    if not path.is_file():
        print(f"[ERROR] File not found: {path}", file=sys.stderr)
        return 2

    html_text = path.read_text(encoding="utf-8")
    errors, warnings = validate_html(html_text, expected_mode=args.mode)

    for w in warnings:
        print(f"[WARN]  {w}")
    for e in errors:
        print(f"[FAIL]  {e}")

    if errors:
        print(f"\nValidation FAILED ({len(errors)} error(s), {len(warnings)} warning(s)): {path}")
        return 1

    print(f"[PASS]  report-for-human@v2.0.0 validation passed ({len(warnings)} warning(s)): {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
