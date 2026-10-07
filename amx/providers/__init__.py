from .base import Provider
from .codex import CodexProvider

PROVIDERS = {
    "codex": CodexProvider(),
}


def get_provider(name: str) -> Provider:
    key = name.lower()
    if key not in PROVIDERS:
        raise KeyError(f"Unsupported provider: {name}")
    return PROVIDERS[key]
