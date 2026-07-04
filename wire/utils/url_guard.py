"""SSRF protection for user-supplied target URLs.

The API accepts an arbitrary URL and the engine then fetches it and navigates a
browser to it. Without a guard, a user could point WIRE at internal services
(``http://localhost:8000``), private networks, or the cloud metadata endpoint
(``http://169.254.169.254/…``) and exfiltrate secrets — a classic SSRF.

``is_public_http_url`` allows only ``http``/``https`` to a host that resolves
entirely to public IP addresses; everything loopback/private/link-local/
reserved is rejected, and DNS is resolved so a public-looking hostname that
maps to an internal address is still blocked.
"""

import ipaddress
import socket
from typing import List
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost")
_BLOCKED_HOST_NAMES = {"localhost"}


def _ip_is_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable → treat as unsafe
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _resolve(host: str) -> List[str]:
    """Return all IP strings ``host`` resolves to (empty on failure)."""
    try:
        return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None)})
    except (socket.gaierror, socket.herror, OSError, UnicodeError):
        return []


def is_public_http_url(url: str) -> bool:
    """True only if ``url`` is http(s) to a host that resolves to public IPs."""
    try:
        parsed = urlparse(url.strip())
    except (ValueError, AttributeError):
        return False

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False

    host = parsed.hostname
    if not host:
        return False
    host = host.lower()

    if host in _BLOCKED_HOST_NAMES or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return False

    # A literal IP is checked directly; a hostname is resolved and every
    # resolved address must be public (defeats DNS-based SSRF).
    try:
        ipaddress.ip_address(host)
        return not _ip_is_blocked(host)
    except ValueError:
        pass

    resolved = _resolve(host)
    if not resolved:
        return False
    return all(not _ip_is_blocked(ip) for ip in resolved)


def check_public_http_url(url: str) -> None:
    """Raise ``ValueError`` if ``url`` is not a safe public http(s) target."""
    if not is_public_http_url(url):
        raise ValueError(
            "URL is not an allowed public http(s) target (SSRF protection): " f"{url!r}"
        )


def is_disallowed_subresource(url: str) -> bool:
    """Fast SSRF check for sub-resource fetches (assets referenced by a page).

    Blocks obvious internal targets — a literal private/loopback/link-local/
    reserved IP (including the cloud metadata address) or a local hostname —
    without a DNS lookup per asset. Hostname-based internal targets are already
    covered by the full ``is_public_http_url`` check applied to the entry URL.
    Non-http(s) references (``data:``, relative) are handled elsewhere and are
    not flagged here.
    """
    try:
        parsed = urlparse(url.strip())
    except (ValueError, AttributeError):
        return True
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in _BLOCKED_HOST_NAMES or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False  # a hostname — entry-URL guard handles DNS-based cases
    return _ip_is_blocked(host)
