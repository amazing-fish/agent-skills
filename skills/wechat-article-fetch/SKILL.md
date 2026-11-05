---
name: wechat-article-fetch
description: Fetch a public WeChat Official Account article from an mp.weixin.qq.com link into cached raw HTML and structured Markdown. Use when a user provides an mp.weixin.qq.com article URL and asks to fetch, extract, save, preserve, or prepare the article for downstream processing or knowledge capture.
---

# WeChat Article Fetch

Use this skill only as the data-acquisition layer for public WeChat Official Account articles. Do not summarize, classify, interpret, or archive the article into a knowledge base. Delegate those downstream responsibilities to `kb-capture` or another consuming skill.

## Fetch an article

Run the bundled script without a shell wrapper:

```text
python <skill-dir>/scripts/fetch_mp_article.py <url> [--assets] [--refresh] [--out <dir>]
```

- Omit `--out` to write under `%LOCALAPPDATA%\mp-article-cache\<sn>\`. Never redirect output into the current repository or another project directory.
- Add `--assets` only when local image files are needed. Otherwise preserve remote image URLs.
- Add `--refresh` only when the caller explicitly needs a fresh network copy. Normal calls reuse the cache.
- Treat stdout as a machine interface: parse its single JSON object. Treat stderr as diagnostic logging.
- On success, read `markdown_path` only when the downstream task needs article content. Use the other JSON fields for routing or provenance without reopening the Markdown unnecessarily.
- Read [references/output-contract.md](references/output-contract.md) when implementing or validating a downstream integration.

## Downstream calling pattern

1. Invoke `scripts/fetch_mp_article.py` as a subprocess without `shell=True`.
2. Capture stdout and stderr separately.
3. Parse stdout as one JSON object.
4. If `ok` is `true`, retain the returned provenance fields and read `markdown_path` as needed.
5. Pass the Markdown and provenance to `kb-capture` or another downstream skill for summarization, classification, or archival.
6. If `ok` is `false`, branch on `error_code`; do not infer article content from an error page or from stderr.

## Handle failures

| `error_code` | Meaning | Downstream action |
| --- | --- | --- |
| `NOT_MP_URL` | The input is not a supported HTTPS `mp.weixin.qq.com` article URL or has no safe `sn` cache key. | Give up for this input and ask for a valid HTTPS WeChat article link. Do not retry unchanged. |
| `DELETED` | The publisher deleted the article or the page explicitly reports deletion. | Give up. Ask for another authorized source or archived copy. |
| `NEEDS_VERIFY` | WeChat returned an environment, rate-limit, or verification page. | Do not treat the page as content. Retry later with backoff or ask the user to provide the article content; avoid rapid automatic retries. |
| `EXPIRED_LINK` | The link is invalid, expired, or reports a parameter error. | Give up for this URL and ask for a fresh article link. |
| `EMPTY_CONTENT` | No non-empty `div#js_content` article body was found. | Do not archive. Retry once with `--refresh` only if a transient page is plausible; otherwise request another source. |
| `NETWORK` | The request failed after bounded network retries or returned an unusable HTTP status. | Retry later. Preserve the same URL; use `--refresh` only when bypassing an existing valid cache is intentional. |
| `PARSE_FAILED` | The page or requested output could not satisfy the extraction contract. | Do not retry repeatedly. Preserve stderr and the error message, then escalate for parser maintenance or correct the output location. |

Never weaken these error boundaries to make a downstream capture succeed. In particular, never archive a deletion, verification, rate-limit, or parameter-error page as article text.
