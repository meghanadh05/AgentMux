from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


CONFIG_VERSION = 3
SUPPORTED_PROVIDERS = {"codex", "claude"}


@dataclass
class Account:
    id: str
    provider: str
    name: str
    provider_home: str
    created_at: Optional[str] = None
    imported: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def home(self) -> str:
        return self.provider_home

    @property
    def vscode_user_data_dir(self) -> str:
        return str(self.metadata.get("legacy_vscode_user_data_dir", ""))

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Account":
        required = {"id", "provider", "name"}
        missing = required.difference(raw)
        if missing:
            raise ValueError(f"Account is missing required fields: {', '.join(sorted(missing))}")
        provider = str(raw["provider"]).lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider in config: {provider}")
        provider_home = str(raw.get("provider_home", raw.get("home", "")))
        metadata = dict(raw.get("metadata", {}))
        if "vscode_user_data_dir" in raw and "legacy_vscode_user_data_dir" not in metadata:
            metadata["legacy_vscode_user_data_dir"] = str(raw["vscode_user_data_dir"])
        return cls(
            id=str(raw["id"]),
            provider=provider,
            name=str(raw["name"]),
            provider_home=provider_home,
            created_at=raw.get("created_at"),
            imported=bool(raw.get("imported", False)),
            metadata=metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "name": self.name,
            "provider_home": self.provider_home,
            "created_at": self.created_at,
            "imported": self.imported,
            "metadata": self.metadata,
        }


@dataclass
class EditorEnvironment:
    id: str
    name: str
    editor: str = "vscode"
    mode: str = "normal"
    user_data_dir: Optional[str] = None
    account_mode: str = "follow_active"
    pinned_account_id: Optional[str] = None
    account_ids: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "EditorEnvironment":
        required = {"id", "name", "editor", "mode", "account_mode"}
        missing = required.difference(raw)
        if missing:
            raise ValueError(f"Environment is missing required fields: {', '.join(sorted(missing))}")
        account_ids = {str(k).lower(): str(v) for k, v in (raw.get("account_ids") or {}).items()}
        if raw.get("pinned_account_id") and not account_ids:
            # Backward compatibility for the short-lived single-pinned-account model.
            account_ids["default"] = str(raw["pinned_account_id"])
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            editor=str(raw.get("editor", "vscode")),
            mode=str(raw.get("mode", "normal")),
            user_data_dir=raw.get("user_data_dir"),
            account_mode=str(raw.get("account_mode", "follow_active")),
            pinned_account_id=raw.get("pinned_account_id"),
            account_ids=account_ids,
            metadata=dict(raw.get("metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "editor": self.editor,
            "mode": self.mode,
            "user_data_dir": self.user_data_dir,
            "account_mode": self.account_mode,
            "pinned_account_id": self.pinned_account_id,
            "account_ids": self.account_ids,
            "metadata": self.metadata,
        }


@dataclass
class VSCodeProfileMapping:
    profile_name: str
    account_ids: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "VSCodeProfileMapping":
        name = str(raw.get("profile_name", "")).strip()
        if not name or name.casefold() == "default":
            raise ValueError("Named VS Code profiles require a non-Default profile name")
        return cls(
            profile_name=name,
            account_ids={str(k).lower(): str(v) for k, v in (raw.get("account_ids") or {}).items()},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"profile_name": self.profile_name, "account_ids": self.account_ids}


@dataclass
class AppConfig:
    version: int = CONFIG_VERSION
    active_provider: Optional[str] = "codex"
    active_accounts: Dict[str, str] = field(default_factory=dict)
    active_account_id: Optional[str] = None
    accounts: List[Account] = field(default_factory=list)
    vscode_profiles: List[VSCodeProfileMapping] = field(default_factory=list)
    legacy_editor_environments: List[EditorEnvironment] = field(default_factory=list)

    @classmethod
    def empty(cls) -> "AppConfig":
        return cls()

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "AppConfig":
        version = int(raw.get("version", CONFIG_VERSION))
        if version > CONFIG_VERSION:
            raise ValueError(f"Config version {version} is newer than this amx version supports")
        active_provider = raw.get("activeProvider", raw.get("active_provider", "codex"))
        if active_provider is not None:
            active_provider = str(active_provider).lower()
            if active_provider not in SUPPORTED_PROVIDERS:
                raise ValueError(f"Unsupported active provider: {active_provider}")
        accounts = [Account.from_dict(item) for item in raw.get("accounts", [])]
        legacy_raw = raw.get("legacyEditorEnvironments", raw.get("environments", []))
        legacy_environments = [EditorEnvironment.from_dict(item) for item in legacy_raw]
        vscode_profiles = [VSCodeProfileMapping.from_dict(item) for item in raw.get("vscodeProfiles", [])]
        active_accounts = {str(k).lower(): str(v) for k, v in raw.get("activeAccounts", {}).items()}
        known_ids = {account.id for account in accounts}
        active_accounts = {provider: account_id for provider, account_id in active_accounts.items() if account_id in known_ids}
        active_account_id = raw.get("active_account_id")
        if active_account_id not in known_ids:
            active_account_id = None
        if not active_account_id and active_provider:
            active_account_id = active_accounts.get(active_provider)
        if version < 2:
            legacy_environments = cls._migrate_legacy_environments(accounts, legacy_environments)
        cls._normalize_environment_account_ids(accounts, legacy_environments)
        return cls(
            version=CONFIG_VERSION,
            active_provider=active_provider,
            active_accounts=active_accounts,
            active_account_id=active_account_id,
            accounts=accounts,
            vscode_profiles=vscode_profiles,
            legacy_editor_environments=legacy_environments,
        )

    @staticmethod
    def _migrate_legacy_environments(accounts: List[Account], environments: List[EditorEnvironment]) -> List[EditorEnvironment]:
        if environments:
            return environments
        migrated: List[EditorEnvironment] = []
        for account in accounts:
            user_data = account.metadata.get("legacy_vscode_user_data_dir")
            if not user_data:
                continue
            migrated.append(
                EditorEnvironment(
                    id=f"legacy-vscode-{account.id}",
                    name=f"{account.name} VS Code",
                    editor="vscode",
                    mode="isolated",
                    user_data_dir=str(user_data),
                    account_mode="pinned",
                    pinned_account_id=account.id,
                    account_ids={account.provider: account.id},
                    metadata={"imported_from": "v1_account_vscode_user_data_dir"},
                )
            )
        return migrated

    @staticmethod
    def _normalize_environment_account_ids(accounts: List[Account], environments: List[EditorEnvironment]) -> None:
        accounts_by_id = {account.id: account for account in accounts}
        for environment in environments:
            default_account_id = environment.account_ids.pop("default", None)
            if default_account_id:
                account = accounts_by_id.get(default_account_id)
                if account:
                    environment.account_ids.setdefault(account.provider, account.id)
            if environment.pinned_account_id:
                account = accounts_by_id.get(environment.pinned_account_id)
                if account:
                    environment.account_ids.setdefault(account.provider, account.id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "activeProvider": self.active_provider,
            "activeAccounts": self.active_accounts,
            "active_account_id": self.active_account_id,
            "accounts": [account.to_dict() for account in self.accounts],
            "vscodeProfiles": [profile.to_dict() for profile in self.vscode_profiles],
            "legacyEditorEnvironments": [environment.to_dict() for environment in self.legacy_editor_environments],
        }

    @property
    def environments(self) -> List[EditorEnvironment]:
        """Compatibility alias for legacy editor-context code."""
        return self.legacy_editor_environments

    @environments.setter
    def environments(self, value: List[EditorEnvironment]) -> None:
        self.legacy_editor_environments = value

    def provider_accounts(self, provider: Optional[str] = None) -> List[Account]:
        if provider is None:
            return list(self.accounts)
        provider = provider.lower()
        return [account for account in self.accounts if account.provider == provider]

    def find_account(self, provider: str, name_or_id: str) -> Account:
        provider = provider.lower()
        needle = name_or_id.lower()
        matches = [
            account
            for account in self.accounts
            if account.provider == provider and (account.id == name_or_id or account.name.lower() == needle)
        ]
        if not matches:
            raise KeyError(f"No {provider} account named {name_or_id!r}")
        if len(matches) > 1:
            raise KeyError(f"More than one {provider} account matches {name_or_id!r}; use the account id")
        return matches[0]

    def find_account_by_id(self, account_id: str) -> Account:
        for account in self.accounts:
            if account.id == account_id:
                return account
        raise KeyError(f"No account with id {account_id!r}")

    def active_account(self, provider: Optional[str] = None) -> Optional[Account]:
        if provider is None and self.active_account_id:
            for account in self.accounts:
                if account.id == self.active_account_id:
                    return account
        provider = (provider or self.active_provider or "").lower()
        account_id = self.active_accounts.get(provider)
        if not account_id:
            return None
        for account in self.accounts:
            if account.id == account_id:
                return account
        return None

    def set_active_account(self, account: Account) -> None:
        self.active_provider = account.provider
        self.active_account_id = account.id
        self.active_accounts[account.provider] = account.id

    def find_environment(self, name_or_id: str) -> EditorEnvironment:
        needle = name_or_id.lower()
        matches = [
            environment
            for environment in self.environments
            if environment.id == name_or_id or environment.name.lower() == needle
        ]
        if not matches:
            raise KeyError(f"No environment named {name_or_id!r}")
        if len(matches) > 1:
            raise KeyError(f"More than one environment matches {name_or_id!r}; use the environment id")
        return matches[0]

    def find_vscode_profile(self, name: str) -> VSCodeProfileMapping:
        needle = name.casefold()
        matches = [profile for profile in self.vscode_profiles if profile.profile_name.casefold() == needle]
        if not matches:
            raise KeyError(f"No AgentMux mapping for VS Code profile {name!r}")
        if len(matches) > 1:
            raise KeyError(f"More than one VS Code profile matches {name!r}")
        return matches[0]
