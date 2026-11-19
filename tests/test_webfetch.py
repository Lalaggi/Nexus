from __future__ import annotations

import socket

import pytest

from nexus.tools import webfetch


def _fake_addrinfo(*addresses: str):
    return [
        (socket.AF_INET6 if ":" in address else socket.AF_INET, 1, 6, "", (address, 0))
        for address in addresses
    ]


async def test_prepare_request_pins_the_resolved_address(monkeypatch):
    calls: list[tuple[str, int]] = []

    def fake_resolve(host: str, port: int) -> str:
        calls.append((host, port))
        return "93.184.216.34"

    monkeypatch.setattr(webfetch, "_resolve_public", fake_resolve)

    pinned, headers, extensions = await webfetch._prepare_request(
        "https://example.com/report?id=3"
    )

    # The hostname is resolved exactly once; the request itself goes to the
    # validated address so a second DNS answer cannot redirect it to localhost.
    assert calls == [("example.com", 443)]
    assert pinned == "https://93.184.216.34:443/report?id=3"
    assert headers == {"Host": "example.com"}
    assert extensions == {"sni_hostname": "example.com"}


async def test_prepare_request_keeps_explicit_port_and_http_semantics(monkeypatch):
    monkeypatch.setattr(webfetch, "_resolve_public", lambda host, port: "93.184.216.34")

    pinned, headers, extensions = await webfetch._prepare_request(
        "http://example.com:8080/path"
    )

    assert pinned == "http://93.184.216.34:8080/path"
    assert headers == {"Host": "example.com:8080"}
    assert extensions == {}


async def test_prepare_request_brackets_ipv6_addresses(monkeypatch):
    monkeypatch.setattr(webfetch, "_resolve_public", lambda host, port: "2606:2800:220:1::1")

    pinned, headers, _extensions = await webfetch._prepare_request("https://example.com/")

    assert pinned == "https://[2606:2800:220:1::1]:443/"
    assert headers["Host"] == "example.com"


async def test_prepare_request_brackets_ipv6_host_header(monkeypatch):
    monkeypatch.setattr(webfetch, "_resolve_public", lambda host, port: "2606:2800:220:1::1")

    pinned, headers, _extensions = await webfetch._prepare_request(
        "https://[2606:2800:220:1::1]/"
    )

    assert pinned == "https://[2606:2800:220:1::1]:443/"
    assert headers["Host"] == "[2606:2800:220:1::1]"


def test_resolve_public_rejects_non_global_answers(monkeypatch):
    monkeypatch.setattr(webfetch.socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo("127.0.0.1"))

    with pytest.raises(ValueError, match="Private"):
        webfetch._resolve_public("example.com", 80)


def test_resolve_public_rejects_mixed_public_and_private_answers(monkeypatch):
    monkeypatch.setattr(
        webfetch.socket,
        "getaddrinfo",
        lambda *a, **k: _fake_addrinfo("93.184.216.34", "169.254.169.254"),
    )

    with pytest.raises(ValueError, match="Private"):
        webfetch._resolve_public("example.com", 80)


def test_resolve_public_prefers_ipv4(monkeypatch):
    monkeypatch.setattr(
        webfetch.socket,
        "getaddrinfo",
        lambda *a, **k: _fake_addrinfo("2606:2800:220:1::1", "93.184.216.34"),
    )

    assert webfetch._resolve_public("example.com", 80) == "93.184.216.34"
