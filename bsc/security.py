"""Input boundaries, not a replacement for an OS/process sandbox."""
from __future__ import annotations
import ipaddress
import json
import re
import socket
from urllib.parse import urlsplit

class InputError(ValueError):
    """Safe, user-facing validation failure."""

SECRET_PATTERNS = (
    r'\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',
    r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}',
    r'(?i)(?:api[_-]?key|client[_-]?secret|password|access[_-]?token)\s*[=:]\s*["\']?[^\s"\']{12,}',
    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
)

def text(value: object, label: str, maximum: int = 10000, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise InputError(f'{label} must be text.')
    value = value.strip()
    if nonempty and not value:
        raise InputError(f'{label} is required.')
    if len(value) > maximum or '\x00' in value:
        raise InputError(f'{label} exceeds its limit or contains an invalid character.')
    return value

def no_secrets(value: object) -> None:
    data = json.dumps(value, ensure_ascii=False)
    if any(re.search(p, data) for p in SECRET_PATTERNS):
        raise InputError('Possible credential detected. Use an environment-variable name, not a secret value.')

def slug(value: str) -> str:
    result = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')[:64].rstrip('-')
    if not result:
        raise InputError('Use at least one letter or number in the skill name.')
    return result

def valid_slug(value: object) -> str:
    value = text(value, 'Skill name', 64)
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value):
        raise InputError('Skill names use lowercase letters, numbers, and single hyphens.')
    return value

def endpoint(value: object, *, local: bool = False, resolve: bool = False) -> str:
    """Remote HTTPS only; explicitly opted-in literal loopback for local LLMs.

    DNS is checked immediately before provider requests. This is defense in depth,
    not DNS pinning: a hostile DNS rebinding environment needs outbound firewalling.
    Importing a document never connects to its declared servers.
    """
    value = text(value, 'API base URL', 2000)
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise InputError('Invalid API port.') from exc
    host = parsed.hostname
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise InputError('Use a base URL without credentials, a query, or a fragment.')
    loopback = host in {'127.0.0.1', '::1', 'localhost'}
    if loopback and local and parsed.scheme in {'http', 'https'}:
        return value.rstrip('/')
    if parsed.scheme != 'https' or loopback:
        raise InputError('Remote APIs require HTTPS. Enable local mode only for a loopback model.')
    if host.endswith('.local') or host == 'metadata.google.internal':
        raise InputError('Private-network API addresses are not allowed.')
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None and not addr.is_global:
        raise InputError('Private-network API addresses are not allowed.')
    if resolve:
        try:
            addresses = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise InputError('The model endpoint could not be resolved.') from exc
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise InputError('The model endpoint resolves to a private address.')
    return value.rstrip('/')
