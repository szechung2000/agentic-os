"""Small, shared redaction helpers for durable records."""

from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS = (
    re.compile(
        r"(?i)(?:api[_-]?key|token|secret|password)"
        r"(?:[\"']?\s*[=:]\s*[\"']?)[^\s\"',}]+"
    ),
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{6,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
SENSITIVE_FIELD = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|authorization)")


def redact_text(text: str) -> str:
    """Replace recognisable secret values without changing unrelated text."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_value(value: Any, *, field_name: str | None = None) -> Any:
    """Recursively redact values before they cross a durable boundary."""
    if field_name and SENSITIVE_FIELD.search(field_name):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(key): redact_value(item, field_name=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_bytes(content: bytes) -> bytes:
    """Redact UTF-8 artifact content; leave non-text bytes untouched."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    return redact_text(text).encode("utf-8")
