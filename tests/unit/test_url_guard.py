"""SSRF guard: only public http(s) targets are allowed."""

import pytest

import wire.utils.url_guard as ug
from wire.utils.url_guard import check_public_http_url, is_public_http_url


def test_rejects_non_http_schemes():
    assert is_public_http_url("file:///etc/passwd") is False
    assert is_public_http_url("ftp://example.com/x") is False
    assert is_public_http_url("gopher://example.com") is False
    assert is_public_http_url("javascript:alert(1)") is False


def test_rejects_loopback_and_private_and_metadata():
    for url in (
        "http://localhost:8000/admin",
        "http://127.0.0.1/",
        "http://0.0.0.0/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://[::1]/",  # IPv6 loopback
        "http://myservice.internal/",
        "http://db.local/",
    ):
        assert is_public_http_url(url) is False, url


def test_allows_public_host(monkeypatch):
    # Resolve to a public IP without real DNS.
    monkeypatch.setattr(ug, "_resolve", lambda host: ["93.184.216.34"])  # example.com
    assert is_public_http_url("https://example.com/path") is True


def test_public_hostname_resolving_to_private_is_blocked(monkeypatch):
    # DNS-rebinding style: a public-looking name that maps to an internal IP.
    monkeypatch.setattr(ug, "_resolve", lambda host: ["10.1.2.3"])
    assert is_public_http_url("https://evil.example.com/") is False


def test_unresolvable_host_is_blocked(monkeypatch):
    monkeypatch.setattr(ug, "_resolve", lambda host: [])
    assert is_public_http_url("https://nope.invalid/") is False


def test_check_raises_for_blocked():
    with pytest.raises(ValueError):
        check_public_http_url("http://127.0.0.1/")


def test_ip_is_blocked_on_garbage():
    assert ug._ip_is_blocked("not-an-ip") is True


def test_public_ip_literal_allowed():
    assert is_public_http_url("http://93.184.216.34/") is True


def test_real_resolve_localhost_and_invalid():
    # Real getaddrinfo: localhost resolves; a bogus TLD does not.
    assert ug._resolve("localhost")  # non-empty (loopback addrs)
    assert ug._resolve("host.invalid.nonexistent.tld.example") == []
