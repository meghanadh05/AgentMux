from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from .models import Account, AppConfig, EditorEnvironment, VSCodeProfileMapping
from .paths import config_file, provider_home, vscode_user_data
from .security import ensure_private_dir


class ConfigStore:
    def __init__(self, config_root: Optional[Path] = None, data_root: Optional[Path] = None) -> None:
        self.config_root = config_root
        self.data_root = data_root
        self.path = config_file(config_root)
        self.loaded_version: Optional[int] = None
        self.loaded_bytes: Optional[bytes] = None

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig.empty()
        try:
            self.loaded_bytes = self.path.read_bytes()
            raw = json.loads(self.loaded_bytes.decode("utf-8"))
            self.loaded_version = int(raw.get("version", 1))
            return AppConfig.from_dict(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON config at {self.path}: {exc}") from exc

    def save(self, config: AppConfig) -> None:
        ensure_private_dir(self.path.parent)
        self._backup_before_migration()
        payload = json.dumps(config.to_dict(), indent=2, sort_keys=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".config.", suffix=".tmp", dir=self.path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary_path.chmod(0o600)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        self.loaded_version = config.version
        self.loaded_bytes = (payload + "\n").encode("utf-8")

    def _backup_before_migration(self) -> None:
        if self.loaded_version is None or self.loaded_version >= 3 or self.loaded_bytes is None:
            return
        backup = self.path.with_name(f"config.v{self.loaded_version}.backup.json")
        try:
            descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(self.loaded_bytes)
            handle.flush()
            os.fsync(handle.fileno())

    def create_account(self, config: AppConfig, provider: str, name: str, imported_home: Optional[Path] = None, imported_vscode: Optional[Path] = None) -> Account:
        provider = provider.lower()
        if any(account.provider == provider and account.name.lower() == name.lower() for account in config.accounts):
            raise ValueError(f"{provider} account {name!r} already exists")
        account_id = str(uuid.uuid4())
        home = imported_home or provider_home(provider, account_id, self.data_root)
        metadata = {}
        if imported_vscode:
            metadata["legacy_vscode_user_data_dir"] = str(imported_vscode)
        account = Account(
            id=account_id,
            provider=provider,
            name=name,
            provider_home=str(home),
            imported=bool(imported_home),
            metadata=metadata,
        )
        config.accounts.append(account)
        if imported_vscode:
            config.legacy_editor_environments.append(
                EditorEnvironment(
                    id=str(uuid.uuid4()),
                    name=f"{name} VS Code",
                    editor="vscode",
                    mode="isolated",
                    user_data_dir=str(imported_vscode),
                    account_mode="pinned",
                    pinned_account_id=account.id,
                    account_ids={provider: account.id},
                    metadata={"imported": True},
                )
            )
        if not config.active_account_id:
            config.set_active_account(account)
        else:
            config.active_accounts.setdefault(provider, account.id)
        return account

    def create_vscode_profile_mapping(
        self, config: AppConfig, name: str, account_ids: Optional[dict[str, str]] = None
    ) -> VSCodeProfileMapping:
        if name.casefold() == "default":
            raise ValueError("Default derives from active accounts and cannot be created")
        if any(profile.profile_name.casefold() == name.casefold() for profile in config.vscode_profiles):
            raise ValueError(f"VS Code profile {name!r} is already configured")
        profile = VSCodeProfileMapping(name, account_ids or {})
        config.vscode_profiles.append(profile)
        return profile

    def create_environment(
        self,
        config: AppConfig,
        name: str,
        editor: str = "vscode",
        mode: str = "normal",
        account_mode: str = "follow_active",
        pinned_account_id: Optional[str] = None,
        account_ids: Optional[dict[str, str]] = None,
        user_data_dir: Optional[Path] = None,
    ) -> EditorEnvironment:
        if any(environment.name.lower() == name.lower() for environment in config.environments):
            raise ValueError(f"Environment {name!r} already exists")
        environment_id = str(uuid.uuid4())
        resolved_user_data = user_data_dir
        if mode == "isolated" and resolved_user_data is None:
            resolved_user_data = vscode_user_data(environment_id, self.data_root)
        environment = EditorEnvironment(
            id=environment_id,
            name=name,
            editor=editor,
            mode=mode,
            user_data_dir=str(resolved_user_data) if resolved_user_data else None,
            account_mode=account_mode,
            pinned_account_id=pinned_account_id,
            account_ids=account_ids or {},
        )
        config.environments.append(environment)
        return environment
