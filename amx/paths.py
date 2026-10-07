from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Optional


APP_NAME = "amx"


def user_home() -> Path:
    return Path.home()


def platform_name() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system.startswith("win"):
        return "windows"
    if system == "linux":
        return "linux"
    return system or "unknown"


def config_dir(base: Optional[Path] = None) -> Path:
    if base:
        return base
    override = os.environ.get("AMX_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    system = platform_name()
    if system == "macos":
        return user_home() / "Library" / "Application Support" / APP_NAME
    if system == "windows":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(user_home() / "AppData" / "Local")
        return Path(root) / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg).expanduser() if xdg else user_home() / ".config") / APP_NAME


def data_dir(base: Optional[Path] = None) -> Path:
    if base:
        return base
    override = os.environ.get("AMX_DATA_DIR")
    if override:
        return Path(override).expanduser()
    system = platform_name()
    if system == "macos":
        return config_dir()
    if system == "windows":
        return config_dir()
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg).expanduser() if xdg else user_home() / ".local" / "share") / APP_NAME


def config_file(config_root: Optional[Path] = None) -> Path:
    return config_dir(config_root) / "config.json"


def provider_home(provider: str, account_id: str, data_root: Optional[Path] = None) -> Path:
    return data_dir(data_root) / "providers" / provider.lower() / account_id


def vscode_user_data(account_id: str, data_root: Optional[Path] = None) -> Path:
    return data_dir(data_root) / "vscode" / account_id

