#!/usr/bin/env python3
"""
report-for-human@v2.0.0 deterministic single-file HTML report renderer.

Renders Mode A (approval) or Mode B (handoff) HTML from a verified JSON payload
using templates/approval_report.html or templates/handoff_report.html, then
runs validate_dual_mode_report.py automatically before exiting.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from validate_dual_mode_report import validate_html
except ImportError:
    _scripts_dir = str(Path(__file__).resolve().parent)
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)
    from validate_dual_mode_report import validate_html


SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"

DEFAULT_ZERO_ARTIFACT_CONSTRAINT = (
    "零图片/零文件回传约束：严禁回传截图、图片、压缩包或任何本地附件文件，"
    "仅以结构化纯文本/Markdown 汇报执行结果、关键命令摘要与可验证 GitHub 链接。"
)


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def safe_json_for_script(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False)
    return (
        raw.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def validate_url(url: str, field_name: str) -> str:
    cleaned = (url or "").strip()
    if not (cleaned.startswith("https://") or cleaned.startswith("http://")):
        raise ValueError(f"字段 `{field_name}` 必须是真实可直达的 http(s) URL，当前值: {url!r}")
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
            f'<g class="dag-node {checked_cls}" data-svg-pr-id="{esc(pid)}" transform="translate({x:.1f}, {y:.1f})">'
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


def render_approval_gates(gates: List[Dict[str, Any]]) -> str:
    if not gates:
        return ""
    items: List[str] = []
    for g in gates:
        gid = str(g["id"])
        enabled = bool(g.get("default_enabled", False))
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
        val = str(c.get(key, "")).strip()
        if len(val) < 4:
            raise ValueError(
                f"判据 `{c.get('code', c.get('id'))}` 的必填项 `{key}`（{label}）不能为空或过短，禁止只写编号不写口径与卡点"
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
        "merged": sum(1 for p in prs if p.get("status") == "merged"),
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
    default_mode = prompt_cfg.get("default_mode") or (modes[0]["id"] if modes else "default")
    modes_html = "".join(
        f'<button type="button" class="prompt-mode-btn" data-prompt-mode="{esc(m["id"])}" '
        f'aria-pressed="{"true" if m["id"] == default_mode else "false"}">{esc(m["label"])}</button>'
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
        "【审批回执 · report-for-human@v2.0.0】",
        f'项目：{meta.get("project_name", "")}',
        f'锚定 main HEAD：{meta.get("main_head_sha", "")} ({meta.get("main_head_url", "")})',
        "审批模式：Mode A（审批态 Approval）",
        "",
    ]
    if gates:
        lines.append("一、前置门禁授权：")
        for g in gates:
            st = "已授权" if g.get("default_enabled") else "未授权"
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
    default_mode_id = prompt_cfg.get("default_mode") or (modes[0]["id"] if modes else "default")
    active_mode = next((m for m in modes if m["id"] == default_mode_id), {"label": "标准执行", "instructions": ""})
    modules = [m for m in (prompt_cfg.get("modules") or []) if m.get("default_checked", True)]
    constraint = prompt_cfg.get("zero_artifact_constraint") or DEFAULT_ZERO_ARTIFACT_CONSTRAINT

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


def render_report(data: Dict[str, Any], mode: str) -> str:
    meta = data.get("meta") or {}
    project_name = meta.get("project_name")
    if not project_name:
        raise ValueError("`meta.project_name` 不能为空")
    main_head_sha = meta.get("main_head_sha")
    if not main_head_sha:
        raise ValueError("`meta.main_head_sha` 不能为空")
    main_head_url = validate_url(meta.get("main_head_url", ""), "meta.main_head_url")
    main_head_short = meta.get("main_head_short") or str(main_head_sha)[:8]
    meta["main_head_short"] = main_head_short

    generated_at = meta.get("generated_at") or datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    report_title = meta.get("report_title") or (
        f"{project_name} · PR 审批与判据签字汇报" if mode == "approval" else f"{project_name} · 合入落盘与跨机交接汇报"
    )
    report_subtitle = meta.get("report_subtitle") or ""
    page_title = f"{report_title} | report-for-human@v2.0.0"

    prompt_cfg = data.get("prompt") or {}
    zero_constraint = prompt_cfg.get("zero_artifact_constraint") or DEFAULT_ZERO_ARTIFACT_CONSTRAINT
    prompt_cfg["zero_artifact_constraint"] = zero_constraint
    data["prompt"] = prompt_cfg

    prs = data.get("prs") or []
    criteria = data.get("criteria") or []
    gates = data.get("gates") or []
    steps_html = render_steps(data.get("steps") or [])
    kpi_html = render_kpis(data.get("kpis") or [])
    prompt_modes_html, prompt_modules_html = render_prompt_controls(prompt_cfg)
    initial_prompt = build_initial_prompt(data, mode)

    template_file = TEMPLATES_DIR / ("approval_report.html" if mode == "approval" else "handoff_report.html")
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
        "{{TAB1_COUNT}}": str(len(prs)),
        "{{TAB2_COUNT}}": str(len(criteria)),
        "{{TAB3_COUNT}}": str(len(prompt_cfg.get("modules") or [])),
        "{{SSR_PROMPT_MODES_HTML}}": prompt_modes_html,
        "{{SSR_PROMPT_MODULES_HTML}}": prompt_modules_html,
        "{{ZERO_ARTIFACT_CONSTRAINT}}": esc(zero_constraint),
        "{{INITIAL_PROMPT_CHARS}}": str(len(initial_prompt)),
        "{{SSR_PROMPT_INITIAL}}": esc(initial_prompt),
        "{{REPORT_DATA_JSON}}": safe_json_for_script(data),
    }

    if mode == "approval":
        approved_cnt = sum(1 for p in prs if p.get("default_checked"))
        signed_cnt = sum(1 for c in criteria if c.get("default_checked"))
        gate_cnt = sum(1 for g in gates if g.get("default_enabled"))
        gate_part = f" · 门禁 {gate_cnt}/{len(gates)}" if gates else ""
        initial_receipt = build_initial_receipt(data)
        replacements.update({
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
    else:
        merged_cnt = sum(1 for p in prs if p.get("status") in ("merged", "conflict_resolved"))
        mod_cnt = sum(1 for m in (prompt_cfg.get("modules") or []) if m.get("default_checked", True))
        total_mods = len(prompt_cfg.get("modules") or [])
        replacements.update({
            "{{INITIAL_COUNTER_TEXT}}": esc(f"已合入 {merged_cnt}/{len(prs)} · 模块 {mod_cnt}/{total_mods} · {len(initial_prompt)} 字符"),
            "{{SSR_CONFLICT_BANNER_HTML}}": render_handoff_conflict_banner(data.get("conflicts") or {}),
            "{{SSR_FILTER_PILLS_HTML}}": render_handoff_filter_pills(prs),
            "{{SSR_PR_LIST_HTML}}": render_handoff_prs(prs),
            "{{SSR_GATES_AUDIT_HTML}}": render_handoff_gates_audit(gates),
            "{{SSR_CRITERIA_HTML}}": render_handoff_criteria(criteria),
        })

    output_html = template_text
    for placeholder, value in replacements.items():
        output_html = output_html.replace(placeholder, value)

    return output_html


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a report-for-human@v2.0.0 interactive single-file HTML report.")
    parser.add_argument("--mode", choices=["approval", "handoff"], default=None, help="Report mode (approval or handoff)")
    parser.add_argument("--input", required=True, help="Path to input JSON data file")
    parser.add_argument("--output", required=True, help="Path to output HTML file")
    parser.add_argument("--skip-validate", action="store_true", help="Skip automatic post-render validation")
    parser.add_argument("--allow-in-skill-dir", action="store_true", help="Allow writing output inside the skill directory")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()

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
    if mode not in ("approval", "handoff"):
        print("[ERROR] 必须通过 --mode 或 JSON 顶层 `mode` 字段指定合法模式（approval 或 handoff）", file=sys.stderr)
        return 2
    if args.mode and json_mode and args.mode != json_mode:
        print(f"[ERROR] 模式冲突：CLI --mode={args.mode} 与 JSON mode={json_mode} 不一致，禁止混用模式", file=sys.stderr)
        return 2

    html_out = render_report(data, mode)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_out, encoding="utf-8")
    print(f"[OK] Generated {mode} report: {output_path} ({len(html_out.encode('utf-8'))} bytes)")

    if not args.skip_validate:
        errors, warnings = validate_html(html_out, expected_mode=mode)
        for w in warnings:
            print(f"[WARN]  {w}")
        for e in errors:
            print(f"[FAIL]  {e}", file=sys.stderr)
        if errors:
            print(f"[ERROR] Post-render validation failed with {len(errors)} error(s).", file=sys.stderr)
            return 1
        print(f"[PASS]  Post-render validation passed ({len(warnings)} warning(s)).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
