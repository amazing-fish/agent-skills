# Output contract

## Command

```text
python scripts/fetch_mp_article.py <url> [--assets] [--refresh] [--out <dir>]
```

The script requires Python 3.12, `requests`, and `lxml`. It introduces no other third-party dependencies and does not use a browser.

## Storage

The default output directory is:

```text
%LOCALAPPDATA%\mp-article-cache\<sn>\
```

`sn` is the final path segment for short links such as `/s/<sn>`, or the `sn` query value for `/s?__biz=...&sn=<sn>`.

Successful output contains:

- `article.md`: YAML frontmatter followed by Markdown article content and a final `原文链接：<url>` provenance line.
- `raw.html`: exact response bytes used for parsing. This file is never written to stdout.
- `assets/`: created only when `--assets` is requested. Successfully downloaded body images are referenced with relative POSIX-style paths from `article.md`.

The script rejects an explicit `--out` inside the current working directory or a detected Git worktree.

## Stdout

Stdout contains exactly one UTF-8 JSON object and a trailing newline. Diagnostics belong on stderr.

Success schema:

```json
{
  "ok": true,
  "url": "<original input>",
  "sn": "<validated cache key>",
  "title": "<article title>",
  "account": "<official account name>",
  "summary": "<og:description or empty string>",
  "cover_url": "<og:image or empty string>",
  "publish_timestamp": 1785311401,
  "publish_time": "2026-07-29T15:50:01+08:00",
  "char_count": 15250,
  "image_count": 11,
  "markdown_path": "C:\\...\\article.md",
  "raw_html_path": "C:\\...\\raw.html",
  "assets_dir": null,
  "cached": false,
  "warnings": []
}
```

Failure schema:

```json
{
  "ok": false,
  "error_code": "NOT_MP_URL",
  "message": "<human-readable explanation>",
  "url": "<original input>"
}
```

Failures use a non-zero process exit code. `error_code` is one of:

```text
NOT_MP_URL
DELETED
NEEDS_VERIFY
EXPIRED_LINK
EMPTY_CONTENT
NETWORK
PARSE_FAILED
```

## Frontmatter

`article.md` frontmatter contains the success metadata using the same field names and values, except the path fields `markdown_path`, `raw_html_path`, and `assets_dir`. It also contains `source_url`, equal to the original input URL. JSON-compatible scalars and arrays are used so the block remains valid YAML.

Example:

```yaml
---
ok: true
url: "https://mp.weixin.qq.com/s/example"
source_url: "https://mp.weixin.qq.com/s/example"
sn: "example"
title: "Example"
account: "Example Account"
summary: ""
cover_url: ""
publish_timestamp: 1785311401
publish_time: "2026-07-29T15:50:01+08:00"
char_count: 15250
image_count: 11
cached: false
warnings: []
---
```

## Cache semantics

A normal call is a cache hit only when both `raw.html` and `article.md` exist. The parser reuses `raw.html`, emits `cached: true`, and performs no article network request. `--refresh` bypasses the cache.

If `--assets` is added to a cache that does not already contain the requested images, image downloads may still make network requests. Image failures do not fail the article; they remain remote Markdown URLs and add strings to `warnings`.
