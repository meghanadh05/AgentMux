from __future__ import annotations

from pathlib import Path

from amx.models import Account

from .base import Provider


class CodexProvider(Provider):
    key = "codex"
    display_name = "Codex"
    executable = "codex"
    config_env_var = "CODEX_HOME"
    login_args = ["login"]

    def is_authenticated(self, account: Account) -> bool:
        home = Path(account.home)
        # Current Codex stores auth beneath CODEX_HOME. Names have changed over time,
        # so status deliberately checks for known auth artifacts without reading them.
        candidates = [
            home / "auth.json",
            home / "codex.json",
            home / "credentials.json",
            home / "config.toml",
        ]
        return any(path.exists() for path in candidates)
