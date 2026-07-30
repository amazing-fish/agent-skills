# Output contract

## Command

```text
python scripts/fetch_mp_article.py <url> [--assets] [--refresh] [--out <dir>]
```

The script requires Python 3.12, `requests`, and `lxml`. It introduces no other third-party dependencies and does not use a browser. Publish times use a fixed UTC+08:00 offset, so stock Windows Python does not need an external IANA timezone database.

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

The script rejects an explicit `--out` inside the current working directory or any output inside a detected Git worktree. The default `%LOCALAPPDATA%` cache remains valid when PowerShell starts in the user-profile directory, even though that directory is an ancestor of `%LOCALAPPDATA%`.

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

If `--assets` is added to a cache that does not already contain the requested images, image downloads may still make network requests. Image failures do not fail the article; they remain remote Markdown URLs and add strings to `warnings`. An HTTP 200 response with a known non-image `Content-Type` is an image failure and is never cached as an asset.

A successful article refresh invalidates the existing `assets/` directory before publishing the new `raw.html`, even when `--assets` is omitted. This prevents ordinal filenames from being reused for changed or reordered image URLs.

Deletion, verification, rate-limit, and expired-link markers are evaluated only when the expected article body is missing or empty, or when the HTML cannot be parsed. Marker phrases inside a non-empty `div#js_content` are article text, not error-page evidence.

Plain article text escapes Markdown control syntax before structural Markdown is emitted. Literal text such as `# heading`, `1. item`, `> quote`, or `---` therefore remains text instead of becoming a heading, list, blockquote, or thematic break; converter-generated headings, lists, links, and emphasis retain their intended structure.

JavaScript Unicode escapes in metadata are decoded before UTF-8 publication. Valid UTF-16 surrogate pairs become one supplementary Unicode character; isolated surrogate code points become the Unicode replacement character instead of making `article.md` unwritable.

Nested list rows are indented to the parent marker's content column. A table whose first row contains `<th>` cells uses that row as its GFM header; a `<td>`-only table receives an empty synthetic header so every source row remains data.
