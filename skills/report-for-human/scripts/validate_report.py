#!/usr/bin/env python3
"""
report-for-human@v2.1.0 pre-delivery HTML validator.

Verifies all structural hard constraints and anti-degradation rules for Mode A
(approval), Mode B (handoff), and Mode C (briefing) single-file HTML reports.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit


WATERMARK = "report-for-human@v2.1.0"

_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img",
    "input", "link", "meta", "source", "track", "wbr",
})

_RESOURCE_ATTRS_BY_TAG: Dict[str, Tuple[str, ...]] = {
    "link": ("href",),
    "script": ("src",),
    "img": ("src", "srcset"),
    "iframe": ("src",),
    "source": ("src", "srcset"),
    "audio": ("src",),
    "video": ("src", "poster"),
    "embed": ("src",),
    "object": ("data",),
    "image": ("href", "xlink:href"),
    "feimage": ("href", "xlink:href"),
    "use": ("href", "xlink:href"),
}

_CSS_EXTERNAL_URL_RE = re.compile(
    r"(?:@import\s+(?:url\(\s*)?|url\(\s*)['\"]?\s*(?:https?:)?//",
    re.IGNORECASE,
)

PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")


def _normalize_url_candidate(raw_val: str) -> str:
    # WHATWG URL standard: remove ASCII tab/LF/CR anywhere and strip leading/trailing C0 + space
    no_tabs_newlines = re.sub(r"[\t\r\n]+", "", raw_val or "")
    return no_tabs_newlines.strip("".join(chr(i) for i in range(0x21)))


def _is_data_media_uri(cleaned_lower: str, *prefixes: str) -> bool:
    if "," not in cleaned_lower:
        return False
    return any(cleaned_lower.startswith(prefix) for prefix in prefixes)


def _is_allowed_resource_url(tag: str, attr_name: str, raw_val: str) -> bool:
    cleaned = _normalize_url_candidate(raw_val)
    if not cleaned:
        return True
    lower = cleaned.lower()

    if tag in ("image", "feimage", "use") and attr_name in ("href", "xlink:href"):
        if cleaned.startswith("#") and len(cleaned) > 1:
            return True
        if tag in ("image", "feimage"):
            return _is_data_media_uri(lower, "data:image/")
        return False

    if tag == "img":
        return _is_data_media_uri(lower, "data:image/")
    if tag == "video" and attr_name == "poster":
        return _is_data_media_uri(lower, "data:image/")
    if tag == "video" and attr_name == "src":
        return _is_data_media_uri(lower, "data:video/")
    if tag == "audio" and attr_name == "src":
        return _is_data_media_uri(lower, "data:audio/")
    if tag == "source":
        return _is_data_media_uri(lower, "data:image/", "data:audio/", "data:video/")
    if tag == "link":
        return _is_data_media_uri(lower, "data:image/")

    # script, iframe, embed, object must never point to external/separate files
    return False


def _split_srcset_urls(raw_val: str) -> List[str]:
    candidates: List[str] = []
    s = raw_val or ""
    pos = 0
    while pos < len(s):
        while pos < len(s) and s[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(s):
            break
        if s[pos:].lower().startswith("data:"):
            comma = s.find(",", pos)
            if comma == -1:
                candidates.append(s[pos:])
                break
            end = comma + 1
            while end < len(s) and s[end] not in " \t\r\n,":
                end += 1
            candidates.append(s[pos:end])
            pos = end
        else:
            comma = s.find(",", pos)
            seg = s[pos:] if comma == -1 else s[pos:comma]
            tok = seg.strip().split(None, 1)[0] if seg.strip() else ""
            if tok:
                candidates.append(tok)
            if comma == -1:
                break
            pos = comma + 1
            continue
        if pos < len(s) and s[pos] in " \t\r\n":
            next_comma = s.find(",", pos)
            if next_comma == -1:
                break
            pos = next_comma + 1
    return candidates


def _extract_disallowed_attr_urls(tag: str, attr_name: str, raw_val: str) -> List[str]:
    if attr_name == "srcset":
        return [tok for tok in _split_srcset_urls(raw_val) if not _is_allowed_resource_url(tag, attr_name, tok)]
    cleaned = _normalize_url_candidate(raw_val)
    return [cleaned] if not _is_allowed_resource_url(tag, attr_name, raw_val) else []


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
        self._tab_panel_depth = 0
        self._current_tab_index: Optional[str] = None

        self.has_svg_topology = False
        self.has_topo_svg_in_tab1 = False
        self._in_svg_topo_depth = 0

        self.has_svg_architecture = False
        self.has_arch_svg_in_tab1 = False
        self._in_svg_arch_depth = 0

        self.has_pr_batch_bar = False
        self.synced_receipt_slots: set[str] = set()
        self.has_conflict_banner = False

        self.has_filter_bar = False
        self._in_pr_filter_depth = 0
        self.has_handoff_search_in_tab1 = False

        self.has_briefing_filter_bar = False
        self._in_briefing_filter_depth = 0
        self.has_briefing_search_in_tab2 = False

        self.has_search_input = False
        self.has_zero_artifact_constraint = False
        self._in_zero_constraint_depth = 0
        self.zero_constraint_text_parts: List[str] = []

        self.in_footer = False
        self.footer_text_parts: List[str] = []
        self.in_style = False
        self.style_parts: List[str] = []
        self.in_report_data = False
        self.report_data_parts: List[str] = []
        self.external_resources: List[str] = []
        self.external_links_missing_attrs: List[str] = []
        self.external_link_count = 0

        self.criteria_card_count = 0
        self._in_criteria_card_depth = 0
        self._current_criteria_text: List[str] = []
        self.criteria_texts: List[str] = []

        self.gap_card_count = 0
        self._in_gap_card_depth = 0
        self._in_gap_box_depth = 0
        self._in_gap_box_label_depth = 0
        self._in_gap_box_body_depth = 0
        self._current_gap_box_label: List[str] = []
        self._current_gap_box_body: List[str] = []
        self._current_gap_boxes: List[Tuple[str, str]] = []
        self.gap_card_boxes: List[List[Tuple[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr_map: Dict[str, str] = {k.lower(): (v or "") for k, v in attrs}
        cls_tokens = set(attr_map.get("class", "").split())
        rfh_role = attr_map.get("data-rfh-role", "")
        non_void = tag not in _VOID_ELEMENTS

        for attr_name in _RESOURCE_ATTRS_BY_TAG.get(tag, ()):
            for bad_url in _extract_disallowed_attr_urls(tag, attr_name, attr_map.get(attr_name, "")):
                self.external_resources.append(f"<{tag} {attr_name}> 禁止引入外网或非自包含外部资源: {bad_url}")

        inline_style = attr_map.get("style", "")
        if inline_style and _CSS_EXTERNAL_URL_RE.search(inline_style):
            self.external_resources.append("内联 style 属性禁止引用外网资源")

        if tag == "style":
            self.in_style = True
        if tag == "script" and attr_map.get("id") == "report-data":
            self.in_report_data = True

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
            if non_void and self._tab_panel_depth == 0:
                self._tab_panel_depth = 1
                self._current_tab_index = idx
        elif self._tab_panel_depth > 0 and non_void:
            self._tab_panel_depth += 1

        if rfh_role == "svg-topology":
            self.has_svg_topology = True
            if non_void and self._in_svg_topo_depth == 0:
                self._in_svg_topo_depth = 1
        elif self._in_svg_topo_depth > 0 and non_void:
            self._in_svg_topo_depth += 1

        if rfh_role == "svg-architecture":
            self.has_svg_architecture = True
            if non_void and self._in_svg_arch_depth == 0:
                self._in_svg_arch_depth = 1
        elif self._in_svg_arch_depth > 0 and non_void:
            self._in_svg_arch_depth += 1

        if rfh_role == "pr-batch-bar":
            self.has_pr_batch_bar = True
        elif rfh_role == "synced-receipt":
            slot = attr_map.get("data-receipt-slot", "")
            if slot:
                self.synced_receipt_slots.add(slot)
        elif rfh_role == "conflict-banner":
            self.has_conflict_banner = True

        if rfh_role == "pr-filter-bar":
            self.has_filter_bar = True
            if non_void and self._in_pr_filter_depth == 0:
                self._in_pr_filter_depth = 1
        elif self._in_pr_filter_depth > 0 and non_void:
            self._in_pr_filter_depth += 1

        if rfh_role == "briefing-filter-bar":
            self.has_briefing_filter_bar = True
            if non_void and self._in_briefing_filter_depth == 0:
                self._in_briefing_filter_depth = 1
        elif self._in_briefing_filter_depth > 0 and non_void:
            self._in_briefing_filter_depth += 1

        if rfh_role == "zero-artifact-constraint":
            self.has_zero_artifact_constraint = True
            if non_void and self._in_zero_constraint_depth == 0:
                self._in_zero_constraint_depth = 1
        elif self._in_zero_constraint_depth > 0 and non_void:
            self._in_zero_constraint_depth += 1

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
            if self._in_svg_topo_depth > 0 and self._current_tab_index == "1":
                self.has_topo_svg_in_tab1 = True
            if self._in_svg_arch_depth > 0 and self._current_tab_index == "1":
                self.has_arch_svg_in_tab1 = True

        if tag == "input" and (attr_map.get("type") == "search" or attr_map.get("id") in ("pr-search-input", "briefing-search-input")):
            self.has_search_input = True
            if attr_map.get("id") == "pr-search-input" and self._in_pr_filter_depth > 0 and self._current_tab_index == "1":
                self.has_handoff_search_in_tab1 = True
            if attr_map.get("id") == "briefing-search-input" and self._in_briefing_filter_depth > 0 and self._current_tab_index == "2":
                self.has_briefing_search_in_tab2 = True

        if tag == "footer":
            self.in_footer = True

        if tag == "a":
            href = _normalize_url_candidate(attr_map.get("href", ""))
            parsed_href = urlsplit(href)
            if parsed_href.scheme.lower() in ("http", "https") and parsed_href.hostname:
                self.external_link_count += 1
                target = attr_map.get("target", "").strip()
                rel_tokens = set(attr_map.get("rel", "").lower().split())
                if target != "_blank" or "noopener" not in rel_tokens or "noreferrer" not in rel_tokens:
                    self.external_links_missing_attrs.append(href)

        if "criteria-card" in cls_tokens and non_void:
            self.criteria_card_count += 1
            self._in_criteria_card_depth = 1
            self._current_criteria_text = []
        elif self._in_criteria_card_depth > 0 and non_void:
            self._in_criteria_card_depth += 1

        if "gap-card" in cls_tokens and non_void and self._in_gap_card_depth == 0:
            self.gap_card_count += 1
            self._in_gap_card_depth = 1
            self._current_gap_boxes = []
        elif self._in_gap_card_depth > 0 and non_void:
            self._in_gap_card_depth += 1
            if "gap-box" in cls_tokens and self._in_gap_box_depth == 0:
                self._in_gap_box_depth = 1
                self._current_gap_box_label = []
                self._current_gap_box_body = []
            elif self._in_gap_box_depth > 0:
                self._in_gap_box_depth += 1
                if "gap-box-label" in cls_tokens and self._in_gap_box_label_depth == 0:
                    self._in_gap_box_label_depth = 1
                elif self._in_gap_box_label_depth > 0:
                    self._in_gap_box_label_depth += 1
                if "gap-box-body" in cls_tokens and self._in_gap_box_body_depth == 0:
                    self._in_gap_box_body_depth = 1
                elif self._in_gap_box_body_depth > 0:
                    self._in_gap_box_body_depth += 1

    def handle_endtag(self, tag: str) -> None:
        non_void = tag not in _VOID_ELEMENTS
        if tag == "style":
            self.in_style = False
        if tag == "script":
            self.in_report_data = False
        if tag == "footer":
            self.in_footer = False

        if non_void:
            if self._tab_panel_depth > 0:
                self._tab_panel_depth -= 1
                if self._tab_panel_depth == 0:
                    self._current_tab_index = None
            if self._in_svg_topo_depth > 0:
                self._in_svg_topo_depth -= 1
            if self._in_svg_arch_depth > 0:
                self._in_svg_arch_depth -= 1
            if self._in_pr_filter_depth > 0:
                self._in_pr_filter_depth -= 1
            if self._in_briefing_filter_depth > 0:
                self._in_briefing_filter_depth -= 1
            if self._in_zero_constraint_depth > 0:
                self._in_zero_constraint_depth -= 1

            if self._in_criteria_card_depth > 0:
                self._in_criteria_card_depth -= 1
                if self._in_criteria_card_depth == 0:
                    self.criteria_texts.append(" ".join(self._current_criteria_text))
                    self._current_criteria_text = []

            if self._in_gap_card_depth > 0:
                if self._in_gap_box_depth > 0:
                    if self._in_gap_box_label_depth > 0:
                        self._in_gap_box_label_depth -= 1
                    if self._in_gap_box_body_depth > 0:
                        self._in_gap_box_body_depth -= 1
                    self._in_gap_box_depth -= 1
                    if self._in_gap_box_depth == 0:
                        lbl = " ".join(self._current_gap_box_label).strip()
                        body = " ".join(self._current_gap_box_body).strip()
                        self._current_gap_boxes.append((lbl, body))
                self._in_gap_card_depth -= 1
                if self._in_gap_card_depth == 0:
                    self.gap_card_boxes.append(self._current_gap_boxes)
                    self._current_gap_boxes = []

    def handle_data(self, data: str) -> None:
        if self.in_style:
            self.style_parts.append(data)
        if self.in_report_data:
            self.report_data_parts.append(data)
        if self.in_footer:
            self.footer_text_parts.append(data)
        if self._in_zero_constraint_depth > 0:
            text = data.strip()
            if text:
                self.zero_constraint_text_parts.append(text)
        if self._in_criteria_card_depth > 0:
            text = data.strip()
            if text:
                self._current_criteria_text.append(text)
        if self._in_gap_box_label_depth > 0:
            text = data.strip()
            if text:
                self._current_gap_box_label.append(text)
        if self._in_gap_box_body_depth > 0:
            text = data.strip()
            if text:
                self._current_gap_box_body.append(text)


def _collect_user_data_placeholders(raw_json: str) -> set[str]:
    if not raw_json.strip():
        return set()
    try:
        parsed = json.loads(raw_json)
    except ValueError:
        return set()
    tokens: set[str] = set()
    stack: List[Any] = [parsed]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            tokens.update(PLACEHOLDER_RE.findall(cur))
        elif isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return tokens


def validate_html(html_text: str, expected_mode: Optional[str] = None) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    # Parse DOM structure first (zero external CDN/network/file resource check included)
    inspector = StructureInspector()
    inspector.feed(html_text)
    inspector.close()

    # 1. Leftover placeholders check (allow literal user data tokens present in parsed #report-data)
    user_data_tokens = _collect_user_data_placeholders("".join(inspector.report_data_parts))
    leftovers = sorted(tok for tok in set(PLACEHOLDER_RE.findall(html_text)) if tok not in user_data_tokens)
    if leftovers:
        errors.append(f"遗留未替换占位符: {', '.join(leftovers)}")

    errors.extend(inspector.external_resources)
    style_text = "\n".join(inspector.style_parts)
    if _CSS_EXTERNAL_URL_RE.search(style_text):
        errors.append("禁止在 CSS 中引用外网 @import 或 url() 资源")

    mode = inspector.report_mode
    if mode not in ("approval", "handoff", "briefing"):
        errors.append(f"<html> 缺少合法的 data-report-mode 属性（需为 approval / handoff / briefing，当前: {mode!r}）")
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
        if not inspector.has_topo_svg_in_tab1:
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
        if not inspector.has_handoff_search_in_tab1:
            errors.append("Mode B（交接态）Tab 1 筛选栏缺少关键字搜索框 (#pr-search-input)")
    elif mode == "briefing":
        if not inspector.has_arch_svg_in_tab1:
            errors.append("Mode C（架构与深度汇报）Tab 1 缺少 SVG 分层架构图")
        if not inspector.has_briefing_filter_bar:
            errors.append("Mode C（架构与深度汇报）Tab 2 缺少类别筛选 Pills 栏")
        if not inspector.has_briefing_search_in_tab2:
            errors.append("Mode C（架构与深度汇报）Tab 2 筛选栏缺少关键字搜索框 (#briefing-search-input)")

    if mode in ("approval", "handoff"):
        # Tab 2 criteria 3 mandatory fields
        required_criteria_labels = ("对应对象与现状", "具体口径与作用", "解锁效果与残余卡点")
        if inspector.criteria_card_count == 0:
            warnings.append("Tab 2 未检测到判据卡片（若本轮确无判据项可忽略，否则需补充）")
        else:
            for idx, ctext in enumerate(inspector.criteria_texts, start=1):
                missing_lbls = [lbl for lbl in required_criteria_labels if lbl not in ctext]
                if missing_lbls:
                    errors.append(f"Tab 2 第 {idx} 条判据卡片缺少必填维度: {', '.join(missing_lbls)}")
    elif mode == "briefing":
        required_gap_labels = ("现状", "目标设计", "核心卡点 / 债务")
        if inspector.gap_card_count == 0:
            errors.append("Mode C（架构与深度汇报）Tab 1 至少需要 1 条架构差距卡片")
        else:
            for idx, boxes in enumerate(inspector.gap_card_boxes, start=1):
                box_map = {lbl: body for lbl, body in boxes}
                missing_or_empty = [lbl for lbl in required_gap_labels if not box_map.get(lbl, "").strip()]
                if missing_or_empty:
                    errors.append(f"Tab 1 第 {idx} 条架构差距卡片缺少必填维度（或维度块为空）: {', '.join(missing_or_empty)}")

    # Tab 3 zero-image / zero-file return constraint checked inside the marker element & char counter
    constraint_text = " ".join(inspector.zero_constraint_text_parts)
    has_zero_prohibition = (
        inspector.has_zero_artifact_constraint
        and ("零图片" in constraint_text or "零文件" in constraint_text)
        and any(tok in constraint_text for tok in ("严禁", "禁止", "不得"))
    )
    if not has_zero_prohibition:
        errors.append("Tab 3 的 zero-artifact-constraint 元素缺少明确的零图片/零文件回传禁止约束标注")
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
    parser = argparse.ArgumentParser(description="Validate a report-for-human@v2.1.0 HTML report.")
    parser.add_argument("html_file", help="Path to generated HTML file")
    parser.add_argument("--mode", choices=["approval", "handoff", "briefing"], default=None, help="Expected report mode")
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

    print(f"[PASS]  {WATERMARK} validation passed ({len(warnings)} warning(s)): {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
