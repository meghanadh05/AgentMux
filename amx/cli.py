from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .codex_vscode import CodexVSCodeManager
from .config import ConfigStore


SUPPORTED_AGENTS = ("codex",)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="amx", formatter_class=argparse.RawDescriptionHelpFormatter,
                                     description="AgentMux - VS Code agent account switcher\n\n"
                                                 "Currently supports:\n  Codex")
    parser.add_argument("--config-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"AgentMux {__version__}")
    commands = parser.add_subparsers(dest="command")
    add = commands.add_parser("add", help="Register the current Codex authentication")
    add.add_argument("name", nargs="*", help="Account name; spaces are allowed")
    login_add = commands.add_parser("login-add", help=argparse.SUPPRESS)
    login_add.add_argument("name", nargs="+", help=argparse.SUPPRESS)
    list_command = commands.add_parser("list", help="List registered Codex accounts")
    list_command.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    switch = commands.add_parser("switch", help="Switch the agent account in VS Code")
    switch.add_argument("selection", nargs="*", help="Agent and account name; spaces are allowed")
    status = commands.add_parser("status", help="Show AgentMux status")
    status.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    rename = commands.add_parser("rename", help="Rename a saved account")
    rename.add_argument("account", nargs="*", help="Account name; spaces are allowed")
    rename.add_argument("--to", dest="new_name", help=argparse.SUPPRESS)
    remove = commands.add_parser("remove", help="Remove an account registration")
    remove.add_argument("account", nargs="*", help="Account name; spaces are allowed")
    remove.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)
    reauthenticate = commands.add_parser("reauthenticate", help="Update an account from current authentication")
    reauthenticate.add_argument("account", nargs="+", help="Account name; spaces are allowed")
    commands.add_parser("doctor", help="Check authentication switching readiness")
    commands.add_parser("setup", help="Install the cross-platform VS Code companion")
    return parser


def _manager(args: argparse.Namespace) -> CodexVSCodeManager:
    return CodexVSCodeManager(ConfigStore(args.config_dir, args.data_dir))


def _choose_account(manager: CodexVSCodeManager) -> str:
    accounts = manager.list_accounts()
    if not accounts:
        raise ValueError("No Codex accounts registered. Run `amx add ACCOUNT` first.")
    print("Select Codex account")
    for index, view in enumerate(accounts, 1):
        print(f"  {'*' if view.active else ' '} {index}. {view.account.name}")
    value = input("> ").strip()
    if value.isdigit() and 1 <= int(value) <= len(accounts):
        return accounts[int(value) - 1].account.id
    return value or next((v.account.id for v in accounts if v.active), accounts[0].account.id)


def _choose_agent() -> str:
    print("Select agent")
    for index, provider in enumerate(SUPPORTED_AGENTS, 1):
        print(f"  {index}. {provider.title()}")
    value = input("> ").strip()
    if value.isdigit() and 1 <= int(value) <= len(SUPPORTED_AGENTS):
        return SUPPORTED_AGENTS[int(value) - 1]
    if value.casefold() in SUPPORTED_AGENTS:
        return value.casefold()
    raise ValueError(f"Unsupported agent: {value or 'none'}")


def _switch_selection(manager: CodexVSCodeManager, values: list[str]) -> str:
    if not values:
        provider = _choose_agent()
        if provider != "codex":
            raise ValueError(f"Agent {provider!r} is not implemented yet.")
        return _choose_account(manager)
    if values[0].casefold() in SUPPORTED_AGENTS:
        provider = values.pop(0).casefold()
        if provider != "codex":
            raise ValueError(f"Agent {provider!r} is not implemented yet.")
        return " ".join(values).strip() or _choose_account(manager)
    return " ".join(values).strip()


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command is None:
        parser.print_help()
        return 0
    manager = _manager(args)
    try:
        if args.command == "add":
            name = " ".join(args.name).strip() or input("Account name: ").strip()
            account, _ = manager.add_account(name)
            print(f"Registered current Codex authentication as: {account.name}")
            return 0
        if args.command == "login-add":
            account = manager.login_and_add_account(" ".join(args.name))
            print(f"Authenticated and registered Codex account: {account.name}")
            return 0
        if args.command == "list":
            if args.json:
                print(json.dumps({"accounts": [
                    {"id": view.account.id, "provider": view.account.provider, "name": view.account.name,
                     "active": view.active, "ready": view.ready}
                    for view in manager.list_accounts()
                ]}))
                return 0
            print("Codex Accounts")
            for view in manager.list_accounts():
                print(f"  {'*' if view.active else ' '} {view.account.name:<18} {'Saved' if view.ready else 'Missing'}")
            return 0
        if args.command == "switch":
            selector = _switch_selection(manager, list(args.selection))
            result = manager.switch_account(selector)
            print(f"Switched default VS Code Codex account: {result.requested_account}")
            print("  Saved latest previous authentication state")
            print("  Activated target authentication atomically")
            print("  Reloaded Codex integration")
            for warning in result.warnings:
                print(f"  Warning: {warning}")
            return 0
        if args.command == "status":
            active = manager.get_active_account()
            loaded = active and manager._same_file(manager.live_auth, manager.account_auth(active))
            if args.json:
                print(json.dumps({"provider": "codex", "activeAccount": active.name if active else None,
                                  "activeAccountId": active.id if active else None, "loaded": bool(loaded)}))
                return 0
            print("AgentMux")
            print("  Target: Default VS Code Codex Extension")
            print(f"  Active account: {active.name if active else 'None'}")
            print(f"  Authentication: {'Loaded' if loaded else 'Unverified'}")
            return 0
        if args.command == "rename":
            selector = " ".join(args.account).strip() or _choose_account(manager)
            new_name = args.new_name or input("New account name: ").strip()
            renamed = manager.rename_account(selector, new_name)
            print(f"Renamed account: {renamed.name}")
            return 0
        if args.command == "reauthenticate":
            selector = " ".join(args.account).strip()
            account = manager.reauthenticate_account(selector)
            print(f"Updated authentication for: {account.name}")
            return 0
        if args.command == "remove":
            selector = " ".join(args.account).strip() or _choose_account(manager)
            account = manager.store.load().find_account("codex", selector)
            if not args.yes and input(f'Remove "{account.name}"? [y/N]: ').strip().casefold() not in {"y", "yes"}:
                print("Removal cancelled.")
                return 0
            removed = manager.remove_account(account.id, delete_data=manager.account_data_is_managed(account))
            print(f"Removed account: {removed.name}")
            return 0
        if args.command == "doctor":
            report = manager.doctor()
            print("AgentMux Doctor")
            print(f"  Default Codex home: {'Ready' if report['default_codex_home'] else 'Missing'}")
            print(f"  VS Code Codex extension: {'Ready' if report['codex_extension'] else 'Missing'}")
            print(f"  AgentMux VS Code companion: {'Installed' if report['companion'] else 'Missing'}")
            print(f"  VS Code Codex app-server: {'Detected' if report['app_server'] else 'Not detected'}")
            print(f"  Reload mechanism: {'Ready' if report['refresh'] else 'Unavailable'}")
            print(f"  Recovery: {'Ready' if report['recovery'] else 'Created on first switch'}")
            print(f"  Accounts: {sum(v.ready for v in report['accounts'])} saved")
            print(f"  Active: {report['active'].name if report['active'] else 'None'}")
            ready = all((report["default_codex_home"], report["codex_extension"], report["app_server"], report["refresh"]))
            return 0 if ready else 1
        if args.command == "setup":
            destination = manager.install_companion()
            print(f"Installed AgentMux VS Code companion: {destination}")
            print("Restart VS Code once to activate cross-platform switching.")
            return 0
    except (ValueError, KeyError, FileNotFoundError) as exc:
        print(f"Error: {exc.args[0] if exc.args else str(exc)}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
