#!/usr/bin/env python3
"""Inline shared light/dark and location-copy controls into a local HTML report."""
from __future__ import annotations
import argparse
from html import escape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

ROOT = Path(__file__).resolve().parents[1]
HEAD_START = '<!-- report-for-human:controls:start -->'
HEAD_END = '<!-- report-for-human:controls:end -->'
TOOLS_START = '<!-- report-for-human:tools:start -->'
TOOLS_END = '<!-- report-for-human:tools:end -->'


class SourcePathMeta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.values = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name', '').lower() == 'report-source-path':
            self.tags.append(self.get_starttag_text())
            self.values.append(attrs.get('content', ''))

    handle_startendtag = handle_starttag


def normalized_source_path(source_path: str | Path) -> str:
    value = str(source_path).strip()
    if not value or '\x00' in value or '\n' in value or '\r' in value:
        raise ValueError('Report source path must be an absolute local filesystem path')
    if PureWindowsPath(value).is_absolute():
        return str(PureWindowsPath(value))
    if PurePosixPath(value).is_absolute():
        return str(PurePosixPath(value))
    raise ValueError('Report source path must be an absolute local filesystem path, not a preview URL')


def enhance_report(html: str, source_path: str | Path | None = None) -> str:
    existing = SourcePathMeta()
    existing.feed(html)
    if source_path is None and existing.values:
        if len(set(existing.values)) != 1:
            raise ValueError('Conflicting report source paths; provide the actual output path')
        source_path = existing.values[0]
    source_path = normalized_source_path(source_path) if source_path is not None else None
    for tag in existing.tags:
        html = html.replace(tag, '')
    for start, end in [(HEAD_START, HEAD_END), (TOOLS_START, TOOLS_END)]:
        html = re.sub(re.escape(start) + r'.*?' + re.escape(end), '', html, flags=re.S)
    if not all(re.search(pattern, html, re.I) for pattern in [r'<html\b', r'</head\s*>', r'<body\b']):
        raise ValueError('Expected a complete HTML report')
    def light_root(match):
        attrs = re.sub(r'\sdata-report-theme\s*=\s*(["\']).*?\1', '', match[0], flags=re.I)
        return attrs[:-1] + ' data-report-theme="light">'
    html = re.sub(r'<html\b[^>]*>', light_root, html, count=1, flags=re.I)
    css = (ROOT/'assets/report-controls.css').read_text(encoding='utf-8')
    js = (ROOT/'assets/report-controls.js').read_text(encoding='utf-8')
    source_meta = '<meta name="report-source-path" content="' + escape(source_path, quote=True) + '">' if source_path else ''
    head = HEAD_START + source_meta + '<style id="rfh-controls-css">' + css + '</style><script id="rfh-controls-js">' + js + '</script>' + HEAD_END
    html = re.sub(r'</head\s*>', lambda m: head + m[0], html, count=1, flags=re.I)
    toolbar = TOOLS_START + '''<div class="rfh-toolbar" data-rfh-toolbar role="group" aria-label="报告阅读工具">
<label class="rfh-theme-choice">主题<select data-rfh-theme-toggle aria-label="报告主题" disabled><option value="system">跟随系统</option><option value="light" selected>浅色</option><option value="dark">深色</option></select></label>
<button type="button" data-rfh-copy-path disabled>复制文件位置</button>
<span data-rfh-status role="status" aria-live="polite"></span>
<label class="rfh-manual-path" data-rfh-manual hidden>文件或页面位置<input data-rfh-manual-path readonly aria-label="文件或页面位置"></label>
<noscript>阅读工具需要 JavaScript；报告正文仍可阅读和打印。</noscript>
</div>''' + TOOLS_END
    anchor = r'<main\b[^>]*>' if re.search(r'<main\b', html, re.I) else r'<body\b[^>]*>'
    return re.sub(anchor, lambda m: m[0] + toolbar, html, count=1, flags=re.I)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--source-path', help='Actual local report path, when different from the execution-host output path')
    args = parser.parse_args()
    target = args.output or args.input
    try:
        html = enhance_report(args.input.read_text(encoding='utf-8'), source_path=args.source_path or target.resolve())
    except ValueError as e:
        parser.error(str(e))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding='utf-8')
    print(target.resolve())


if __name__ == '__main__':
    main()
