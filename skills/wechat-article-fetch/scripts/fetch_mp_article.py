#!/usr/bin/env python3
"""Fetch a public WeChat Official Account article into a local cache."""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from zoneinfo import ZoneInfo

import requests
from lxml import etree
from lxml import html as lxml_html


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
TIMEOUT_SECONDS = 30
RETRY_DELAYS = (1, 2, 4)
SN_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")
ERROR_CODES = {
    "NOT_MP_URL",
    "DELETED",
    "NEEDS_VERIFY",
    "EXPIRED_LINK",
    "EMPTY_CONTENT",
    "NETWORK",
    "PARSE_FAILED",
}
PAGE_ERROR_MARKERS = (
    ("DELETED", ("该内容已被发布者删除", "内容已被删除")),
    (
        "NEEDS_VERIFY",
        (
            "环境异常",
            "访问过于频繁",
            "请进行验证",
            "请在微信客户端打开链接",
        ),
    ),
    ("EXPIRED_LINK", ("参数错误", "链接已过期", "链接已失效", "该链接已失效")),
)
SKIPPED_TAGS = {"script", "style", "noscript", "svg", "canvas"}
BLOCK_TAGS = {"article", "aside", "div", "main", "section"}


class FetchError(Exception):
    """A contract-level failure safe to expose to downstream callers."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Article:
    title: str
    account: str
    summary: str
    cover_url: str
    publish_timestamp: int
    publish_time: str
    char_count: int
    image_urls: list[str]
    content: Any


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a public mp.weixin.qq.com article into a local cache."
    )
    parser.add_argument("url", help="WeChat article URL")
    parser.add_argument(
        "--assets",
        action="store_true",
        help="Download body images into an assets directory.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Bypass a complete cache entry and fetch the article again.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Explicit output directory outside any project directory.",
    )
    return parser.parse_args(argv)


def parse_sn(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise FetchError("NOT_MP_URL", f"Invalid URL: {exc}") from exc

    if parsed.scheme not in {"http", "https"} or parsed.hostname != "mp.weixin.qq.com":
        raise FetchError(
            "NOT_MP_URL",
            "Expected an http(s) URL on mp.weixin.qq.com.",
        )

    path = parsed.path.rstrip("/")
    sn = ""
    if path.startswith("/s/"):
        sn = unquote(path.rsplit("/", 1)[-1])
    elif path == "/s":
        sn = parse_qs(parsed.query, keep_blank_values=True).get("sn", [""])[0]

    if not SN_PATTERN.fullmatch(sn):
        raise FetchError(
            "NOT_MP_URL",
            "The URL does not contain a safe supported article sn.",
        )
    return sn


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _inside_git_worktree(path: Path) -> bool:
    current = path
    while True:
        if (current / ".git").exists():
            return True
        if current.parent == current:
            return False
        current = current.parent


def choose_output_dir(sn: str, explicit_out: Path | None) -> Path:
    if explicit_out is None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = (
            Path(local_app_data)
            if local_app_data
            else Path.home() / "AppData" / "Local"
        )
        output_dir = base / "mp-article-cache" / sn
    else:
        output_dir = explicit_out.expanduser()

    output_dir = output_dir.resolve()
    cwd = Path.cwd().resolve()
    if _is_relative_to(output_dir, cwd) or _inside_git_worktree(output_dir):
        raise FetchError(
            "PARSE_FAILED",
            "Refusing to write article output inside the current workspace or a Git worktree.",
        )
    return output_dir


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        }
    )
    return session


def request_with_retries(
    session: requests.Session,
    url: str,
    *,
    stream: bool = False,
) -> requests.Response:
    last_message = "network request failed"
    attempts = len(RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            response = session.get(
                url,
                timeout=TIMEOUT_SECONDS,
                allow_redirects=True,
                stream=stream,
            )
        except requests.RequestException as exc:
            last_message = str(exc)
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            raise FetchError(
                "NETWORK",
                f"Network request failed after {attempts} attempts: {last_message}",
            ) from exc

        if 500 <= response.status_code <= 599:
            last_message = f"HTTP {response.status_code}"
            response.close()
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            raise FetchError(
                "NETWORK",
                f"Network request failed after {attempts} attempts: {last_message}",
            )
        return response

    raise FetchError("NETWORK", last_message)


def fetch_html(session: requests.Session, url: str) -> bytes:
    response = request_with_retries(session, url)
    try:
        if response.status_code in {404, 410}:
            raise FetchError("EXPIRED_LINK", f"Article URL returned HTTP {response.status_code}.")
        if response.status_code in {403, 429}:
            raise FetchError("NEEDS_VERIFY", f"WeChat returned HTTP {response.status_code}.")
        if response.status_code != 200:
            raise FetchError(
                "NETWORK",
                f"Article request returned HTTP {response.status_code}.",
            )
        return response.content
    finally:
        response.close()


def detect_page_error(raw_html: bytes) -> None:
    text = html_lib.unescape(raw_html.decode("utf-8", errors="replace"))
    for code, markers in PAGE_ERROR_MARKERS:
        for marker in markers:
            if marker in text:
                raise FetchError(code, f"WeChat page reported: {marker}")


def _meta_content(document: Any, property_name: str) -> str:
    values = document.xpath(
        "//meta[@property=$name]/@content",
        name=property_name,
    )
    if not values:
        return ""
    return str(values[0]).strip()


def _decode_js_string(value: str) -> str:
    value = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        value,
    )
    value = re.sub(
        r"\\x([0-9a-fA-F]{2})",
        lambda match: chr(int(match.group(1), 16)),
        value,
    )
    escapes = {
        r"\\": "\\",
        r"\/": "/",
        r"\"": '"',
        r"\'": "'",
        r"\n": "\n",
        r"\r": "\r",
        r"\t": "\t",
        r"\b": "\b",
        r"\f": "\f",
    }
    for escaped, replacement in escapes.items():
        value = value.replace(escaped, replacement)
    return html_lib.unescape(value).strip()


def _extract_account(source: str) -> str:
    match = re.search(
        r"\bvar\s+nickname\s*=\s*htmlDecode\(\s*([\"'])(.*?)\1\s*\)",
        source,
        flags=re.DOTALL,
    )
    return _decode_js_string(match.group(2)) if match else ""


def _extract_timestamp(source: str) -> int | None:
    match = re.search(r"\bvar\s+ct\s*=\s*[\"'](\d{9,12})[\"']", source)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _normalize_image_url(value: str) -> str:
    value = value.strip()
    if value.startswith("//"):
        return f"https:{value}"
    return value


def parse_article(raw_html: bytes) -> Article:
    detect_page_error(raw_html)
    source = raw_html.decode("utf-8", errors="replace")
    try:
        document = lxml_html.fromstring(raw_html)
    except (etree.ParserError, ValueError) as exc:
        raise FetchError("PARSE_FAILED", f"Could not parse article HTML: {exc}") from exc

    contents = document.xpath("//div[@id='js_content']")
    if not contents:
        raise FetchError("EMPTY_CONTENT", "No div#js_content article body was found.")
    content = contents[0]
    visible_text = content.text_content()
    char_count = len(re.sub(r"\s+", "", visible_text))
    if char_count == 0:
        raise FetchError("EMPTY_CONTENT", "The div#js_content article body is empty.")

    title = _meta_content(document, "og:title")
    if not title:
        title_values = document.xpath(
            "//h1[@id='activity-name']//*[contains("
            "concat(' ', normalize-space(@class), ' '), ' js_title_inner ')]//text()"
        )
        title = "".join(str(value) for value in title_values).strip()

    account = _extract_account(source)
    timestamp = _extract_timestamp(source)
    missing = [
        name
        for name, value in (
            ("title", title),
            ("account", account),
            ("publish timestamp", timestamp),
        )
        if not value
    ]
    if missing:
        raise FetchError(
            "PARSE_FAILED",
            f"Missing required article metadata: {', '.join(missing)}.",
        )

    try:
        publish_time = datetime.fromtimestamp(
            int(timestamp),
            tz=ZoneInfo("Asia/Shanghai"),
        ).isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError) as exc:
        raise FetchError("PARSE_FAILED", f"Invalid publish timestamp: {timestamp}.") from exc

    image_urls: list[str] = []
    for image in content.xpath(".//img"):
        value = _normalize_image_url(str(image.get("data-src") or ""))
        if value:
            image_urls.append(value)

    return Article(
        title=title,
        account=account,
        summary=_meta_content(document, "og:description"),
        cover_url=_meta_content(document, "og:image"),
        publish_timestamp=int(timestamp),
        publish_time=publish_time,
        char_count=char_count,
        image_urls=image_urls,
        content=content,
    )


def _tag_name(node: Any) -> str:
    tag = node.tag
    if not isinstance(tag, str):
        return ""
    tag = tag.rsplit("}", 1)[-1].lower()
    return tag.rsplit(":", 1)[-1]


def _plain_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\xa0", " "))


class MarkdownConverter:
    """Small, purpose-built converter for common WeChat article markup."""

    def __init__(self, asset_map: dict[str, str]) -> None:
        self.asset_map = asset_map

    def convert(self, root: Any) -> str:
        rendered = self._render_children(root)
        return self._cleanup(rendered)

    def _render_children(self, node: Any) -> str:
        pieces = [_plain_text(node.text)]
        for child in node:
            pieces.append(self._render_node(child))
            pieces.append(_plain_text(child.tail))
        return "".join(pieces)

    def _render_node(self, node: Any) -> str:
        tag = _tag_name(node)
        if not tag or tag in SKIPPED_TAGS:
            return ""
        if tag == "img":
            return self._render_image(node)
        if tag == "br":
            return "\ue000BR\ue001"
        if tag == "hr":
            return "\n\n---\n\n"
        if tag == "pre":
            return self._render_pre(node)
        if tag == "table":
            return self._render_table(node)
        if tag in {"ul", "ol"}:
            return self._render_list(node, ordered=tag == "ol")

        content = self._render_children(node)
        stripped = content.strip()
        if tag in {"h1", "h2", "h3", "h4"}:
            level = int(tag[1])
            return f"\n\n{'#' * level} {stripped}\n\n" if stripped else ""
        if tag == "p":
            return f"\n\n{stripped}\n\n" if stripped else "\n\n"
        if tag in BLOCK_TAGS:
            return f"\n\n{stripped}\n\n" if stripped else ""
        if tag in {"strong", "b"}:
            return f"**{stripped}**" if stripped else ""
        if tag in {"em", "i"}:
            return f"*{stripped}*" if stripped else ""
        if tag == "blockquote":
            lines = stripped.splitlines()
            quoted = "\n".join(f"> {line}" if line else ">" for line in lines)
            return f"\n\n{quoted}\n\n" if quoted else ""
        if tag == "a":
            href = str(node.get("href") or "").strip()
            if not href:
                return content
            label = stripped or href
            return f"[{label}]({href})"
        if tag == "code":
            return self._render_inline_code(node)
        if tag == "li":
            return stripped
        return content

    def _render_image(self, node: Any) -> str:
        source = _normalize_image_url(str(node.get("data-src") or ""))
        if not source:
            return ""
        target = self.asset_map.get(source, source)
        alt = _plain_text(str(node.get("alt") or "")).strip().replace("]", r"\]")
        return f"\n\n![{alt}]({target})\n\n"

    def _render_pre(self, node: Any) -> str:
        code = "".join(node.itertext()).replace("\r\n", "\n").replace("\r", "\n")
        code = code.strip("\n")
        language = ""
        code_nodes = node.xpath(".//code[1]")
        if code_nodes:
            class_name = str(code_nodes[0].get("class") or "")
            match = re.search(r"(?:language-|lang-)([A-Za-z0-9_+-]+)", class_name)
            if match:
                language = match.group(1)
        max_run = max((len(run) for run in re.findall(r"`+", code)), default=0)
        fence = "`" * max(3, max_run + 1)
        return f"\n\n{fence}{language}\n{code}\n{fence}\n\n"

    def _render_inline_code(self, node: Any) -> str:
        code = "".join(node.itertext()).strip()
        if not code:
            return ""
        max_run = max((len(run) for run in re.findall(r"`+", code)), default=0)
        fence = "`" * max(1, max_run + 1)
        padding = " " if code.startswith("`") or code.endswith("`") else ""
        return f"{fence}{padding}{code}{padding}{fence}"

    def _render_list(self, node: Any, *, ordered: bool) -> str:
        rows: list[str] = []
        items = [child for child in node if _tag_name(child) == "li"]
        for index, item in enumerate(items, start=1):
            body_parts = [_plain_text(item.text)]
            nested_parts: list[str] = []
            for child in item:
                child_tag = _tag_name(child)
                if child_tag in {"ul", "ol"}:
                    nested_parts.append(
                        self._render_list(child, ordered=child_tag == "ol").strip("\n")
                    )
                else:
                    body_parts.append(self._render_node(child))
                body_parts.append(_plain_text(child.tail))
            body = self._cleanup("".join(body_parts)).strip()
            marker = f"{index}. " if ordered else "- "
            body_lines = body.splitlines() or [""]
            rows.append(marker + body_lines[0])
            rows.extend("  " + line for line in body_lines[1:])
            for nested in nested_parts:
                rows.extend("  " + line for line in nested.splitlines())
        rendered_rows = "\n".join(rows)
        return f"\n\n{rendered_rows}\n\n" if rows else ""

    def _render_table(self, node: Any) -> str:
        rows: list[tuple[list[str], bool]] = []
        for row in node.xpath(".//tr"):
            cells = [
                cell
                for cell in row
                if _tag_name(cell) in {"th", "td"}
            ]
            if not cells:
                continue
            values: list[str] = []
            for cell in cells:
                value = self._render_children(cell)
                value = self._cleanup(value).strip().replace("|", r"\|")
                value = re.sub(r"\s*\n\s*", "<br>", value)
                values.append(value)
            rows.append((values, any(_tag_name(cell) == "th" for cell in cells)))
        if not rows:
            return ""

        width = max(len(values) for values, _ in rows)
        normalized = [values + [""] * (width - len(values)) for values, _ in rows]
        header = normalized[0]
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in range(width)) + " |",
        ]
        lines.extend("| " + " | ".join(values) + " |" for values in normalized[1:])
        rendered_lines = "\n".join(lines)
        return f"\n\n{rendered_lines}\n\n"

    def _cleanup(self, markdown: str) -> str:
        markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
        markdown = markdown.replace("\ue000BR\ue001", "  \n")
        cleaned: list[str] = []
        blank = False
        in_fence = False
        fence_marker = ""
        for raw_line in markdown.splitlines():
            stripped = raw_line.strip()
            fence_match = re.match(r"^(`{3,})(?:[^`]*)$", stripped)
            if fence_match:
                marker = fence_match.group(1)
                if not in_fence:
                    in_fence = True
                    fence_marker = marker
                elif marker.startswith(fence_marker):
                    in_fence = False
                    fence_marker = ""
                cleaned.append(raw_line.rstrip())
                blank = False
                continue
            if in_fence:
                cleaned.append(raw_line.rstrip())
                continue

            line = raw_line.rstrip()
            if not line.strip():
                if cleaned and not blank:
                    cleaned.append("")
                blank = True
                continue
            if not re.match(r"^\s*(?:[-*+] |\d+\. |>|```|\|)", line):
                line = line.strip()
            cleaned.append(line)
            blank = False
        return "\n".join(cleaned).strip()


def _image_extension(response: requests.Response, url: str) -> str:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    by_type = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/bmp": ".bmp",
    }
    if content_type in by_type:
        return by_type[content_type]
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".img"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def download_assets(
    session: requests.Session,
    image_urls: list[str],
    assets_dir: Path,
    *,
    reuse_existing: bool,
) -> tuple[dict[str, str], list[str]]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_map: dict[str, str] = {}
    warnings: list[str] = []
    unique_urls = list(dict.fromkeys(image_urls))
    for index, url in enumerate(unique_urls, start=1):
        if reuse_existing:
            existing = [
                path
                for path in assets_dir.glob(f"{index:03d}.*")
                if path.is_file() and path.stat().st_size > 0
            ]
            if len(existing) == 1:
                asset_map[url] = f"assets/{existing[0].name}"
                continue

        response: requests.Response | None = None
        try:
            response = request_with_retries(session, url, stream=True)
            if response.status_code != 200:
                raise FetchError(
                    "NETWORK",
                    f"Image request returned HTTP {response.status_code}.",
                )
            extension = _image_extension(response, url)
            destination = assets_dir / f"{index:03d}{extension}"
            atomic_write_bytes(destination, response.content)
            asset_map[url] = f"assets/{destination.name}"
        except (FetchError, requests.RequestException, OSError) as exc:
            warnings.append(f"Image download failed: {url} ({exc})")
        finally:
            if response is not None:
                response.close()
    return asset_map, warnings


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def render_article_markdown(
    article: Article,
    result: dict[str, Any],
    source_url: str,
    asset_map: dict[str, str],
) -> str:
    frontmatter_fields = (
        "ok",
        "url",
        "sn",
        "title",
        "account",
        "summary",
        "cover_url",
        "publish_timestamp",
        "publish_time",
        "char_count",
        "image_count",
        "cached",
        "warnings",
    )
    lines = ["---"]
    for key in frontmatter_fields:
        lines.append(f"{key}: {_yaml_scalar(result[key])}")
        if key == "url":
            lines.append(f"source_url: {_yaml_scalar(source_url)}")
    lines.append("---")
    body = MarkdownConverter(asset_map).convert(article.content)
    lines.extend(["", body, "", f"原文链接：{source_url}", ""])
    return "\n".join(lines)


def build_success(
    *,
    url: str,
    sn: str,
    article: Article,
    markdown_path: Path,
    raw_html_path: Path,
    assets_dir: Path | None,
    cached: bool,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "ok": True,
        "url": url,
        "sn": sn,
        "title": article.title,
        "account": article.account,
        "summary": article.summary,
        "cover_url": article.cover_url,
        "publish_timestamp": article.publish_timestamp,
        "publish_time": article.publish_time,
        "char_count": article.char_count,
        "image_count": len(article.image_urls),
        "markdown_path": str(markdown_path),
        "raw_html_path": str(raw_html_path),
        "assets_dir": str(assets_dir) if assets_dir is not None else None,
        "cached": cached,
        "warnings": warnings,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    original_url = args.url
    sn = parse_sn(original_url)
    output_dir = choose_output_dir(sn, args.out)
    raw_html_path = output_dir / "raw.html"
    markdown_path = output_dir / "article.md"
    cache_hit = (
        not args.refresh
        and raw_html_path.is_file()
        and markdown_path.is_file()
    )

    session: requests.Session | None = None
    if cache_hit:
        try:
            raw_html = raw_html_path.read_bytes()
        except OSError as exc:
            raise FetchError("PARSE_FAILED", f"Could not read cached HTML: {exc}") from exc
    else:
        session = make_session()
        raw_html = fetch_html(session, original_url)

    article = parse_article(raw_html)
    if not cache_hit:
        try:
            atomic_write_bytes(raw_html_path, raw_html)
        except OSError as exc:
            raise FetchError("PARSE_FAILED", f"Could not write raw HTML: {exc}") from exc

    assets_dir: Path | None = None
    asset_map: dict[str, str] = {}
    warnings: list[str] = []
    if args.assets:
        assets_dir = output_dir / "assets"
        if session is None:
            session = make_session()
        asset_map, warnings = download_assets(
            session,
            article.image_urls,
            assets_dir,
            reuse_existing=cache_hit,
        )

    result = build_success(
        url=original_url,
        sn=sn,
        article=article,
        markdown_path=markdown_path,
        raw_html_path=raw_html_path,
        assets_dir=assets_dir,
        cached=cache_hit,
        warnings=warnings,
    )
    markdown = render_article_markdown(
        article,
        result,
        original_url,
        asset_map,
    )
    try:
        atomic_write_text(markdown_path, markdown)
    except OSError as exc:
        raise FetchError("PARSE_FAILED", f"Could not write Markdown: {exc}") from exc
    finally:
        if session is not None:
            session.close()
    return result


def emit_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        emit_json(run(args))
        return 0
    except FetchError as exc:
        emit_json(
            {
                "ok": False,
                "error_code": exc.code,
                "message": exc.message,
                "url": args.url,
            }
        )
        return 1
    except Exception as exc:
        print(f"Unexpected parser failure: {exc}", file=sys.stderr)
        emit_json(
            {
                "ok": False,
                "error_code": "PARSE_FAILED",
                "message": str(exc),
                "url": args.url,
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
