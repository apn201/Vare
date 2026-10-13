"""Shared by check_secrets.py and check_publishable.py."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Patterns worth stopping a push for. Deliberately narrow: a scanner that
# cries wolf gets ignored, and this one has to be trusted the day it fires.
SECRETS = [
    ("AWS access key id", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer or api token assignment", re.compile(
        r"(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)"
        r"\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]", re.I)),
    ("OpenAI-style key", re.compile(r"\bsk-(proj-)?[A-Za-z0-9_\-]{20,}\b")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
]

# Paths that must never appear in any commit.
FORBIDDEN_PATHS = [
    re.compile(r"^private/"),
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)\.env\.(?!example$)[^/]+$"),
    re.compile(r"\.pem$"),
    re.compile(r"\.db$"),
    re.compile(r"^var/"),
    re.compile(r"^benchmark/results/"),
]


def local_secret_values():
    """The actual secret values on this machine, from .env files and the
    environment. Whatever the key format, the literal value must never be in
    a tracked file. Only values of 12+ chars count, to avoid false hits."""
    values = {}
    for path in (ROOT / ".env", ROOT / "private" / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip().strip("'\"")
            if re.search(r"KEY|TOKEN|SECRET|PASSWORD", name, re.I) and len(value) >= 12:
                values[value] = name
    for name, value in os.environ.items():
        if re.search(r"(^|_)(API_KEY|TOKEN|SECRET)$", name) and len(value) >= 12:
            values.setdefault(value, name)
    return values


def scan_text(text, path, secret_values):
    found = []
    for label, pattern in SECRETS:
        m = pattern.search(text)
        if m:
            found.append("{} in {}: {}".format(label, path, m.group(0)[:12] + "..."))
    for value, name in secret_values.items():
        if value in text:
            found.append("the value of {} appears in {}".format(name, path))
    return found
