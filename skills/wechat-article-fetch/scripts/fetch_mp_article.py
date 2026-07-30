#!/usr/bin/env python3
"""Fetch a public WeChat Official Account article into a local cache."""

from __future__ import annotations

import argparse
import html as html_lib
import ipaddress
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

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
MAX_ARTICLE_BYTES = 10 * 1024 * 1024
ARTICLE_CHUNK_BYTES = 64 * 1024
MAX_ARTICLE_REDIRECTS = 5
TRUSTED_ARTICLE_HOSTS = frozenset({"mp.weixin.qq.com"})
MAX_ASSET_BYTES = 20 * 1024 * 1024
ASSET_CHUNK_BYTES = 64 * 1024
MAX_ASSET_REDIRECTS = 5
TRUSTED_ASSET_HOSTS = frozenset({"mmbiz.qpic.cn", "mp.weixin.qq.com"})
TUNNEL_FAKE_IP_RANGE = ipaddress.ip_network("198.18.0.0/15")
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MARKDOWN_DESTINATION_SAFE = ":/?#@!$&'*+,;=%-._~"
CHINA_STANDARD_TIME = timezone(timedelta(hours=8), name="Asia/Shanghai")
MAX_TABLE_COLUMNS = 128
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
        port = parsed.port
    except ValueError as exc:
        raise FetchError("NOT_MP_URL", f"Invalid URL: {exc}") from exc

    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != "mp.weixin.qq.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise FetchError(
            "NOT_MP_URL",
            "Expected an HTTPS URL on mp.weixin.qq.com without credentials.",
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
    if (
        explicit_out is not None
        and _is_relative_to(output_dir, cwd)
    ) or _inside_git_worktree(output_dir):
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
                allow_redirects=False,
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


def _validate_trusted_public_url(
    url: str,
    *,
    trusted_hosts: frozenset[str],
    label: str,
    host_description: str,
) -> None:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise FetchError("NETWORK", f"Invalid image URL: {exc}") from exc

    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise FetchError(
            "NETWORK",
            f"{label.capitalize()} URL must use HTTPS on the public Internet "
            "without credentials.",
        )

    hostname = hostname.lower()
    if hostname not in trusted_hosts:
        raise FetchError(
            "NETWORK",
            f"Refusing {label} destination outside {host_description}: {hostname}.",
        )

    try:
        addresses = {
            entry[4][0].split("%", 1)[0]
            for entry in socket.getaddrinfo(
                hostname,
                port or 443,
                type=socket.SOCK_STREAM,
            )
        }
    except OSError as exc:
        raise FetchError(
            "NETWORK",
            f"Could not resolve {label} host {hostname}: {exc}",
        ) from exc

    if not addresses:
        raise FetchError(
            "NETWORK",
            f"{label.capitalize()} host {hostname} resolved to no addresses.",
        )

    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise FetchError(
                "NETWORK",
                f"{label.capitalize()} host {hostname} resolved to an invalid address.",
            ) from exc
        if not (
            parsed_address.is_global
            or (
                parsed_address.version == 4
                and parsed_address in TUNNEL_FAKE_IP_RANGE
            )
        ):
            raise FetchError(
                "NETWORK",
                f"Refusing non-public {label} destination {hostname} ({address}).",
            )


def _validate_public_asset_url(url: str) -> None:
    _validate_trusted_public_url(
        url,
        trusted_hosts=TRUSTED_ASSET_HOSTS,
        label="image",
        host_description="a trusted WeChat image host",
    )


def _validate_public_article_url(url: str) -> None:
    _validate_trusted_public_url(
        url,
        trusted_hosts=TRUSTED_ARTICLE_HOSTS,
        label="article",
        host_description="the trusted WeChat article host",
    )


def _request_with_validated_redirects(
    session: requests.Session,
    url: str,
    *,
    validate_url: Callable[[str], None],
    max_redirects: int,
    label: str,
) -> tuple[requests.Response, str]:
    current_url = url
    for redirect_count in range(max_redirects + 1):
        validate_url(current_url)
        response = request_with_retries(
            session,
            current_url,
            stream=True,
        )
        if response.status_code not in REDIRECT_STATUSES:
            return response, current_url

        location = response.headers.get("Location", "").strip()
        response.close()
        if not location:
            raise FetchError(
                "NETWORK",
                f"{label.capitalize()} redirect response did not include "
                "a Location header.",
            )
        if redirect_count == max_redirects:
            raise FetchError(
                "NETWORK",
                f"{label.capitalize()} request exceeded {max_redirects} redirects.",
            )
        current_url = urljoin(current_url, location)

    raise FetchError(
        "NETWORK",
        f"{label.capitalize()} request exceeded the redirect limit.",
    )


def _request_asset_with_retries(
    session: requests.Session,
    url: str,
) -> tuple[requests.Response, str]:
    return _request_with_validated_redirects(
        session,
        url,
        validate_url=_validate_public_asset_url,
        max_redirects=MAX_ASSET_REDIRECTS,
        label="image",
    )


def _request_article_with_retries(
    session: requests.Session,
    url: str,
) -> tuple[requests.Response, str]:
    return _request_with_validated_redirects(
        session,
        url,
        validate_url=_validate_public_article_url,
        max_redirects=MAX_ARTICLE_REDIRECTS,
        label="article",
    )


def _read_bounded_response(
    response: requests.Response,
    *,
    max_bytes: int,
    chunk_bytes: int,
    label: str,
    require_content: bool,
) -> bytes:
    raw_length = response.headers.get("Content-Length", "").strip()
    if raw_length:
        try:
            declared_length = int(raw_length)
        except ValueError:
            declared_length = -1
        if declared_length > max_bytes:
            raise FetchError(
                "NETWORK",
                f"{label.capitalize()} response exceeds the {max_bytes}-byte limit.",
            )

    deadline_expired = threading.Event()

    def expire_response() -> None:
        deadline_expired.set()
        raw_response = getattr(response, "raw", None)
        connection = getattr(raw_response, "_connection", None)
        connection_socket = getattr(connection, "sock", None)
        http_response = getattr(raw_response, "_fp", None)
        buffered_reader = getattr(http_response, "fp", None)
        socket_io = getattr(buffered_reader, "raw", None)
        file_socket = getattr(socket_io, "_sock", None)
        closed_socket_ids: set[int] = set()
        for active_socket in (connection_socket, file_socket):
            if active_socket is None or id(active_socket) in closed_socket_ids:
                continue
            closed_socket_ids.add(id(active_socket))
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except (OSError, ValueError):
                pass
            try:
                active_socket.close()
            except OSError:
                pass
        try:
            response.close()
        except Exception:
            # The deadline event remains authoritative if wrapper cleanup fails.
            pass

    deadline_timer = threading.Timer(TIMEOUT_SECONDS, expire_response)
    deadline_timer.daemon = True
    deadline_timer.start()
    payload = bytearray()
    try:
        if deadline_expired.is_set():
            raise FetchError(
                "NETWORK",
                f"{label.capitalize()} response exceeded the "
                f"{TIMEOUT_SECONDS}-second read deadline.",
            )
        try:
            for chunk in response.iter_content(chunk_size=chunk_bytes):
                if deadline_expired.is_set():
                    raise FetchError(
                        "NETWORK",
                        f"{label.capitalize()} response exceeded the "
                        f"{TIMEOUT_SECONDS}-second read deadline.",
                    )
                if not chunk:
                    continue
                if not isinstance(chunk, bytes):
                    raise FetchError(
                        "NETWORK",
                        f"{label.capitalize()} response yielded a non-byte chunk.",
                    )
                if len(payload) + len(chunk) > max_bytes:
                    raise FetchError(
                        "NETWORK",
                        f"{label.capitalize()} response exceeds the "
                        f"{max_bytes}-byte limit.",
                    )
                payload.extend(chunk)
        except requests.RequestException as exc:
            if deadline_expired.is_set():
                raise FetchError(
                    "NETWORK",
                    f"{label.capitalize()} response exceeded the "
                    f"{TIMEOUT_SECONDS}-second read deadline.",
                ) from exc
            raise
        if deadline_expired.is_set():
            raise FetchError(
                "NETWORK",
                f"{label.capitalize()} response exceeded the "
                f"{TIMEOUT_SECONDS}-second read deadline.",
            )
    finally:
        deadline_timer.cancel()

    if require_content and not payload:
        raise FetchError(
            "NETWORK",
            f"{label.capitalize()} request returned an empty response body.",
        )
    return bytes(payload)


def _read_bounded_asset(response: requests.Response) -> bytes:
    return _read_bounded_response(
        response,
        max_bytes=MAX_ASSET_BYTES,
        chunk_bytes=ASSET_CHUNK_BYTES,
        label="image",
        require_content=True,
    )


def _read_bounded_article(response: requests.Response) -> bytes:
    return _read_bounded_response(
        response,
        max_bytes=MAX_ARTICLE_BYTES,
        chunk_bytes=ARTICLE_CHUNK_BYTES,
        label="article",
        require_content=False,
    )


def fetch_html(session: requests.Session, url: str) -> bytes:
    response, _final_url = _request_article_with_retries(session, url)
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
        return _read_bounded_article(response)
    except requests.RequestException as exc:
        raise FetchError(
            "NETWORK",
            f"Article response failed while streaming: {exc}",
        ) from exc
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
    value = html_lib.unescape(value)

    normalized: list[str] = []
    index = 0
    while index < len(value):
        codepoint = ord(value[index])
        if 0xD800 <= codepoint <= 0xDBFF and index + 1 < len(value):
            low = ord(value[index + 1])
            if 0xDC00 <= low <= 0xDFFF:
                normalized.append(
                    chr(0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00))
                )
                index += 2
                continue
        normalized.append("\ufffd" if 0xD800 <= codepoint <= 0xDFFF else value[index])
        index += 1
    return "".join(normalized).strip()


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


def _normalize_image_url(value: str, article_url: str = "") -> str:
    value = value.strip()
    if article_url and value:
        return urljoin(article_url, value)
    if value.startswith("//"):
        return f"https:{value}"
    return value


def _tag_name(node: Any) -> str:
    tag = node.tag
    if not isinstance(tag, str):
        return ""
    tag = tag.rsplit("}", 1)[-1].lower()
    return tag.rsplit(":", 1)[-1]


def _image_source(image: Any, article_url: str = "") -> str:
    lazy_source = _normalize_image_url(
        str(image.get("data-src") or ""),
        article_url,
    )
    if lazy_source:
        return lazy_source
    return _normalize_image_url(str(image.get("src") or ""), article_url)


def _renderable_text_content(node: Any) -> str:
    pieces = [str(node.text or "")]
    for child in node:
        tag = _tag_name(child)
        if tag in {"pre", "code"}:
            pieces.append("".join(str(value) for value in child.itertext()))
        elif tag and tag not in SKIPPED_TAGS:
            pieces.append(_renderable_text_content(child))
        pieces.append(str(child.tail or ""))
    return "".join(pieces)


def _renderable_image_urls(node: Any, article_url: str) -> list[str]:
    image_urls: list[str] = []
    for child in node:
        tag = _tag_name(child)
        if not tag or tag in SKIPPED_TAGS:
            continue
        if tag == "img" and (source := _image_source(child, article_url)):
            image_urls.append(source)
        if tag not in {"pre", "code"}:
            image_urls.extend(_renderable_image_urls(child, article_url))
    return image_urls


def parse_article(raw_html: bytes, article_url: str) -> Article:
    source = raw_html.decode("utf-8", errors="replace")
    try:
        document = lxml_html.fromstring(raw_html)
    except (etree.ParserError, ValueError) as exc:
        detect_page_error(raw_html)
        raise FetchError("PARSE_FAILED", f"Could not parse article HTML: {exc}") from exc

    contents = document.xpath("//div[@id='js_content']")
    if not contents:
        detect_page_error(raw_html)
        raise FetchError("EMPTY_CONTENT", "No div#js_content article body was found.")
    content = contents[0]
    visible_text = _renderable_text_content(content)
    char_count = len(re.sub(r"\s+", "", visible_text))
    image_urls = _renderable_image_urls(content, article_url)
    if char_count == 0 and not image_urls:
        detect_page_error(raw_html)
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
            tz=CHINA_STANDARD_TIME,
        ).isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError) as exc:
        raise FetchError("PARSE_FAILED", f"Invalid publish timestamp: {timestamp}.") from exc

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


def _escape_plain_line_markers(value: str) -> str:
    lines: list[str] = []
    for line in value.splitlines(keepends=True) or [value]:
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        if re.fullmatch(r"\s*(?:-\s*){3,}", body):
            body = body.replace("-", r"\-")
        body = re.sub(r"^(\s*)([-+])(?=\s)", r"\1\\\2", body)
        body = re.sub(r"^(\s*)(\d+)([.)])(?=\s)", r"\1\2\\\3", body)
        lines.append(body + ending)
    return "".join(lines)


def _plain_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"\s+", " ", value.replace("\xa0", " "))
    escaped = normalized.replace("\\", "\\\\")
    escaped = re.sub(r"([`*_\[\]<>#~])", r"\\\1", escaped)
    return _escape_plain_line_markers(escaped)


def _markdown_destination(value: str) -> str:
    return quote(value, safe=MARKDOWN_DESTINATION_SAFE)


def _integer_attribute(node: Any, name: str, default: int) -> int:
    value = node.get(name)
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


def _split_boundary_whitespace(value: str) -> tuple[str, str, str]:
    match = re.fullmatch(r"(\s*)(.*?)(\s*)", value, flags=re.DOTALL)
    if not match:
        return "", value, ""
    return match.group(1), match.group(2), match.group(3)


def _wrap_inline(content: str, opening: str, closing: str) -> str:
    leading, core, trailing = _split_boundary_whitespace(content)
    if not core:
        return content
    return f"{leading}{opening}{core}{closing}{trailing}"


class MarkdownConverter:
    """Small, purpose-built converter for common WeChat article markup."""

    def __init__(self, asset_map: dict[str, str], article_url: str = "") -> None:
        self.asset_map = asset_map
        self.article_url = article_url

    def convert(self, root: Any) -> str:
        rendered = self._render_children(root)
        return self._cleanup(rendered)

    def _render_children(self, node: Any) -> str:
        pieces: list[str] = []
        inline_pieces = [_plain_text(node.text)]

        def flush_inline() -> None:
            if inline_pieces:
                pieces.append(
                    _escape_plain_line_markers("".join(inline_pieces))
                )
                inline_pieces.clear()

        structural_tags = BLOCK_TAGS | {
            "blockquote",
            "br",
            "h1",
            "h2",
            "h3",
            "h4",
            "hr",
            "img",
            "li",
            "ol",
            "p",
            "pre",
            "table",
            "ul",
        }
        for child in node:
            rendered = self._render_node(child)
            if _tag_name(child) in structural_tags:
                flush_inline()
                pieces.append(rendered)
            else:
                inline_pieces.append(rendered)
            inline_pieces.append(_plain_text(child.tail))
        flush_inline()
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
            return _wrap_inline(content, "**", "**")
        if tag in {"em", "i"}:
            return _wrap_inline(content, "*", "*")
        if tag == "blockquote":
            lines = stripped.splitlines()
            quoted = "\n".join(f"> {line}" if line else ">" for line in lines)
            return f"\n\n{quoted}\n\n" if quoted else ""
        if tag == "a":
            href = str(node.get("href") or "").strip()
            if not href:
                return content
            destination = _markdown_destination(href)
            leading, label, trailing = _split_boundary_whitespace(content)
            if not label:
                return f"[{_plain_text(href)}]({destination})"
            return f"{leading}[{label}]({destination}){trailing}"
        if tag == "code":
            return self._render_inline_code(node)
        if tag == "li":
            return stripped
        return content

    def _render_image(self, node: Any) -> str:
        source = _image_source(node, self.article_url)
        if not source:
            return ""
        target = self.asset_map.get(source, source)
        alt = _plain_text(str(node.get("alt") or "")).strip()
        return f"\n\n![{alt}]({_markdown_destination(target)})\n\n"

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
        content = "".join(node.itertext())
        leading, code, trailing = _split_boundary_whitespace(content)
        if not code:
            return content
        max_run = max((len(run) for run in re.findall(r"`+", code)), default=0)
        fence = "`" * max(1, max_run + 1)
        padding = " " if code.startswith("`") or code.endswith("`") else ""
        return f"{leading}{fence}{padding}{code}{padding}{fence}{trailing}"

    def _render_list(self, node: Any, *, ordered: bool) -> str:
        rows: list[str] = []
        items = [child for child in node if _tag_name(child) == "li"]
        next_number = _integer_attribute(node, "start", 1) if ordered else 1
        for item in items:
            body_parts = [_plain_text(item.text)]
            for child in item:
                child_tag = _tag_name(child)
                if child_tag in {"ul", "ol"}:
                    nested = self._render_list(
                        child,
                        ordered=child_tag == "ol",
                    ).strip("\n")
                    body_parts.append(f"\n{nested}\n")
                else:
                    body_parts.append(self._render_node(child))
                body_parts.append(_plain_text(child.tail))
            body = self._cleanup("".join(body_parts)).strip()
            if ordered:
                item_number = _integer_attribute(item, "value", next_number)
                marker = f"{item_number}. "
                next_number = item_number + 1
            else:
                marker = "- "
            continuation = " " * len(marker)
            body_lines = body.splitlines() or [""]
            rows.append(marker + body_lines[0])
            rows.extend(continuation + line for line in body_lines[1:])
        rendered_rows = "\n".join(rows)
        return f"\n\n{rendered_rows}\n\n" if rows else ""

    def _render_table(self, node: Any) -> str:
        rows: list[tuple[list[str], bool]] = []
        table_rows: list[Any] = []

        def collect_rows(parent: Any) -> None:
            for child in parent:
                tag = _tag_name(child)
                if tag == "table":
                    continue
                if tag == "tr":
                    table_rows.append(child)
                    continue
                collect_rows(child)

        collect_rows(node)
        active_rowspans: dict[int, int] = {}
        for row_index, row in enumerate(table_rows):
            cells = [
                cell
                for cell in row
                if _tag_name(cell) in {"th", "td"}
            ]
            if not cells and not active_rowspans:
                continue

            occupied = active_rowspans
            next_rowspans = {
                column: remaining - 1
                for column, remaining in occupied.items()
                if remaining > 1
            }
            values: list[str] = []
            column = 0
            for cell in cells:
                while column in occupied:
                    column += 1
                if column >= MAX_TABLE_COLUMNS:
                    break

                value = self._render_children(cell)
                value = self._cleanup(value).strip().replace("|", r"\|")
                value = re.sub(r"\s*\n\s*", "<br>", value)
                if len(values) < column:
                    values.extend("" for _ in range(column - len(values)))
                values.append(value)

                requested_colspan = max(
                    1,
                    min(
                        MAX_TABLE_COLUMNS,
                        _integer_attribute(cell, "colspan", 1),
                    ),
                )
                next_occupied = min(
                    (
                        occupied_column
                        for occupied_column in occupied
                        if occupied_column > column
                    ),
                    default=MAX_TABLE_COLUMNS,
                )
                colspan = min(
                    requested_colspan,
                    next_occupied - column,
                    MAX_TABLE_COLUMNS - column,
                )
                values.extend("" for _ in range(colspan - 1))
                rowspan = max(
                    1,
                    min(
                        len(table_rows) - row_index,
                        _integer_attribute(cell, "rowspan", 1),
                    ),
                )
                if rowspan > 1:
                    for spanned_column in range(column, column + colspan):
                        next_rowspans[spanned_column] = max(
                            next_rowspans.get(spanned_column, 0),
                            rowspan - 1,
                        )
                column += colspan

            if occupied:
                occupied_width = min(
                    MAX_TABLE_COLUMNS,
                    max(occupied) + 1,
                )
                if len(values) < occupied_width:
                    values.extend("" for _ in range(occupied_width - len(values)))
            rows.append((values, any(_tag_name(cell) == "th" for cell in cells)))
            active_rowspans = next_rowspans
        if not rows:
            return ""

        width = max(len(values) for values, _ in rows)
        normalized = [values + [""] * (width - len(values)) for values, _ in rows]
        first_row_is_header = rows[0][1]
        header = normalized[0] if first_row_is_header else [""] * width
        data_rows = normalized[1:] if first_row_is_header else normalized
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in range(width)) + " |",
        ]
        lines.extend("| " + " | ".join(values) + " |" for values in data_rows)
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
                    cleaned.append(raw_line.rstrip())
                elif marker.startswith(fence_marker):
                    in_fence = False
                    fence_marker = ""
                    cleaned.append(raw_line.rstrip())
                else:
                    cleaned.append(raw_line)
                blank = False
                continue
            if in_fence:
                cleaned.append(raw_line)
                continue

            line = raw_line.rstrip()
            if not line.strip():
                if cleaned and not blank:
                    cleaned.append("")
                blank = True
                continue
            if not re.match(
                r"^(?: {2,}\S|\s*(?:[-*+] |\d+\. |>|```|\|))",
                line,
            ):
                line = line.strip()
            cleaned.append(line)
            blank = False
        return "\n".join(cleaned).strip()


def _response_content_type(response: requests.Response) -> str:
    return response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()


def _image_extension(response: requests.Response, url: str) -> str:
    content_type = _response_content_type(response)
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


def invalidate_asset_cache(output_dir: Path) -> None:
    assets_dir = output_dir / "assets"
    if not os.path.lexists(assets_dir):
        return
    if assets_dir.is_symlink() or not assets_dir.is_dir():
        assets_dir.unlink()
        return
    shutil.rmtree(assets_dir)


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
            response, final_url = _request_asset_with_retries(session, url)
            if response.status_code != 200:
                raise FetchError(
                    "NETWORK",
                    f"Image request returned HTTP {response.status_code}.",
                )
            content_type = _response_content_type(response)
            if content_type and not content_type.startswith("image/"):
                raise FetchError(
                    "NETWORK",
                    f"Image request returned non-image Content-Type {content_type}.",
                )
            payload = _read_bounded_asset(response)
            extension = _image_extension(response, final_url)
            destination = assets_dir / f"{index:03d}{extension}"
            atomic_write_bytes(destination, payload)
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
    body = MarkdownConverter(asset_map, source_url).convert(article.content)
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


def _cached_markdown_matches_sn(markdown_path: Path, sn: str) -> bool:
    try:
        lines = markdown_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        key, separator, raw_value = line.partition(":")
        if separator and key.strip() == "sn":
            try:
                cached_sn = json.loads(raw_value.strip())
            except (json.JSONDecodeError, TypeError):
                return False
            return isinstance(cached_sn, str) and cached_sn == sn
    return False


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
        and _cached_markdown_matches_sn(markdown_path, sn)
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

    article = parse_article(raw_html, original_url)
    if not cache_hit:
        try:
            invalidate_asset_cache(output_dir)
            atomic_write_bytes(raw_html_path, raw_html)
        except OSError as exc:
            raise FetchError(
                "PARSE_FAILED",
                f"Could not publish refreshed article cache: {exc}",
            ) from exc

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
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    binary_stdout = getattr(sys.stdout, "buffer", None)
    if binary_stdout is not None:
        binary_stdout.write(encoded)
        binary_stdout.flush()
        return
    sys.stdout.write(encoded.decode("utf-8"))
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
