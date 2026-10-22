#!/usr/bin/env python3
"""Render verified report data into the bundled offline visual language."""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import re
import textwrap
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
KINDS = {"change": "改动", "requirements": "要求", "status": "现状", "mechanism": "机制"}
STATES = {"done": "已完成", "current": "当前环节", "pending": "待进行", "unknown": "待核实"}


def text(value):
    if not isinstance(value, str):
        raise ValueError("Report text must be a string")
    return escape(value, quote=True)


def link(label, url):
    if urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).netloc:
        raise ValueError("Evidence links must be absolute HTTP(S) URLs")
    return f'<a href="{text(url)}" rel="noopener noreferrer">{text(label)}</a>'


def badge(label):
    return f'<span class="rf-badge">{text(label)}</span>'


def svg_text(value, x, y, cls, width=14):
    lines = textwrap.wrap(value, width=width, break_long_words=True) or [""]
    return f'<text x="{x}" y="{y}" class="{cls}">' + "".join(
        f'<tspan x="{x}" dy="{0 if i == 0 else 23}">{text(line)}</tspan>'
        for i, line in enumerate(lines)
    ) + '</text>'


def graph(data):
    owners, nodes, edges = data["owners"], data["nodes"], data["edges"]
    if not 1 <= len(owners) <= 4 or not 1 <= len(nodes) <= 16:
        raise ValueError("Use 1–4 owners and 1–16 nodes; split larger diagrams")
    by_id, occupied = {}, set()
    for n in nodes:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", n["id"]) or n["id"] in by_id:
            raise ValueError("Graph node ids must be unique identifiers")
        col, row = n["owner"], n["row"]
        if type(col) is not int or type(row) is not int or not 0 <= col < len(owners) or not 0 <= row <= 5:
            raise ValueError("Invalid owner/row position")
        if (col, row) in occupied or len(n["title"]) > 24 or len(n["detail"]) > 44:
            raise ValueError("Keep nodes distinct and labels short; put detail in evidence")
        occupied.add((col, row)); by_id[n["id"]] = n
    w, h = len(owners) * 290, (max(n["row"] for n in nodes) + 1) * 190 + 60
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="flow-title flow-desc">',
             '<title id="flow-title">参与方与数据流</title><desc id="flow-desc">箭头标注输入、事件或条件；窄屏下方按同一节点与箭头重排。</desc>',
             '<defs><marker id="rf-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path class="rf-marker" d="M0 0 L8 4 L0 8 Z"/></marker></defs>']
    for i, owner in enumerate(owners):
        parts += [f'<rect class="rf-lane rf-lane-{i}" x="{i*290+5}" y="0" width="280" height="{h}" rx="18"/>', svg_text(owner, i*290+21, 30, "rf-node-detail", 20)]
    for e in edges:
        if e["from"] not in by_id or e["to"] not in by_id or not e["label"]:
            raise ValueError("Every edge needs existing endpoints and a meaningful label")
        a, b = by_id[e["from"]], by_id[e["to"]]
        ax, ay, bx, by = a["owner"]*290+145, a["row"]*190+190, b["owner"]*290+145, b["row"]*190+66
        if a["row"] == b["row"]:
            # Separate incoming/outgoing bottom ports so adjacent edges do not
            # overlap into an apparently continuous, ambiguous bus.
            direction = 1 if b["owner"] > a["owner"] else -1
            ax += direction * 100
            bx -= direction * 100
            by = b["row"]*190+190
            mid = ay + 36
        else:
            mid = (ay + by) / 2
        label_x, wrap = (ax+9, 9) if ax == bx else (min(ax,bx)+9, 9 if abs(ax-bx)<180 else 22)
        parts += [f'<g data-edge="{a["id"]}|{b["id"]}"><path class="rf-edge" marker-end="url(#rf-arrow)" d="M{ax} {ay} V{mid} H{bx} V{by}"/>',
                  svg_text(e["label"], label_x, mid-8, "rf-edge-label", wrap).replace('<text ', f'<text data-wrap="{wrap}" data-edge-label="{a["id"]}|{b["id"]}" ', 1), '</g>']
    mobile = []
    for n in nodes:
        x, y = n["owner"]*290+16, n["row"]*190+58
        parts += [f'<g data-node="{n["id"]}"><rect class="rf-node" x="{x}" y="{y}" width="258" height="132" rx="14"/>',
                  svg_text(n["title"], x+15, y+32, "rf-node-title", 12).replace('<text ', f'<text data-node-title="{n["id"]}" ', 1),
                  svg_text(n["detail"], x+15, y+82, "rf-node-detail", 17).replace('<text ', f'<text data-node-detail="{n["id"]}" ', 1), '</g>']
        outgoing = [f'<span data-edge-label="{e["from"]}|{e["to"]}">{text(e["label"])}</span> → <span data-node-title="{e["to"]}">{text(by_id[e["to"]]["title"])}</span>' for e in edges if e["from"] == n["id"]]
        mobile.append(f'<li data-node="{n["id"]}">{badge(owners[n["owner"]])}<h3 data-node-title="{n["id"]}">{text(n["title"])}</h3><p data-node-detail="{n["id"]}">{text(n["detail"])}</p>' + ''.join(f'<p class="rf-caption">↳ {s}</p>' for s in outgoing) + '</li>')
    parts.append('</svg>')
    return '<div class="rf-flow">' + ''.join(parts) + '<ol class="rf-flow-mobile">' + ''.join(mobile) + '</ol></div>'


def visual(d):
    kind = d["kind"]
    if kind == "change":
        return '<div class="rf-compare"><article><span class="rf-caption">原来</span><h3>'+text(d["before"])+ '</h3></article><span class="rf-arrow" aria-hidden="true">→</span><article><span class="rf-caption">现在</span><h3>'+text(d["after"])+ '</h3></article></div><p class="rf-band">'+text(d["impact"])+ '</p>'
    if kind == "requirements":
        return ''.join('<article class="rf-rule">'+badge(r["authority"])+ '<h3>'+text(r["rule"])+ '</h3><div class="rf-rule-grid"><div><span class="rf-caption">适用条件</span><p>'+text(r["when"])+ '</p></div><div><span class="rf-caption">验收方式</span><p>'+text(r["accept"])+ '</p></div><div><span class="rf-caption">来源与确定性</span><p>'+text(r["basis"])+ '</p></div></div></article>' for r in d["rules"])
    if kind == "status":
        stages = []
        for s in d["stages"]:
            if s["state"] not in STATES:
                raise ValueError("Stage state must be done/current/pending/unknown")
            stages.append(f'<li class="rf-stage" data-state="{s["state"]}">'+badge(STATES[s["state"]])+ '<h3>'+text(s["title"])+ '</h3><p>'+text(s["detail"])+ '</p></li>')
        return '<ol class="rf-stages">'+''.join(stages)+'</ol>'
    return graph(d["graph"])


def render(d):
    if d.get("kind") not in KINDS:
        raise ValueError("kind must be change/requirements/status/mechanism")
    for key in ["title", "summary", "scope", "as_of"]:
        if not isinstance(d.get(key), str) or not d[key].strip():
            raise ValueError(f"Missing nonempty {key}")
    if len(d.get("next_actions", [])) > 2:
        raise ValueError("Choose at most two concrete next actions")
    spotlight = d["spotlight"]
    limits = ''.join('<p class="rf-limit">'+text(x)+'</p>' for x in d.get("limitations", []))
    actions = ''.join('<article class="rf-action">'+badge(a["owner"])+ '<h3>'+text(a["action"])+ '</h3><p>'+text(a["effect"])+ '</p></article>' for a in d.get("next_actions", []))
    evidence = ''.join('<li><strong>'+(link(e["label"], e["url"]) if e.get("url") else text(e["label"]))+'</strong><p>'+text(e["detail"])+ '</p></li>' for e in d.get("evidence", []))
    scenarios = d.get("scenarios", [])
    if scenarios and d["kind"] != "mechanism":
        raise ValueError("Scenario controls are for mechanism graphs")
    controls, static = '', ''
    for i, s in enumerate(scenarios):
        if s["basis"] not in {"观察", "模拟"}:
            raise ValueError("Scenario basis must explicitly be 观察 or 模拟")
        nodes = {n["id"] for n in d["graph"]["nodes"]}
        if not set(s.get("active_nodes", [])) <= nodes or not set(s.get("titles", {})) <= nodes or not set(s.get("details", {})) <= nodes:
            raise ValueError("Scenario references a missing node")
        edge_ids = {e['from']+'|'+e['to'] for e in d['graph']['edges']}
        if not set(s.get('edge_labels', {})) <= edge_ids:
            raise ValueError("Scenario references a missing edge")
        for field in ['titles', 'details', 'edge_labels']:
            for value in s.get(field, {}).values():
                text(value)
        controls += f'<button type="button" data-scenario="{i}" aria-pressed="{str(i==0).lower()}">{text(s["label"])} · {text(s["basis"])}</button>'
        static += '<li>'+text(s["label"])+ '（'+text(s["basis"])+ '）：'+text(s["summary"])+ '</li>'
    if controls:
        controls = '<div class="rf-controls" role="group" aria-label="本地场景演示">'+controls+'</div><p class="rf-caption">场景切换只在本页演示，不改变真实系统。</p>'
    css = '\n'.join((ROOT/'assets'/p).read_text(encoding='utf-8') for p in ['report-theme.css','report-layout.css'])
    lines = d.get('title_lines')
    if lines is None:
        first, sep, rest = d['title'].partition('，')
        lines = [first+sep, rest] if sep else [d['title']]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 3 or ''.join(lines) != d['title']:
        raise ValueError('title_lines must preserve the exact title in 1–3 semantic lines')
    headline = '<br>'.join(('<em>'+text(line)+'</em>') if i else text(line) for i,line in enumerate(lines))
    page = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+text(d["title"])+ '</title><style>'+css+'</style></head><body><main class="human-report"><div class="rf-topbar"><span class="rf-brand">'+text(d["scope"])+ '</span><span>'+text(d["as_of"])+ '</span></div><header class="rf-hero"><div><p class="rf-kicker">'+text(d.get("eyebrow", KINDS[d["kind"]]+' · 人类汇报'))+'</p><h1>'+headline+ '</h1><p class="rf-lead">'+text(d["summary"])+ '</p>'+limits+'</div><aside class="rf-spotlight"><small>'+text(spotlight["label"])+ '</small><strong>'+text(spotlight["value"])+ '</strong><p>'+text(spotlight["detail"])+ '</p></aside></header><section class="rf-panel" aria-labelledby="visual-heading"><p class="rf-kicker">核心关系</p><h2 id="visual-heading">'+text(d.get("visual_title", KINDS[d["kind"]]))+'</h2>'+controls+visual(d)
    if scenarios:
        page += '<p class="rf-band" id="scenario-result" aria-live="polite">'+text(scenarios[0]["summary"])+ '</p><ul class="rf-print-states">'+static+'</ul><noscript><p>脚本未启用；主图保留默认关系，以下是各假设状态：</p><ul>'+static+'</ul></noscript>'
    page += '</section><section class="rf-actions" aria-label="下一步">'+actions+'</section><details><summary>证据、版本与适用边界</summary><ul class="rf-evidence">'+evidence+'</ul></details><footer>'+text(d.get("footer", "自包含 HTML · 状态以标注的取证时间为准 · 汇报不构成操作授权"))+'</footer></main>'
    payload = json.dumps({"scenarios": scenarios,"nodes": d.get("graph",{}).get("nodes",[]),"edges":d.get("graph",{}).get("edges",[])},ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    page += '<script type="application/json" id="report-data">'+payload+'</script><script>\n'+'''(()=>{'use strict';
const data=JSON.parse(document.getElementById('report-data').textContent);
function show(i){const s=data.scenarios[i];if(!s)return;
document.querySelectorAll('[data-scenario]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.scenario)===i)));
document.querySelectorAll('[data-node]').forEach(n=>n.dataset.dimmed=String(Boolean(s.active_nodes?.length)&&!s.active_nodes.includes(n.dataset.node)));
function update(selector,value,width){document.querySelectorAll(selector).forEach(el=>{
if(el.namespaceURI==='http://www.w3.org/2000/svg'){
const count=Number(el.dataset.wrap)||width;
const chunks=Array.from(value).reduce((a,c,i)=>{if(i%count===0)a.push('');a[a.length-1]+=c;return a},[]);
el.replaceChildren(...chunks.map((v,i)=>{const t=document.createElementNS(el.namespaceURI,'tspan');t.setAttribute('x',el.getAttribute('x'));t.setAttribute('dy',i?'23':'0');t.textContent=v;return t}));
}else el.textContent=value;});}
for(const n of data.nodes){update('[data-node-title="'+n.id+'"]',s.titles?.[n.id]??n.title,12);update('[data-node-detail="'+n.id+'"]',s.details?.[n.id]??n.detail,17);}
for(const e of data.edges)update('[data-edge-label="'+e.from+'|'+e.to+'"]',s.edge_labels?.[e.from+'|'+e.to]??e.label,22);
document.getElementById('scenario-result').textContent=s.basis+'：'+s.summary;}
document.querySelectorAll('[data-scenario]').forEach(b=>b.addEventListener('click',()=>show(Number(b.dataset.scenario))));
if(data.scenarios.length)show(0);
const details=[...document.querySelectorAll('details')];let wasOpen=[];
addEventListener('beforeprint',()=>{wasOpen=details.map(d=>d.open);details.forEach(d=>d.open=true)});
addEventListener('afterprint',()=>details.forEach((d,i)=>d.open=wasOpen[i]??false));
})();'''+'</script></body></html>'
    return page


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    try:
        html = render(json.loads(a.input.read_text(encoding='utf-8')))
    except (ValueError, KeyError, TypeError) as e:
        p.error(str(e))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(html, encoding='utf-8')
    print(a.output.resolve())


if __name__ == '__main__':
    main()
