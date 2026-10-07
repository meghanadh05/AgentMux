from __future__ import annotations

import os
from pathlib import Path


SECRET_FIELD_NAMES = ("token", "secret", "password", "cookie", "key")


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)


def redact(value: object) -> str:
    text = str(value)
    if not text:
        return ""
    return "<redacted>"


def contains_secret_name(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in SECRET_FIELD_NAMES)

