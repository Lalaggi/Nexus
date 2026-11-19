"""Fetch a public page and reduce it to readable text."""

from __future__ import annotations

import asyncio
import html as html_lib
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

from .base import Tool, ToolContext, ToolResult, register

MAX_BYTES = 3_000_000
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 Nexus/0.1"
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "Absolute http(s) URL to fetch."},
        "max_chars": {
            "type": "integer",
            "description": "Maximum characters of extracted text (default 20000).",
            "minimum": 1000,
            "maximum": 60000,
        },
    },
    "required": ["url"],
}


def _resolve_public(host: str, port: int) -> str:
    """Resolve a hostname once and return a single validated public address.

    Resolving here and then handing the *hostname* to the HTTP client would let
    a hostile DNS server answer with a public address for this check and a
    private one when the client resolves again (DNS rebinding). The caller
    therefore connects to the address returned here, pinning the connection.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Could not resolve that host.") from exc
    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0]).split("%")[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("Could not resolve that host.") from exc
        if not ip.is_global:
            raise ValueError("Private, loopback, and link-local addresses are blocked.")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise ValueError("Could not resolve that host.")
    # Prefer IPv4: a host with no working IPv6 route would otherwise fail even
    # though it also has a perfectly good A record.
    addresses.sort(key=lambda address: ":" in address)
    return addresses[0]


async def _prepare_request(url: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """Validate a URL, resolve it once, and return a pinned request target.

    Returns ``(pinned_url, headers, extensions)``. The pinned URL contains the
    validated IP address; the Host header and TLS SNI/certificate hostname stay
    the original hostname, so virtual hosting and certificate verification are
    unchanged.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only absolute http(s) URLs are allowed.")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed.")
    host = parsed.hostname
    if host.lower() in {"localhost", "localhost.localdomain"} or host.lower().endswith(".local"):
        raise ValueError("Local addresses are blocked.")

    try:
        host_ascii = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("Invalid hostname.") from None
    default_port = 443 if parsed.scheme == "https" else 80
    try:
        port = parsed.port or default_port
    except ValueError:
        raise ValueError("Invalid port in URL.") from None

    address = await asyncio.to_thread(_resolve_public, host_ascii, port)
    host_literal = f"[{address}]" if ":" in address else address
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    pinned = f"{parsed.scheme}://{host_literal}:{port}{path}"

    host_display = f"[{host_ascii}]" if ":" in host_ascii else host_ascii
    host_header = host_display if parsed.port is None else f"{host_display}:{parsed.port}"
    headers = {"Host": host_header}
    extensions: dict[str, str] = {}
    if parsed.scheme == "https":
        # httpcore uses this for both SNI and certificate verification.
        extensions["sni_hostname"] = host_ascii
    return pinned, headers, extensions


def _fallback_extract(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?is)</(p|div|li|h[1-6]|tr|section|article)>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html_lib.unescape(raw)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _extract_html(raw: str, final_url: str) -> tuple[str, str]:
    title = ""
    text = ""
    try:
        import trafilatura

        metadata = trafilatura.extract_metadata(raw)
        if metadata and metadata.title:
            title = metadata.title.strip()
        text = (
            trafilatura.extract(
                raw,
                url=final_url,
                output_format="markdown",
                include_links=True,
                include_formatting=True,
                include_comments=False,
            )
            or ""
        )
    except Exception:
        pass
    if not title:
        match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
        if match:
            title = html_lib.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    if not text.strip():
        text = _fallback_extract(raw)
    return title, text.strip()


async def webfetch(ctx: ToolContext, args: dict) -> ToolResult:
    url = str(args.get("url", "")).strip()
    max_chars = max(1000, min(60_000, int(args.get("max_chars") or 20_000)))
    if not url:
        return ToolResult(content="A URL is required.", ok=False)

    current = url
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain,application/json,application/pdf;q=0.9,*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.8",
    }
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=False) as client:
            for _ in range(6):
                pinned, host_headers, extensions = await _prepare_request(current)
                async with client.stream(
                    "GET",
                    pinned,
                    headers={**headers, **host_headers},
                    extensions=extensions,
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Redirect without a Location header.")
                        current = urljoin(current, location)
                        continue

                    response.raise_for_status()
                    ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    buffer = bytearray()
                    truncated = False
                    async for chunk in response.aiter_bytes():
                        buffer.extend(chunk)
                        if len(buffer) >= MAX_BYTES:
                            truncated = True
                            break
                    break
            else:
                raise ValueError("Too many redirects.")
    except ValueError as exc:
        return ToolResult(content=f"Could not fetch {url}: {exc}", ok=False, summary="Blocked URL")
    except httpx.HTTPStatusError as exc:
        return ToolResult(
            content=f"Fetching {current} failed with HTTP {exc.response.status_code}.",
            ok=False,
            summary="HTTP error",
        )
    except httpx.HTTPError as exc:
        return ToolResult(content=f"Fetching {url} failed: {exc}", ok=False, summary="Fetch failed")

    if ctype == "application/pdf" or current.lower().endswith(".pdf"):
        try:
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(bytes(buffer)))
            pages = [page.extract_text() or "" for page in reader.pages[:40]]
            text = "\n\n".join(pages).strip()
            title = "PDF document"
        except Exception as exc:
            return ToolResult(content=f"Could not read that PDF: {exc}", ok=False)
    else:
        if ctype and not (
            ctype.startswith("text/")
            or ctype in {"application/json", "application/xml", "application/xhtml+xml"}
        ):
            return ToolResult(
                content=f"That URL returned unsupported content type {ctype}. Only text, HTML, JSON, and PDF are supported.",
                ok=False,
            )
        raw = bytes(buffer).decode("utf-8", "replace")
        if ctype == "application/json":
            title = "JSON response"
            text = raw
        elif ctype in {"text/plain", "text/markdown", "text/csv"}:
            title = current.rsplit("/", 1)[-1] or "Text document"
            text = raw
        else:
            title, text = _extract_html(raw, current)

    if not text.strip():
        return ToolResult(content=f"No readable text found at {current}.", ok=False, summary="Empty page")

    clipped = text[:max_chars]
    suffix = ""
    if len(text) > len(clipped):
        suffix = f"\n\n[Truncated at {max_chars} characters of {len(text):,}.]"
    if truncated:
        suffix += "\n[Response body was larger than 3 MB and was cut off.]"
    body = f"# {title or 'Fetched page'}\nURL: {current}\n\n{clipped}{suffix}"
    return ToolResult(
        content=body,
        summary=f"{len(clipped):,} chars from {urlparse(current).hostname}",
        data={"url": current, "title": title, "content": clipped[:4000]},
    )


register(
    Tool(
        name="web_fetch",
        description=(
            "Fetch a public web page and extract its readable text as Markdown. Use after "
            "web_search to read the best sources. Only public http(s) addresses are allowed."
        ),
        parameters=PARAMETERS,
        handler=webfetch,
    )
)
