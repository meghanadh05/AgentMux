from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from amx.models import Account
from amx.security import ensure_private_dir


class Provider:
    key = ""
    display_name = ""
    executable = ""
    config_env_var = ""
    login_args: List[str] = []

    def ensure_environment(self, account: Account) -> None:
        ensure_private_dir(Path(account.home))

    def status(self, account: Account) -> str:
        if not Path(account.home).exists():
            return "Missing provider home"
        if self.is_authenticated(account):
            return "Authenticated"
        return "Login needed"

    def is_authenticated(self, account: Account) -> bool:
        return False

    def env(self, account: Account) -> Dict[str, str]:
        return {self.config_env_var: account.home} if self.config_env_var else {}

    def executable_path(self) -> Optional[str]:
        return shutil.which(self.executable) if self.executable else None

    def launch_login(self, account: Account) -> int:
        executable = self.executable_path()
        if executable is None:
            raise FileNotFoundError(f"{self.display_name} CLI executable not found: {self.executable}")
        self.ensure_environment(account)
        env = self.env(account)
        merged_env = os.environ.copy()
        merged_env.update(env)
        return subprocess.call([executable, *self.login_args], env=merged_env)

    def launch(self, account: Account, args: Optional[List[str]] = None) -> int:
        executable = self.executable_path()
        if executable is None:
            raise FileNotFoundError(f"{self.display_name} CLI executable not found: {self.executable}")
        self.ensure_environment(account)
        merged_env = os.environ.copy()
        merged_env.update(self.env(account))
        return subprocess.call([executable, *(args or [])], env=merged_env, cwd=os.getcwd())
