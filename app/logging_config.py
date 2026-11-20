"""Logging that never writes passwords or authorization headers."""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
from pathlib import Path

_PATTERNS = (
    re.compile(r"(?i)(password\s*[=:]\s*)(\S+)"),
    re.compile(r"(?i)(authorization\s*[=:]\s*)(\S+)"),
    re.compile(r"(?i)(Basic\s+)([A-Za-z0-9+/=]+)"),
    re.compile(r"(?i)(NTLM\s+)([A-Za-z0-9+/=]+)"),
    re.compile(r"(?i)(Bearer\s+)(\S+)"),
    re.compile(r"(https?://)([^/\s:@]+):([^/\s@]+)@"),
)


def redact(text: str, secrets: list[str] | None = None) -> str:
    redacted = text
    for pattern in _PATTERNS[:5]:
        redacted = pattern.sub(r"\1***", redacted)
    redacted = _PATTERNS[5].sub(r"\1\2:***@", redacted)
    for secret in secrets or []:
        if secret and len(secret) >= 4:
            redacted = redacted.replace(secret, "***")
    return redacted


class RedactionFilter(logging.Filter):
    secrets: list[str] = []

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = redact(record.getMessage(), self.secrets)
            record.msg = rendered
            record.args = ()
        except Exception:
            record.msg = "Log record redaction failed."
            record.args = ()
        return True


def register_secret(value: str) -> None:
    if not value or len(value) < 4:
        return
    if value not in RedactionFilter.secrets:
        RedactionFilter.secrets.append(value)
    if len(RedactionFilter.secrets) > 10:
        del RedactionFilter.secrets[:-10]


_configured = False


def setup_logging(level: str = "INFO", log_path: Path | None = None) -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream.addFilter(RedactionFilter())
    root.addHandler(stream)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(RedactionFilter())
        root.addHandler(file_handler)
        try:
            os.chmod(log_path.parent, 0o700)
            os.chmod(log_path, 0o600)
        except OSError:
            logging.getLogger(__name__).warning("Could not restrict log file permissions.")
    for name in ("exchangelib", "urllib3", "requests", "spnego"):
        logging.getLogger(name).setLevel(logging.WARNING)
    _configured = True
