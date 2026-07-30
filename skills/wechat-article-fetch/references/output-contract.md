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

Only HTTPS article URLs on `mp.weixin.qq.com` are accepted. URL credentials and ports other than 443 are rejected. `sn` is the final path segment for short links such as `/s/<sn>`, or the `sn` query value for `/s?__biz=...&sn=<sn>`.

Successful output contains:

- `article.md`: YAML frontmatter followed by Markdown article content and a final `原文链接：<url>` provenance line.
- `raw.html`: exact response bytes used for parsing. This file is never written to stdout.
- `assets/`: created only when `--assets` is requested. Successfully downloaded body images are referenced with relative POSIX-style paths from `article.md`.

An article body is non-empty when it contains visible text or at least one image URL. Body images prefer `data-src` and fall back to `src`, preserving image-only and non-lazy-loaded articles.

The script rejects an explicit `--out` inside the current working directory or any output inside a detected Git worktree. The default `%LOCALAPPDATA%` cache remains valid when PowerShell starts in the user-profile directory, even though that directory is an ancestor of `%LOCALAPPDATA%`.

## Stdout

Stdout contains exactly one UTF-8 JSON object and a trailing newline. It is written as UTF-8 bytes through the binary stdout stream so Windows legacy text encodings cannot corrupt or reject metadata. Diagnostics belong on stderr.

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

Article requests use the same fail-closed destination policy on the initial URL and every redirect target: HTTPS on port 443, no URL credentials, the exact trusted host `mp.weixin.qq.com`, and no private, loopback, link-local, reserved, or otherwise non-public DNS results. Redirects are followed manually, with a maximum of five. The documented Windows tunnel-adapter exception for synthetic `198.18.0.0/15` addresses applies only to the exact trusted hostname and retains HTTPS certificate verification.

Article response bodies are streamed in 64 KiB chunks with a 30-second read deadline and a 10 MiB decoded-body limit, including when `Content-Length` is absent or incorrect. A dedicated deadline watchdog shuts down the active transport socket before closing the response, so a body read blocked while waiting to fill its next chunk cannot extend the deadline indefinitely. A larger or overdue response fails with `NETWORK` before `raw.html` is published.

If `--assets` is added to a cache that does not already contain the requested images, image downloads may still make network requests. Each request must use a public HTTPS destination on port 443 with no URL credentials and the trusted WeChat CDN host `mmbiz.qpic.cn`. DNS results are rejected if any resolved address is loopback, private, link-local, reserved, or otherwise non-public. The `198.18.0.0/15` network-benchmark range is accepted only for that exact trusted hostname because Windows tunnel adapters commonly expose public destinations through synthetic addresses in this range; HTTPS certificate verification still binds the connection to the CDN hostname. Automatic redirects are disabled, and every redirect target is resolved and validated under the same policy before the next request. At most five redirects are followed.

Image bodies use the same 30-second read deadline, are streamed in bounded chunks, and are limited to 20 MiB per response, including when `Content-Length` is absent or incorrect. Image failures do not fail the article; they remain remote Markdown URLs and add strings to `warnings`. An HTTP 200 response with a known non-image `Content-Type` is an image failure and is never cached as an asset. An empty image payload is an image failure under the same rule. An oversized payload is also rejected without writing a partial asset.

A successful article refresh invalidates the existing `assets/` directory before publishing the new `raw.html`, even when `--assets` is omitted. This prevents ordinal filenames from being reused for changed or reordered image URLs.

Deletion, verification, rate-limit, and expired-link markers are evaluated only when the expected article body is missing or empty, or when the HTML cannot be parsed. Marker phrases inside a non-empty `div#js_content` are article text, not error-page evidence. Skipped subtrees do not contribute text or images to the emptiness predicate or output counts.

Plain article text escapes Markdown control syntax before structural Markdown is emitted. Literal text such as `# heading`, `1. item`, `> quote`, `---`, `~~~`, or `~~text~~` therefore remains text instead of becoming a heading, list, blockquote, thematic break, code fence, or strikethrough; converter-generated headings, lists, links, and emphasis retain their intended structure.

Markdown link and image destinations percent-encode whitespace, parentheses, square brackets, angle brackets, quotes, backslashes, and other syntax-breaking characters while preserving URL separators and existing percent escapes. This applies to labeled links, empty-label link fallbacks, remote image URLs, and downloaded relative asset paths.

JavaScript Unicode escapes in metadata are decoded before UTF-8 publication. Valid UTF-16 surrogate pairs become one supplementary Unicode character; isolated surrogate code points become the Unicode replacement character instead of making `article.md` unwritable.

Inline emphasis, links, and code preserve boundary whitespace outside their Markdown delimiters. Fenced code preserves trailing spaces and tabs inside the fence. Nested lists remain at their source position inside a list item. Nested list rows are indented to the parent marker's content column, as are continuation paragraphs. Ordered lists preserve `<ol start>` and `<li value>` numbering. A table whose first row contains `<th>` cells uses that row as its GFM header; a `<td>`-only table receives an empty synthetic header so every source row remains data. Table spans are bounded to 128 logical columns: `colspan` cells expand across their logical columns, and `rowspan` reserves occupied columns in following rows. Nested table rows stay within the cell that owns the nested table and are not emitted again as outer rows.
