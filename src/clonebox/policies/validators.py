from __future__ import annotations

import fnmatch
from typing import List
from urllib.parse import urlparse


def extract_hostname(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").strip().lower()


def host_matches(hostname: str, pattern: str) -> bool:
    hostname = (hostname or "").strip().lower()
    pattern = (pattern or "").strip().lower()
    if not hostname or not pattern:
        return False
    return fnmatch.fnmatch(hostname, pattern)


def is_host_allowed(hostname: str, allowlist: List[str], blocklist: List[str]) -> bool:
    if any(host_matches(hostname, p) for p in blocklist or []):
        return False
    if allowlist:
        return any(host_matches(hostname, p) for p in allowlist)
    return True
