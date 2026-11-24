#!/usr/bin/env python3
"""
report-for-human@v2.1.0 deterministic single-file HTML report renderer.

Renders Mode A (approval), Mode B (handoff), or Mode C (briefing) HTML from a
verified JSON payload using templates/{approval,handoff,briefing}_report.html,
then runs validate_report.py automatically before exiting.
"""

from __future__ import annotations

import argparse
import copy
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlsplit

try:
    from validate_report import CANONICAL_ZERO_ARTIFACT_CONSTRAINT, validate_html
except ImportError:
    _scripts_dir = str(Path(__file__).resolve().parent)
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)
    from validate_report import CANONICAL_ZERO_ARTIFACT_CONSTRAINT, validate_html


SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"

DEFAULT_ZERO_ARTIFACT_CONSTRAINT = CANONICAL_ZERO_ARTIFACT_CONSTRAINT


def normalize_zero_artifact_constraint(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text or text == DEFAULT_ZERO_ARTIFACT_CONSTRAINT:
        return DEFAULT_ZERO_ARTIFACT_CONSTRAINT
    if text.startswith(DEFAULT_ZERO_ARTIFACT_CONSTRAINT):
        return text
    return f"{DEFAULT_ZERO_ARTIFACT_CONSTRAINT} 补充约束：{text}"


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def safe_json_for_script(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, allow_nan=False)
    return (
        raw.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def validate_url(url: str, field_name: str) -> str:
    cleaned = (url or "").strip()
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"字段 `{field_name}` 必须是真实可直达的 http(s) URL（包含有效主机名），当前值: {url!r}")
    return cleaned


def ext_link(url: str, label: str, css_class: str = "") -> str:
    safe_url = validate_url(url, f"link({label})")
    cls_attr = f' class="{esc(css_class)}"' if css_class else ""
    return f'<a href="{esc(safe_url)}" target="_blank" rel="noopener noreferrer"{cls_attr}>{esc(label)}</a>'


def render_steps(steps: List[Dict[str, Any]]) -> str:
    if len(steps) != 3:
        raise ValueError(f"`steps` 必须恰好包含 3 项（Step 1 / Step 2 / Step 3），当前为 {len(steps)} 项")
    status_meta = {
        "done": ("step-done", "已完成"),
        "active": ("step-active", "当前步骤"),
        "pending": ("step-pending", "待前置完成"),
    }
    cards: List[str] = []
    for idx, step in enumerate(steps, start=1):
        st = step.get("status", "pending")
        cls, default_badge = status_meta.get(st, ("step-pending", st))
        badge_text = step.get("status_label") or default_badge
        actor = step.get("actor", "")
        actor_html = f" · {esc(actor)}" if actor else ""
        arrow_prefix = f"Step {idx}" + (" →" if idx < 3 else "")
        cards.append(
            f'<article class="step-card {cls}">'
            f'  <div class="step-top">'
            f'    <span class="step-num">{esc(arrow_prefix)}{actor_html}</span>'
            f'    <span class="step-badge">{esc(badge_text)}</span>'
            f'  </div>'
            f'  <h2 class="step-title">{esc(step.get("title", ""))}</h2>'
            f'  <p class="step-desc">{esc(step.get("description", ""))}</p>'
            f'  <div class="step-dep">依赖说明：{esc(step.get("dependency", "无前置阻塞"))}</div>'
            f'</article>'
        )
    return "\n".join(cards)


def render_kpis(kpis: List[Dict[str, Any]]) -> str:
    if len(kpis) != 4:
        raise ValueError(f"`kpis` 必须恰好包含 4 张 KPI 卡片，当前为 {len(kpis)} 张")
    cards: List[str] = []
    for kpi in kpis:
        tone = kpi.get("tone", "default")
        tone_cls = f" kpi-tone-{esc(tone)}" if tone in ("success", "warning", "danger", "accent") else ""
        mono_cls = " mono" if kpi.get("mono") else ""
        value_text = str(kpi.get("value", ""))
        if kpi.get("url"):
            value_html = ext_link(kpi["url"], value_text)
        else:
            value_html = esc(value_text)
        cards.append(
            f'<article class="kpi-card{tone_cls}">'
            f'  <span class="kpi-label">{esc(kpi.get("label", ""))}</span>'
            f'  <div class="kpi-value{mono_cls}">{value_html}</div>'
            f'  <span class="kpi-sub">{esc(kpi.get("subtext", ""))}</span>'
            f'</article>'
        )
    return "\n".join(cards)


def render_svg_topology(meta: Dict[str, Any], prs: List[Dict[str, Any]]) -> str:
    by_id: Dict[str, Dict[str, Any]] = {str(p["id"]): p for p in prs}
    depth_cache: Dict[str, int] = {}

    def get_depth(pid: str, stack: set[str]) -> int:
        if pid in depth_cache:
            return depth_cache[pid]
        if pid in stack:
            return 1
        pr = by_id.get(pid)
        if not pr:
            return 0
        deps = [str(d) for d in (pr.get("depends_on") or []) if str(d) in by_id]
        if not deps:
            depth_cache[pid] = 1
            return 1
        stack.add(pid)
        d = 1 + max(get_depth(dep, stack) for dep in deps)
        stack.remove(pid)
        depth_cache[pid] = d
        return d

    layers: Dict[int, List[Dict[str, Any]]] = {}
    for pr in prs:
        d = get_depth(str(pr["id"]), set())
        layers.setdefault(d, []).append(pr)

    max_depth = max(layers.keys(), default=1)
    max_rows = max((len(v) for v in layers.values()), default=1)

    node_w = 196
    node_h = 64
    col_gap = 66
    row_gap = 20
    pad_x = 24
    pad_y = 24

    total_cols = max_depth + 1
    svg_w = pad_x * 2 + total_cols * node_w + (total_cols - 1) * col_gap
    svg_h = max(140, pad_y * 2 + max_rows * node_h + max(0, max_rows - 1) * row_gap)

    positions: Dict[str, Tuple[float, float]] = {}
    root_x = pad_x
    root_y = (svg_h - node_h) / 2
    positions["__MAIN__"] = (root_x, root_y)

    for depth in range(1, max_depth + 1):
        col_items = layers.get(depth, [])
        col_h = len(col_items) * node_h + max(0, len(col_items) - 1) * row_gap
        start_y = (svg_h - col_h) / 2
        x = pad_x + depth * (node_w + col_gap)
        for r_idx, pr in enumerate(col_items):
            y = start_y + r_idx * (node_h + row_gap)
            positions[str(pr["id"])] = (x, y)

    edges_svg: List[str] = []
    for pr in prs:
        pid = str(pr["id"])
        deps = [str(d) for d in (pr.get("depends_on") or []) if str(d) in by_id]
        parents = deps if deps else ["__MAIN__"]
        tx, ty = positions[pid]
        for parent_id in parents:
            sx, sy = positions[parent_id]
            x1 = sx + node_w
            y1 = sy + node_h / 2
            x2 = tx
            y2 = ty + node_h / 2
            cx1 = x1 + col_gap * 0.45
            cx2 = x2 - col_gap * 0.45
            edges_svg.append(
                f'<path d="M {x1:.1f} {y1:.1f} C {cx1:.1f} {y1:.1f}, {cx2:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}" '
                f'fill="none" stroke="var(--border-strong)" stroke-width="2" marker-end="url(#dag-arrow)" />'
            )

    nodes_svg: List[str] = []
    # Main root node
    main_short = meta.get("main_head_short") or str(meta.get("main_head_sha", "HEAD"))[:8]
    nodes_svg.append(
        f'<g class="dag-root" transform="translate({root_x:.1f}, {root_y:.1f})">'
        f'  <rect width="{node_w}" height="{node_h}" rx="10" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="2" />'
        f'  <text x="12" y="25" font-size="11" font-weight="700" fill="var(--accent)">MAIN ANCHOR</text>'
        f'  <text x="12" y="46" font-size="14" font-weight="800" font-family="var(--font-mono)" fill="var(--text-primary)">{esc(main_short)}</text>'
        f'</g>'
    )

    status_fill = {
        "ready": "var(--bg-surface)",
        "approved": "var(--success-soft)",
        "warning": "var(--warning-soft)",
        "blocked": "var(--danger-soft)",
    }
    status_label_color = {
        "ready": "var(--success)",
        "approved": "var(--success)",
        "warning": "var(--warning)",
        "blocked": "var(--danger)",
    }

    for pr in prs:
        pid = str(pr["id"])
        x, y = positions[pid]
        st = pr.get("status", "ready")
        fill = status_fill.get(st, "var(--bg-surface)")
        st_color = status_label_color.get(st, "var(--text-muted)")
        checked_cls = "is-approved" if pr.get("default_checked") else "is-unapproved"
        short_title = str(pr.get("title", ""))
        if len(short_title) > 18:
            short_title = short_title[:17] + "…"
        st_badge = pr.get("status_label") or st
        nodes_svg.append(
            f'<g class="dag-node {checked_cls}" data-svg-pr-id="{esc(pid)}" '
            f'tabindex="0" role="button" aria-label="定位 PR #{esc(pr.get("number"))}: {esc(pr.get("title", ""))}" '
            f'transform="translate({x:.1f}, {y:.1f})">'
            f'  <title>点击定位 PR #{esc(pr.get("number"))}: {esc(pr.get("title", ""))}</title>'
            f'  <rect width="{node_w}" height="{node_h}" rx="10" fill="{fill}" stroke="var(--border-strong)" stroke-width="1.6" />'
            f'  <text x="12" y="24" font-size="12.5" font-weight="800" font-family="var(--font-mono)" fill="var(--accent)">#{esc(pr.get("number"))}</text>'
            f'  <text x="{node_w - 12}" y="24" text-anchor="end" font-size="11" font-weight="700" fill="{st_color}">{esc(st_badge)}</text>'
            f'  <text x="12" y="46" font-size="12" font-weight="600" fill="var(--text-primary)">{esc(short_title)}</text>'
            f'</g>'
        )

    return (
        f'<svg class="topology-svg" viewBox="0 0 {svg_w:.0f} {svg_h:.0f}" width="{svg_w:.0f}" height="{svg_h:.0f}" '
        f'role="img" aria-label="PR 堆叠依赖拓扑图">'
        f'  <defs>'
        f'    <marker id="dag-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'      <path d="M 0 1 L 10 5 L 0 9 z" fill="var(--border-strong)" />'
        f'    </marker>'
        f'  </defs>'
        f'  {"".join(edges_svg)}'
        f'  {"".join(nodes_svg)}'
        f'</svg>'
    )


def badge_class_for_status(status: str) -> str:
    return {
        "ready": "badge-success",
        "approved": "badge-success",
        "merged": "badge-success",
        "signed": "badge-success",
        "conflict_resolved": "badge-warning",
        "warning": "badge-warning",
        "guarded": "badge-warning",
        "blocked": "badge-danger",
        "deferred": "badge-danger",
    }.get(status, "badge-accent")


def render_approval_prs(prs: List[Dict[str, Any]]) -> str:
    by_id = {str(p["id"]): p for p in prs}
    cards: List[str] = []
    for pr in prs:
        pid = str(pr["id"])
        checked = bool(pr.get("default_checked", False))
        checked_attr = " checked" if checked else ""
        sel_cls = " is-selected" if checked else ""
        st = pr.get("status", "ready")
        st_lbl = pr.get("status_label") or st
        ci_lbl = pr.get("ci_status", "")
        deps = [str(d) for d in (pr.get("depends_on") or [])]
        dep_badges = "".join(
            f'<span class="badge badge-accent">依赖 #{esc(by_id[d]["number"])}</span>'
            if d in by_id else f'<span class="badge">依赖 {esc(d)}</span>'
            for d in deps
        )
        ci_badge = f'<span class="badge">{esc(ci_lbl)}</span>' if ci_lbl else ""
        pr_link = ext_link(pr["url"], f'#{pr["number"]}', "pr-id-link")
        branch_text = ""
        if pr.get("head_branch") or pr.get("base_branch"):
            branch_text = f'<span>分支：<code>{esc(pr.get("head_branch", ""))}</code> → <code>{esc(pr.get("base_branch", "main"))}</code></span>'
        author_text = f'<span>作者：{esc(pr["author"])}</span>' if pr.get("author") else ""
        diff_text = f'<span>变更：<code>{esc(pr["diff_stat"])}</code></span>' if pr.get("diff_stat") else ""

        details_html = ""
        if pr.get("notes") or pr.get("evidence_links"):
            ev_links = ""
            if pr.get("evidence_links"):
                ev_items = "".join(
                    f'<li>{ext_link(lk["url"], lk["label"])}</li>'
                    for lk in pr["evidence_links"]
                )
                ev_links = f'<ul style="margin:6px 0 0;padding-left:18px;">{ev_items}</ul>'
            details_html = (
                f'<details class="pr-details">'
                f'  <summary>查看审查要点与核验证据</summary>'
                f'  <div class="pr-details-body">'
                f'    <div>{esc(pr.get("notes", ""))}</div>'
                f'    {ev_links}'
                f'  </div>'
                f'</details>'
            )

        cards.append(
            f'<article class="pr-card{sel_cls}" id="pr-card-{esc(pid)}">'
            f'  <div class="pr-top">'
            f'    <label class="pr-check-label">'
            f'      <input type="checkbox" class="pr-checkbox" data-pr-id="{esc(pid)}"{checked_attr}>'
            f'      <span>{pr_link}<span class="pr-title-text">{esc(pr.get("title", ""))}</span></span>'
            f'    </label>'
            f'    <div class="badge-row">'
            f'      <span class="badge {badge_class_for_status(st)}">{esc(st_lbl)}</span>'
            f'      {ci_badge}'
            f'      {dep_badges}'
            f'    </div>'
            f'  </div>'
            f'  <div class="pr-meta">{branch_text}{author_text}{diff_text}</div>'
            f'  <p class="pr-summary">{esc(pr.get("summary", ""))}</p>'
            f'  {details_html}'
            f'</article>'
        )
    return "\n".join(cards)


def _is_gate_enabled(g: Dict[str, Any]) -> bool:
    if "authorized" in g:
        return bool(g["authorized"])
    return bool(g.get("default_enabled", False))


def render_approval_gates(gates: List[Dict[str, Any]]) -> str:
    if not gates:
        return ""
    items: List[str] = []
    for g in gates:
        gid = str(g["id"])
        enabled = _is_gate_enabled(g)
        checked_attr = " checked" if enabled else ""
        auth_cls = " is-authorized" if enabled else ""
        status_txt = "已授权" if enabled else "未授权"
        link_html = f' · {ext_link(g["url"], "查看关联对象")}' if g.get("url") else ""
        items.append(
            f'<div class="gate-card{auth_cls}">'
            f'  <div class="gate-info">'
            f'    <h4 class="gate-title">{esc(g.get("title", ""))} <span class="badge">{esc(gid)}</span></h4>'
            f'    <p class="gate-desc">{esc(g.get("description", ""))}{link_html}</p>'
            f'  </div>'
            f'  <label class="switch-wrap">'
            f'    <span class="gate-status-label">{status_txt}</span>'
            f'    <input type="checkbox" class="switch-input gate-toggle" data-gate-id="{esc(gid)}" role="switch"{checked_attr}>'
            f'  </label>'
            f'</div>'
        )
    return (
        '<div class="panel-section" data-rfh-role="gate-section">'
        '  <div class="section-header">'
        '    <h3 class="section-title">前置门禁独立授权开关</h3>'
        '    <span class="section-hint">独立开关实时写入回执，明确界定云端机是否有权执行联动动作</span>'
        '  </div>'
        f'  <div class="gate-list">{"".join(items)}</div>'
        '</div>'
    )


def validate_criterion_fields(c: Dict[str, Any]) -> None:
    for key, label in (
        ("target_and_status", "对应对象与现状"),
        ("ruling", "具体口径与作用"),
        ("unlock_and_blockers", "解锁效果与残余卡点"),
    ):
        raw = c.get(key)
        if not isinstance(raw, str) or len(raw.strip()) < 4:
            raise ValueError(
                f"判据 `{c.get('code', c.get('id'))}` 的必填项 `{key}`（{label}）必须是非空字符串（至少 4 个字符），禁止 null 或只写编号不写口径与卡点"
            )


def render_approval_criteria(criteria: List[Dict[str, Any]]) -> str:
    cards: List[str] = []
    for c in criteria:
        validate_criterion_fields(c)
        cid = str(c["id"])
        checked = bool(c.get("default_checked", False))
        checked_attr = " checked" if checked else ""
        signed_cls = " is-signed" if checked else ""
        link_html = ext_link(c["url"], c.get("link_label") or "直达 Issue / PR") if c.get("url") else ""
        st_lbl = c.get("status_label") or ("建议签字" if checked else "待人工裁决")
        st_cls = "badge-success" if checked else "badge-warning"
        cards.append(
            f'<article class="criteria-card{signed_cls}">'
            f'  <div class="criteria-header">'
            f'    <label class="criteria-check">'
            f'      <input type="checkbox" class="criterion-checkbox" data-criterion-id="{esc(cid)}"{checked_attr}>'
            f'      <span><span class="criteria-code">{esc(c.get("code", cid))}</span><span class="criteria-title">{esc(c.get("title", ""))}</span></span>'
            f'    </label>'
            f'    <div class="badge-row">'
            f'      <span class="badge {st_cls}">{esc(st_lbl)}</span>'
            f'      {link_html}'
            f'    </div>'
            f'  </div>'
            f'  <div class="criteria-grid">'
            f'    <div class="criteria-box"><div class="criteria-box-label">对应对象与现状</div><p class="criteria-box-body">{esc(c["target_and_status"])}</p></div>'
            f'    <div class="criteria-box"><div class="criteria-box-label">具体口径与作用</div><p class="criteria-box-body">{esc(c["ruling"])}</p></div>'
            f'    <div class="criteria-box"><div class="criteria-box-label">解锁效果与残余卡点</div><p class="criteria-box-body">{esc(c["unlock_and_blockers"])}</p></div>'
            f'  </div>'
            f'</article>'
        )
    return "\n".join(cards)


def render_handoff_conflict_banner(conflicts: Dict[str, Any]) -> str:
    has_conflicts = bool(conflicts.get("has_conflicts", False))
    items = conflicts.get("items") or []
    summary = conflicts.get("summary") or ("本轮合入无冲突，全部干净合入主干。" if not has_conflicts else "本轮合入过程中遇到并已解决以下冲突：")
    cls = "conflict-banner" if has_conflicts else "conflict-banner is-clean"
    title = "冲突解决高亮说明（已落盘核验）" if has_conflicts else "合入冲突核验：零冲突干净合入"
    list_html = ""
    if items:
        lis: List[str] = []
        for it in items:
            pr_part = ext_link(it["url"], it["pr_label"]) if it.get("url") else esc(it.get("pr_label", ""))
            commit_part = f'（解决提交：{ext_link(it["commit_url"], it["commit_sha"])}）' if it.get("commit_url") else ""
            lis.append(f'<li><strong>{pr_part}</strong>：{esc(it.get("resolution", ""))}{commit_part}</li>')
        list_html = f'<ul class="conflict-list">{"".join(lis)}</ul>'
    return (
        f'<section class="{cls}" id="conflict-banner" data-rfh-role="conflict-banner">'
        f'  <h3 class="conflict-title">{esc(title)}</h3>'
        f'  <p style="margin:0 0 6px;font-size:13px;color:var(--text-secondary);">{esc(summary)}</p>'
        f'  {list_html}'
        f'</section>'
    )


def render_handoff_filter_pills(prs: List[Dict[str, Any]]) -> str:
    counts = {
        "all": len(prs),
        "merged": sum(1 for p in prs if p.get("status") in ("merged", "conflict_resolved")),
        "conflict_resolved": sum(1 for p in prs if p.get("status") == "conflict_resolved" or p.get("conflict_note")),
        "blocked": sum(1 for p in prs if p.get("status") in ("blocked", "deferred")),
    }
    specs = [
        ("all", f'全部 ({counts["all"]})'),
        ("merged", f'已合入 ({counts["merged"]})'),
        ("conflict_resolved", f'已解冲突 ({counts["conflict_resolved"]})'),
        ("blocked", f'阻塞/暂缓 ({counts["blocked"]})'),
    ]
    return "".join(
        f'<button type="button" class="filter-pill" data-filter="{key}" aria-pressed="{"true" if key == "all" else "false"}">{esc(label)}</button>'
        for key, label in specs
    )


def render_handoff_prs(prs: List[Dict[str, Any]]) -> str:
    cards: List[str] = []
    for pr in prs:
        st = pr.get("status", "merged")
        st_lbl = pr.get("status_label") or {
            "merged": "已合入 Merged",
            "conflict_resolved": "冲突已解并合入",
            "blocked": "阻塞守护",
            "deferred": "本轮暂缓",
        }.get(st, st)
        has_conflict = bool(pr.get("conflict_note")) or st == "conflict_resolved"
        pr_link = ext_link(pr["url"], f'#{pr["number"]}', "pr-id-link")
        merge_sha_html = ""
        if pr.get("merge_commit_sha") and pr.get("merge_commit_url"):
            merge_sha_html = f'<span>合入提交：<code>{ext_link(pr["merge_commit_url"], pr["merge_commit_sha"][:8])}</code></span>'
        branch_html = f'<span>分支：<code>{esc(pr.get("head_branch", ""))}</code> → <code>{esc(pr.get("base_branch", "main"))}</code></span>' if pr.get("head_branch") else ""
        ci_badge = f'<span class="badge badge-info">{esc(pr["ci_status"])}</span>' if pr.get("ci_status") else ""
        conflict_html = (
            f'<div class="pr-conflict-note"><strong>冲突解决记录：</strong>{esc(pr["conflict_note"])}</div>'
            if pr.get("conflict_note") else ""
        )
        details_html = ""
        if pr.get("notes") or pr.get("evidence_links"):
            ev_links = ""
            if pr.get("evidence_links"):
                ev_items = "".join(f'<li>{ext_link(lk["url"], lk["label"])}</li>' for lk in pr["evidence_links"])
                ev_links = f'<ul style="margin:6px 0 0;padding-left:18px;">{ev_items}</ul>'
            details_html = (
                f'<details class="pr-details">'
                f'  <summary>查看落盘核验记录与证据链接</summary>'
                f'  <div class="pr-details-body"><div>{esc(pr.get("notes", ""))}</div>{ev_links}</div>'
                f'</details>'
            )
        search_blob = " ".join([
            f'#{pr.get("number", "")}',
            str(pr.get("title", "")),
            str(pr.get("head_branch", "")),
            str(pr.get("summary", "")),
            str(pr.get("conflict_note", "")),
            str(st_lbl),
        ])
        cards.append(
            f'<article class="pr-card" data-status="{esc(st)}" data-has-conflict="{"true" if has_conflict else "false"}" data-search-text="{esc(search_blob)}">'
            f'  <div class="pr-top">'
            f'    <div>{pr_link}<span class="pr-title-text">{esc(pr.get("title", ""))}</span></div>'
            f'    <div class="badge-row">'
            f'      <span class="badge {badge_class_for_status(st)}">{esc(st_lbl)}</span>'
            f'      {ci_badge}'
            f'    </div>'
            f'  </div>'
            f'  <div class="pr-meta">{merge_sha_html}{branch_html}</div>'
            f'  <p class="pr-summary">{esc(pr.get("summary", ""))}</p>'
            f'  {conflict_html}'
            f'  {details_html}'
            f'</article>'
        )
    return "\n".join(cards)


def render_handoff_gates_audit(gates: List[Dict[str, Any]]) -> str:
    if not gates:
        return ""
    items: List[str] = []
    for g in gates:
        authorized = bool(g.get("authorized", g.get("default_enabled", False)))
        cls = "gate-audit-card is-authorized" if authorized else "gate-audit-card"
        badge = '<span class="badge badge-success">已授权落盘</span>' if authorized else '<span class="badge badge-warning">未授权 / 保持关闭</span>'
        link_html = f' · {ext_link(g["url"], "查看审计链接")}' if g.get("url") else ""
        items.append(
            f'<div class="{cls}">'
            f'  <div><strong>{esc(g.get("title", ""))}</strong> <span class="badge">{esc(g.get("id", ""))}</span>'
            f'  <div style="font-size:12.5px;color:var(--text-secondary);margin-top:2px;">{esc(g.get("description", ""))}{link_html}</div></div>'
            f'  <div>{badge}</div>'
            f'</div>'
        )
    return (
        '<div class="panel-section">'
        '  <div class="section-header"><h3 class="section-title">前置门禁授权落盘审计</h3><span class="section-hint">记录本轮审批授权的实际执行状态</span></div>'
        f'  <div class="gate-audit-strip">{"".join(items)}</div>'
        '</div>'
    )


def render_handoff_criteria(criteria: List[Dict[str, Any]]) -> str:
    cards: List[str] = []
    for c in criteria:
        validate_criterion_fields(c)
        cst = c.get("status", "signed")
        st_lbl = c.get("status_label") or ("已签字落盘" if cst == "signed" else "阻塞守护")
        link_html = ext_link(c["url"], c.get("link_label") or "查看落盘凭证") if c.get("url") else ""
        cards.append(
            f'<article class="criteria-card" data-cstatus="{esc(cst)}">'
            f'  <div class="criteria-header">'
            f'    <div><span class="criteria-code">{esc(c.get("code", c.get("id", "")))}</span><span class="criteria-title">{esc(c.get("title", ""))}</span></div>'
            f'    <div class="badge-row"><span class="badge {badge_class_for_status(cst)}">{esc(st_lbl)}</span>{link_html}</div>'
            f'  </div>'
            f'  <div class="criteria-grid">'
            f'    <div class="criteria-box"><div class="criteria-box-label">对应对象与现状</div><p class="criteria-box-body">{esc(c["target_and_status"])}</p></div>'
            f'    <div class="criteria-box"><div class="criteria-box-label">具体口径与作用</div><p class="criteria-box-body">{esc(c["ruling"])}</p></div>'
            f'    <div class="criteria-box"><div class="criteria-box-label">解锁效果与残余卡点</div><p class="criteria-box-body">{esc(c["unlock_and_blockers"])}</p></div>'
            f'  </div>'
            f'</article>'
        )
    return "\n".join(cards)


def render_prompt_controls(prompt_cfg: Dict[str, Any]) -> Tuple[str, str]:
    modes = prompt_cfg.get("modes") or []
    raw_default = prompt_cfg.get("default_mode")
    default_mode = str(raw_default) if raw_default is not None else (str(modes[0]["id"]) if modes else "default")
    modes_html = "".join(
        f'<button type="button" class="prompt-mode-btn" data-prompt-mode="{esc(m["id"])}" '
        f'aria-pressed="{"true" if str(m["id"]) == default_mode else "false"}">{esc(m["label"])}</button>'
        for m in modes
    )
    modules = prompt_cfg.get("modules") or []
    modules_html = "".join(
        f'<label class="module-item">'
        f'  <input type="checkbox" class="prompt-module-cb" data-module-id="{esc(mod["id"])}"{" checked" if mod.get("default_checked", True) else ""}>'
        f'  <span><span class="module-title">{esc(mod["title"])}</span><span class="module-desc">{esc(mod.get("description", ""))}</span></span>'
        f'</label>'
        for mod in modules
    )
    return modes_html, modules_html


def build_initial_receipt(data: Dict[str, Any]) -> str:
    meta = data.get("meta") or {}
    prs = data.get("prs") or []
    criteria = data.get("criteria") or []
    gates = data.get("gates") or []
    approved = [p for p in prs if p.get("default_checked")]
    held = [p for p in prs if not p.get("default_checked")]
    signed = [c for c in criteria if c.get("default_checked")]
    kept = [c for c in criteria if not c.get("default_checked")]

    lines = [
        "【审批回执 · report-for-human@v2.1.0】",
        f'项目：{meta.get("project_name", "")}',
        f'锚定 main HEAD：{meta.get("main_head_sha", "")} ({meta.get("main_head_url", "")})',
        "审批模式：Mode A（审批态 Approval）",
        "",
    ]
    if gates:
        lines.append("一、前置门禁授权：")
        for g in gates:
            st = "已授权" if _is_gate_enabled(g) else "未授权"
            lines.append(f'- [{st}] {g["title"]}（{g["id"]}）')
        lines.append("")
    lines.append(f"二、批准合入的 PR（{len(approved)}/{len(prs)}）：")
    if not approved:
        lines.append("- （无：本轮暂不批准任何 PR 合入）")
    else:
        for p in approved:
            lines.append(f'- [APPROVE] #{p["number"]} {p["title"]} | {p["url"]}')
    if held:
        lines.append(f"暂缓/不合入 PR（{len(held)}）：")
        for p in held:
            lines.append(f'- [HOLD] #{p["number"]} {p["title"]}')
    lines.append("")
    lines.append(f"三、判据签字裁决（{len(signed)}/{len(criteria)}）：")
    if not signed:
        lines.append("- （无：本轮暂不签字任何判据）")
    else:
        for c in signed:
            lines.append(f'- [SIGN-OFF] {c["code"]} {c["title"]}（口径：{c["ruling"]}）')
    if kept:
        lines.append(f"暂缓/继续阻塞判据（{len(kept)}）：")
        for c in kept:
            lines.append(f'- [KEEP-OPEN] {c["code"]} {c["title"]}（残余卡点：{c["unlock_and_blockers"]}）')
    lines.append("")
    lines.append("执行约束：请严格按上述勾选与授权执行合入与签字落盘；完成后输出 Mode B（Handoff）交接报告并锚定最新 main HEAD。")
    return "\n".join(lines)


def build_initial_prompt(data: Dict[str, Any], mode: str) -> str:
    meta = data.get("meta") or {}
    prompt_cfg = data.get("prompt") or {}
    modes = prompt_cfg.get("modes") or []
    raw_default = prompt_cfg.get("default_mode")
    default_mode_id = str(raw_default) if raw_default is not None else (str(modes[0]["id"]) if modes else "default")
    active_mode = next((m for m in modes if str(m["id"]) == default_mode_id), {"label": "标准执行", "instructions": ""})
    modules = [m for m in (prompt_cfg.get("modules") or []) if m.get("default_checked", True)]
    constraint = normalize_zero_artifact_constraint(prompt_cfg.get("zero_artifact_constraint"))

    lines = [
        f'# 下一环启动指令（{prompt_cfg.get("target_machine", "内网工作机")}）',
        "",
        f'- 项目：{meta.get("project_name", "")}',
        f'- 锚定 main HEAD：{meta.get("main_head_sha", "")} ({meta.get("main_head_url", "")})',
        f'- 启动模式：{active_mode["label"]}',
    ]
    if mode == "handoff":
        short_sha = meta.get("main_head_short") or str(meta.get("main_head_sha", ""))[:8]
        lines.append(f'- 同步命令建议：`git fetch origin && git checkout main && git pull --ff-only origin main`（确认 HEAD 为 `{short_sha}`）')
    lines.append("")
    if prompt_cfg.get("preamble"):
        lines.append("## 前置上下文")
        lines.append(prompt_cfg["preamble"])
        lines.append("")
    if active_mode.get("instructions"):
        lines.append("## 模式执行要求")
        lines.append(active_mode["instructions"])
        lines.append("")
    lines.append(f"## 本轮勾选任务模块（{len(modules)} 项）")
    for idx, m in enumerate(modules, start=1):
        lines.append(f'{idx}. **{m["title"]}**：{m.get("prompt_text") or m.get("description", "")}')
    lines.append("")
    lines.append("## 强制回传约束（不可违反）")
    lines.append(f"- {constraint}")
    return "\n".join(lines)


def render_briefing_arch_svg(arch: Dict[str, Any]) -> str:
    layers = arch.get("layers") or []
    horizontals = arch.get("horizontals") or []
    if not layers:
        raise ValueError("Mode C (`briefing`) 必须提供 `architecture.layers` 分层定义")

    svg_w = 1040
    left_w = 690
    right_x = 735
    right_w = 275
    pad_x = 24
    pad_y = 26
    layer_h = 64
    layer_gap = 18
    total_layers_h = len(layers) * layer_h + max(0, len(layers) - 1) * layer_gap
    h_top = pad_y + 22
    h_gap = 10
    h_count = len(horizontals)
    h_avail = total_layers_h - 24
    h_box_h = max(36, (h_avail - max(0, h_count - 1) * h_gap) / max(1, h_count))
    horizontal_span = (h_top + h_count * h_box_h + max(0, h_count - 1) * h_gap) if h_count else 0
    svg_h = max(320, pad_y * 2 + total_layers_h + 24, int(horizontal_span + pad_y + 20))

    status_fill = {
        "ready": "var(--success-soft)",
        "partial": "var(--warning-soft)",
        "gap": "var(--danger-soft)",
    }
    status_stroke = {
        "ready": "var(--success)",
        "partial": "var(--warning)",
        "gap": "var(--danger)",
    }

    parts: List[str] = [
        f'<svg class="architecture-svg" viewBox="0 0 {svg_w} {svg_h}" width="{svg_w}" height="{svg_h}" role="img" aria-label="系统分层与横向平台架构图">',
        '  <defs>',
        '    <marker id="arch-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">',
        '      <path d="M 0 1 L 10 5 L 0 9 z" fill="var(--border-strong)" />',
        '    </marker>',
        '  </defs>',
    ]

    for idx, layer in enumerate(layers):
        y = pad_y + idx * (layer_h + layer_gap)
        st = layer.get("status", "partial")
        fill = status_fill.get(st, "var(--bg-surface)")
        stroke = status_stroke.get(st, "var(--accent)")
        gid = layer.get("gap_id", "")
        name = str(layer.get("name", ""))
        summary = str(layer.get("summary", ""))
        if len(summary) > 54:
            summary = summary[:53] + "…"
        gap_attr = f' data-arch-gap-id="{esc(gid)}"' if gid else ""
        role_attr = ' tabindex="0" role="button"' if gid else ""
        parts.append(
            f'  <g class="arch-node"{gap_attr}{role_attr} aria-label="聚焦架构层：{esc(name)}" transform="translate({pad_x}, {y})">'
            f'    <title>{esc(name)}: {esc(layer.get("summary", ""))}</title>'
            f'    <rect width="{left_w}" height="{layer_h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.8" />'
            f'    <text x="16" y="25" font-size="13.5" font-weight="800" fill="var(--text-primary)">{esc(name)}</text>'
            f'    <text x="16" y="47" font-size="12" fill="var(--text-secondary)">{esc(summary)}</text>'
            f'  </g>'
        )
        if idx < len(layers) - 1:
            ax = pad_x + left_w / 2
            y1 = y + layer_h
            y2 = y1 + layer_gap - 2
            parts.append(
                f'  <line x1="{ax:.1f}" y1="{y1}" x2="{ax:.1f}" y2="{y2}" stroke="var(--border-strong)" stroke-width="2" marker-end="url(#arch-arrow)" />'
            )

    if horizontals:
        frame_h = max(total_layers_h, horizontal_span - pad_y) + 20
        parts.append(
            f'  <rect x="{right_x - 10}" y="{pad_y - 10}" width="{right_w + 20}" height="{frame_h:.1f}" rx="12" '
            f'fill="var(--info-soft)" stroke="var(--info-border)" stroke-width="1.4" stroke-dasharray="5 4" />'
        )
        parts.append(
            f'  <text x="{right_x + 4}" y="{pad_y + 10}" font-size="11.5" font-weight="800" fill="var(--info)">横向平台能力与基础设施</text>'
        )
        for h_idx, h_item in enumerate(horizontals):
            hy = h_top + h_idx * (h_box_h + h_gap)
            parts.append(
                f'  <g transform="translate({right_x}, {hy:.1f})">'
                f'    <rect width="{right_w}" height="{h_box_h:.1f}" rx="8" fill="var(--bg-surface)" stroke="var(--border-strong)" stroke-width="1.2" />'
                f'    <text x="12" y="20" font-size="12.5" font-weight="700" fill="var(--text-primary)">{esc(h_item.get("name", ""))}</text>'
                f'    <text x="12" y="36" font-size="11" fill="var(--text-muted)">{esc(h_item.get("detail", ""))}</text>'
                f'  </g>'
            )

    parts.append("</svg>")
    return "\n".join(parts)


def render_briefing_gaps(gaps: List[Dict[str, Any]]) -> str:
    cards: List[str] = []
    for g in gaps:
        for key, label in (("current_state", "现状"), ("target_design", "目标设计"), ("blocker", "核心卡点 / 债务")):
            raw = g.get(key)
            if not isinstance(raw, str) or len(raw.strip()) < 4:
                raise ValueError(f"架构差距项 `{g.get('code', g.get('id'))}` 的 `{key}`（{label}）必须为非空字符串")
        gid = str(g["id"])
        sev = g.get("severity", "medium")
        st_lbl = g.get("status_label") or sev
        badge_cls = {"ok": "badge-success", "medium": "badge-warning", "high": "badge-danger"}.get(sev, "badge-accent")
        cards.append(
            f'<article class="gap-card" data-gap-id="{esc(gid)}" data-severity="{esc(sev)}" tabindex="-1">'
            f'  <div class="gap-header">'
            f'    <div><span class="gap-code">{esc(g.get("code", gid))}</span><span class="gap-title">{esc(g.get("title", ""))}</span></div>'
            f'    <span class="badge {badge_cls}">{esc(st_lbl)}</span>'
            f'  </div>'
            f'  <div class="gap-grid">'
            f'    <div class="gap-box"><div class="gap-box-label">现状</div><p class="gap-box-body">{esc(g["current_state"])}</p></div>'
            f'    <div class="gap-box"><div class="gap-box-label">目标设计</div><p class="gap-box-body">{esc(g["target_design"])}</p></div>'
            f'    <div class="gap-box"><div class="gap-box-label">核心卡点 / 债务</div><p class="gap-box-body">{esc(g["blocker"])}</p></div>'
            f'  </div>'
            f'</article>'
        )
    return "\n".join(cards)


def render_briefing_filter_pills(options: List[Dict[str, Any]], inventory: List[Dict[str, Any]]) -> str:
    if not options:
        options = [{"id": "all", "label": "全部"}]
    buttons: List[str] = []
    for opt in options:
        oid = str(opt["id"])
        cnt = len(inventory) if oid == "all" else sum(1 for item in inventory if item.get("kind") == oid)
        pressed = "true" if oid == "all" else "false"
        buttons.append(
            f'<button type="button" class="filter-pill" data-filter="{esc(oid)}" aria-pressed="{pressed}">{esc(opt["label"])} ({cnt})</button>'
        )
    return "".join(buttons)


def render_briefing_inventory(inventory: List[Dict[str, Any]]) -> str:
    cards: List[str] = []
    for item in inventory:
        kind = str(item.get("kind", "other"))
        tone = item.get("tone", "accent")
        badge_cls = badge_class_for_status({"success": "approved", "warning": "warning", "danger": "blocked", "info": "ready"}.get(tone, "ready"))
        search_blob = " ".join([
            str(item.get("id", "")),
            str(item.get("title", "")),
            str(item.get("kind_label", kind)),
            str(item.get("maturity", "")),
            str(item.get("summary", "")),
            str(item.get("details", "")),
        ])
        details_html = ""
        if item.get("details"):
            details_html = (
                '<details class="inv-details">'
                '  <summary>展开详细条目与技术说明</summary>'
                f'  <div class="inv-details-body">{esc(item["details"])}</div>'
                '</details>'
            )
        cards.append(
            f'<article class="inv-card" data-kind="{esc(kind)}" data-search-text="{esc(search_blob)}">'
            f'  <div class="inv-top">'
            f'    <div><span class="gap-code">{esc(item.get("id", ""))}</span><span class="gap-title">{esc(item.get("title", ""))}</span></div>'
            f'    <div class="badge-row">'
            f'      <span class="badge {badge_cls}">{esc(item.get("kind_label", kind))}</span>'
            f'      <span class="badge">{esc(item.get("maturity", ""))}</span>'
            f'    </div>'
            f'  </div>'
            f'  <p class="inv-summary">{esc(item.get("summary", ""))}</p>'
            f'  {details_html}'
            f'</article>'
        )
    return "\n".join(cards)


def render_briefing_platform_caps(caps: List[Dict[str, Any]]) -> str:
    cards: List[str] = []
    for cap in caps:
        tone = cap.get("tone", "warning")
        badge_cls = {"success": "badge-success", "warning": "badge-warning", "danger": "badge-danger"}.get(tone, "badge-info")
        cards.append(
            '<div class="cap-card">'
            '  <div class="section-header" style="margin-bottom:8px;">'
            f'    <h4 class="cap-title">{esc(cap.get("title", ""))}</h4>'
            f'    <span class="badge {badge_cls}">{esc(cap.get("status", ""))}</span>'
            '  </div>'
            f'  <p class="cap-meta"><strong>现状：</strong>{esc(cap.get("current", ""))}</p>'
            f'  <p class="cap-meta"><strong>缺口/方案：</strong>{esc(cap.get("gap", ""))}</p>'
            '</div>'
        )
    return "\n".join(cards)


def render_briefing_roadmap(roadmap: List[Dict[str, Any]]) -> str:
    items: List[str] = []
    for r in roadmap:
        items.append(
            '<div class="roadmap-item">'
            f'  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:4px;"><span class="badge badge-accent">{esc(r.get("phase", ""))}</span><strong>{esc(r.get("title", ""))}</strong></div>'
            f'  <div style="font-size:13px;color:var(--text-secondary);">{esc(r.get("detail", ""))}</div>'
            '</div>'
        )
    return "\n".join(items)


def build_initial_briefing_prompt(data: Dict[str, Any]) -> str:
    meta = data.get("meta") or {}
    prompt_cfg = data.get("prompt") or {}
    modes = prompt_cfg.get("modes") or []
    raw_default = prompt_cfg.get("default_mode")
    default_mode_id = str(raw_default) if raw_default is not None else (str(modes[0]["id"]) if modes else "default")
    active_mode = next((m for m in modes if str(m["id"]) == default_mode_id), {"label": "架构评审摘要", "instructions": ""})
    modules = [m for m in (prompt_cfg.get("modules") or []) if m.get("default_checked", True)]
    constraint = normalize_zero_artifact_constraint(prompt_cfg.get("zero_artifact_constraint"))

    lines = [
        f'# 架构与演进执行摘要（{prompt_cfg.get("target_machine", "研发协同")}）',
        "",
        f'- 项目：{meta.get("project_name", "")}',
        f'- 锚定 main HEAD：{meta.get("main_head_sha", "")} ({meta.get("main_head_url", "")})',
        f'- 当前视图模式：{active_mode["label"]}',
        "",
    ]
    if prompt_cfg.get("preamble"):
        lines.append("## 核心定性与背景")
        lines.append(prompt_cfg["preamble"])
        lines.append("")
    if active_mode.get("instructions"):
        lines.append("## 当前模式说明")
        lines.append(active_mode["instructions"])
        lines.append("")
    lines.append(f'## 已选定推进项（{len(modules)}/{len(prompt_cfg.get("modules") or [])}）')
    for idx, m in enumerate(modules, start=1):
        lines.append(f'{idx}. **{m["title"]}**：{m.get("prompt_text") or m.get("description", "")}')
    lines.append("")
    lines.append("## 强制约束")
    lines.append(f"- {constraint}")
    return "\n".join(lines)


def render_report(data: Dict[str, Any], mode: str) -> str:
    render_data = copy.deepcopy(data)
    meta = render_data.get("meta") or {}
    project_name = meta.get("project_name")
    if not project_name:
        raise ValueError("`meta.project_name` 不能为空")
    main_head_sha = meta.get("main_head_sha")
    if not main_head_sha:
        raise ValueError("`meta.main_head_sha` 不能为空")
    main_head_url = validate_url(meta.get("main_head_url", ""), "meta.main_head_url")
    main_head_short = meta.get("main_head_short") or str(main_head_sha)[:8]
    meta["main_head_short"] = main_head_short

    generated_at = str(meta.get("generated_at") or "").strip() or "未提供（not supplied）"
    default_titles = {
        "approval": f"{project_name} · PR 审批与判据签字汇报",
        "handoff": f"{project_name} · 合入落盘与跨机交接汇报",
        "briefing": f"{project_name} · 架构蓝图与资产盘点深度汇报",
    }
    report_title = meta.get("report_title") or default_titles[mode]
    report_subtitle = meta.get("report_subtitle") or ""
    page_title = f"{report_title} | report-for-human@v2.1.0"

    prompt_cfg = render_data.get("prompt") or {}
    zero_constraint = normalize_zero_artifact_constraint(prompt_cfg.get("zero_artifact_constraint"))
    prompt_cfg["zero_artifact_constraint"] = zero_constraint
    render_data["prompt"] = prompt_cfg

    prs = render_data.get("prs") or []
    criteria = render_data.get("criteria") or []
    gates = render_data.get("gates") or []
    steps_html = render_steps(render_data.get("steps") or [])
    kpi_html = render_kpis(render_data.get("kpis") or [])
    prompt_modes_html, prompt_modules_html = render_prompt_controls(prompt_cfg)
    initial_prompt = build_initial_briefing_prompt(render_data) if mode == "briefing" else build_initial_prompt(render_data, mode)

    template_name = {
        "approval": "approval_report.html",
        "handoff": "handoff_report.html",
        "briefing": "briefing_report.html",
    }[mode]
    template_file = TEMPLATES_DIR / template_name
    template_text = template_file.read_text(encoding="utf-8")

    replacements: Dict[str, str] = {
        "{{PAGE_TITLE}}": esc(page_title),
        "{{PROJECT_NAME}}": esc(project_name),
        "{{REPORT_TITLE}}": esc(report_title),
        "{{REPORT_SUBTITLE}}": esc(report_subtitle),
        "{{GENERATED_AT}}": esc(generated_at),
        "{{MAIN_HEAD_SHORT}}": esc(main_head_short),
        "{{MAIN_HEAD_URL}}": esc(main_head_url),
        "{{SSR_STEPS_HTML}}": steps_html,
        "{{SSR_KPI_HTML}}": kpi_html,
        "{{SSR_PROMPT_MODES_HTML}}": prompt_modes_html,
        "{{SSR_PROMPT_MODULES_HTML}}": prompt_modules_html,
        "{{ZERO_ARTIFACT_CONSTRAINT}}": esc(zero_constraint),
        "{{INITIAL_PROMPT_CHARS}}": str(len(initial_prompt)),
        "{{SSR_PROMPT_INITIAL}}": esc(initial_prompt),
        "{{REPORT_DATA_JSON}}": safe_json_for_script(render_data),
    }

    if mode == "approval":
        approved_cnt = sum(1 for p in prs if p.get("default_checked"))
        signed_cnt = sum(1 for c in criteria if c.get("default_checked"))
        gate_cnt = sum(1 for g in gates if _is_gate_enabled(g))
        gate_part = f" · 门禁 {gate_cnt}/{len(gates)}" if gates else ""
        initial_receipt = build_initial_receipt(render_data)
        replacements.update({
            "{{TAB1_COUNT}}": str(len(prs)),
            "{{TAB2_COUNT}}": str(len(criteria)),
            "{{TAB3_COUNT}}": str(len(prompt_cfg.get("modules") or [])),
            "{{INITIAL_COUNTER_TEXT}}": esc(f"已批 PR {approved_cnt}/{len(prs)} · 签字 {signed_cnt}/{len(criteria)}{gate_part}"),
            "{{PR_SELECTION_SUMMARY}}": esc(f"已勾选 {approved_cnt} / {len(prs)} 个 PR"),
            "{{CRITERIA_SELECTION_SUMMARY}}": esc(f"已签字 {signed_cnt} / {len(criteria)} 项判据"),
            "{{SSR_SVG_TOPOLOGY}}": render_svg_topology(meta, prs),
            "{{SSR_PR_LIST_HTML}}": render_approval_prs(prs),
            "{{SSR_GATES_SECTION_HTML}}": render_approval_gates(gates),
            "{{SSR_CRITERIA_HTML}}": render_approval_criteria(criteria),
            "{{SSR_RECEIPT_INITIAL}}": esc(initial_receipt),
            "{{INITIAL_RECEIPT_CHARS}}": str(len(initial_receipt)),
        })
    elif mode == "handoff":
        merged_cnt = sum(1 for p in prs if p.get("status") in ("merged", "conflict_resolved"))
        mod_cnt = sum(1 for m in (prompt_cfg.get("modules") or []) if m.get("default_checked", True))
        total_mods = len(prompt_cfg.get("modules") or [])
        replacements.update({
            "{{TAB1_COUNT}}": str(len(prs)),
            "{{TAB2_COUNT}}": str(len(criteria)),
            "{{TAB3_COUNT}}": str(total_mods),
            "{{INITIAL_COUNTER_TEXT}}": esc(f"已合入 {merged_cnt}/{len(prs)} · 模块 {mod_cnt}/{total_mods} · {len(initial_prompt)} 字符"),
            "{{SSR_CONFLICT_BANNER_HTML}}": render_handoff_conflict_banner(render_data.get("conflicts") or {}),
            "{{SSR_FILTER_PILLS_HTML}}": render_handoff_filter_pills(prs),
            "{{SSR_PR_LIST_HTML}}": render_handoff_prs(prs),
            "{{SSR_GATES_AUDIT_HTML}}": render_handoff_gates_audit(gates),
            "{{SSR_CRITERIA_HTML}}": render_handoff_criteria(criteria),
        })
    else:
        arch = render_data.get("architecture") or {}
        layers = arch.get("layers") or []
        horizontals = arch.get("horizontals") or []
        arch_title = (
            f"{len(layers)} 层纵向架构 + {len(horizontals)} 项横向平台能力（SVG）"
            if horizontals else f"{len(layers)} 层纵向架构（SVG）"
        )
        gaps = render_data.get("gaps") or []
        inventory = render_data.get("inventory") or []
        platform_caps = render_data.get("platform_capabilities") or []
        roadmap = render_data.get("roadmap") or []
        mod_cnt = sum(1 for m in (prompt_cfg.get("modules") or []) if m.get("default_checked", True))
        total_mods = len(prompt_cfg.get("modules") or [])
        replacements.update({
            "{{TAB1_COUNT}}": str(len(gaps)),
            "{{TAB2_COUNT}}": str(len(inventory)),
            "{{TAB3_COUNT}}": str(len(platform_caps) + len(roadmap)),
            "{{INITIAL_COUNTER_TEXT}}": esc(f"架构模块 {len(gaps)} · 盘点 {len(inventory)} · 已选推进 {mod_cnt}/{total_mods}"),
            "{{ARCH_SECTION_TITLE}}": esc(arch_title),
            "{{SSR_ARCH_SVG}}": render_briefing_arch_svg(arch),
            "{{SSR_GAPS_HTML}}": render_briefing_gaps(gaps),
            "{{SSR_BRIEFING_FILTER_PILLS}}": render_briefing_filter_pills(render_data.get("filter_options") or [], inventory),
            "{{SSR_INVENTORY_HTML}}": render_briefing_inventory(inventory),
            "{{SSR_PLATFORM_CAPS_HTML}}": render_briefing_platform_caps(platform_caps),
            "{{SSR_ROADMAP_HTML}}": render_briefing_roadmap(roadmap),
        })

    slot_pattern = re.compile("|".join(re.escape(key) for key in replacements))
    return slot_pattern.sub(lambda match: replacements[match.group(0)], template_text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a report-for-human@v2.1.0 interactive single-file HTML report.")
    parser.add_argument("--mode", choices=["approval", "handoff", "briefing"], default=None, help="Report mode (approval, handoff, or briefing)")
    parser.add_argument("--input", required=True, help="Path to input JSON data file")
    parser.add_argument("--output", required=True, help="Path to output HTML file")
    parser.add_argument("--skip-validate", action="store_true", help="Skip automatic post-render validation")
    parser.add_argument("--allow-in-skill-dir", action="store_true", help="Allow writing output inside the skill directory")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()

    same_target = input_path == output_path
    if not same_target and input_path.exists() and output_path.exists():
        try:
            same_target = input_path.samefile(output_path)
        except OSError:
            same_target = False
    if same_target:
        print(f"[ERROR] 禁止输出路径覆盖输入 JSON 文件: {output_path}", file=sys.stderr)
        return 2

    if not args.allow_in_skill_dir:
        try:
            output_path.relative_to(SKILL_ROOT)
            print(f"[ERROR] 禁止将生成的业务汇报写入技能安装目录内: {output_path}", file=sys.stderr)
            return 2
        except ValueError:
            pass

    data = json.loads(input_path.read_text(encoding="utf-8"))
    json_mode = data.get("mode")
    mode = args.mode or json_mode
    if mode not in ("approval", "handoff", "briefing"):
        print("[ERROR] 必须通过 --mode 或 JSON 顶层 `mode` 字段指定合法模式（approval / handoff / briefing）", file=sys.stderr)
        return 2
    if args.mode and json_mode and args.mode != json_mode:
        print(f"[ERROR] 模式冲突：CLI --mode={args.mode} 与 JSON mode={json_mode} 不一致，禁止混用模式", file=sys.stderr)
        return 2

    html_out = render_report(data, mode)

    if not args.skip_validate:
        errors, warnings = validate_html(html_out, expected_mode=mode)
        for w in warnings:
            print(f"[WARN]  {w}")
        for e in errors:
            print(f"[FAIL]  {e}", file=sys.stderr)
        if errors:
            print(f"[ERROR] Post-render validation failed with {len(errors)} error(s).", file=sys.stderr)
            return 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_out, encoding="utf-8")
        print(f"[OK] Generated {mode} report: {output_path} ({len(html_out.encode('utf-8'))} bytes)")
        print(f"[PASS]  Post-render validation passed ({len(warnings)} warning(s)).")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_out, encoding="utf-8")
    print(f"[OK] Generated {mode} report: {output_path} ({len(html_out.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
