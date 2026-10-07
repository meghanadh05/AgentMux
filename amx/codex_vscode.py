from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from .config import ConfigStore
from .models import Account
from .paths import data_dir
from .security import ensure_private_dir
from .vscode import find_code_command


AUTH_FILE = "auth.json"


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except (AttributeError, OSError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError as exc:
        return exc.errno == errno.EPERM


class RefreshMethod(str, Enum):
    NONE = "none"
    WINDOW_RELOAD = "window-reload"


@dataclass(frozen=True)
class SwitchResult:
    previous_account: Optional[str]
    requested_account: str
    auth_ready: bool
    refresh_method: RefreshMethod
    vscode_running: bool
    integration_restarted: bool
    identity_verified: bool
    success: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AccountView:
    account: Account
    ready: bool
    active: bool


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int
    kind: str
    command: str


@dataclass(frozen=True)
class CompanionBridge:
    host: str
    port: int
    token: str


class CodexVSCodeManager:
    def __init__(
        self,
        store: ConfigStore,
        *,
        codex_home: Optional[Path] = None,
        pairing_root: Optional[Path] = None,
        companion_root: Optional[Path] = None,
        refresh: Optional[Callable[[], bool]] = None,
        login_status: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.store = store
        self.data_root = data_dir(store.data_root)
        self.codex_home = codex_home or Path.home() / ".codex"
        self.pairing_root = pairing_root or (
            Path.home() / "Library/Application Support/com.openai.chat/app_pairing_extensions"
        )
        self.companion_root = companion_root or Path.home() / ".agentmux" / "bridges"
        self.live_auth = self.codex_home / AUTH_FILE
        self._refresh = refresh or self.reload_default_vscode
        self._login_status = login_status or self.codex_login_ready

    def list_accounts(self) -> list[AccountView]:
        config = self.store.load()
        active_id = config.active_accounts.get("codex")
        return [AccountView(account, self.account_auth(account).is_file(), account.id == active_id)
                for account in config.provider_accounts("codex")]

    def get_active_account(self) -> Optional[Account]:
        return self.store.load().active_account("codex")

    def add_account(self, name: str, *, authenticate: bool = True) -> tuple[Account, int]:
        del authenticate
        name = name.strip()
        if not name:
            raise ValueError("Account name cannot be empty.")
        self._validate_auth(self.live_auth, "Current Codex")
        config = self.store.load()
        account = self.store.create_account(config, "codex", name)
        account.metadata = {"surface": "default-vscode", "auth_artifact": AUTH_FILE}
        ensure_private_dir(Path(account.home))
        self._atomic_copy(self.live_auth, self.account_auth(account))
        config.set_active_account(account)
        self.store.save(config)
        return account, 0

    def login_and_add_account(self, name: str, *, cancel_file: Optional[Path] = None) -> Account:
        name = name.strip()
        if not name:
            raise ValueError("Account name cannot be empty.")
        has_existing_auth = self.live_auth.is_file()
        if has_existing_auth:
            self._validate_auth(self.live_auth, "Current Codex")
        codex = self._codex_command()
        if not codex:
            raise FileNotFoundError("The Codex CLI was not found.")
        config = self.store.load()
        if any(item.provider == "codex" and item.name.casefold() == name.casefold() for item in config.accounts):
            raise ValueError(f"A Codex account named {name!r} already exists.")
        previous = config.active_account("codex")

        with self._switch_lock(), tempfile.TemporaryDirectory(prefix="amx-codex-login-") as login_directory:
            recovery = self._recovery_path() if has_existing_auth else None
            if recovery:
                self._atomic_copy(self.live_auth, recovery)
            if previous and has_existing_auth:
                ensure_private_dir(Path(previous.home))
                self._atomic_copy(self.live_auth, self.account_auth(previous))
            env = os.environ.copy()
            login_home = Path(login_directory)
            env["CODEX_HOME"] = str(login_home)
            try:
                result = self._run_codex_login(codex, env, cancel_file)
                if result.returncode:
                    detail = (result.stderr or result.stdout).strip()
                    raise RuntimeError(detail or "Codex login did not complete.")
                login_auth = login_home / AUTH_FILE
                self._validate_auth(login_auth, "New Codex account")
                self._atomic_copy(login_auth, self.live_auth)
                if not self._refresh():
                    raise RuntimeError("VS Code did not accept the new Codex authentication")
                if not self._login_status():
                    raise RuntimeError("Codex did not report an authenticated session")
            except Exception as exc:
                if recovery and recovery.is_file():
                    self._atomic_copy(recovery, self.live_auth)
                    try:
                        self._refresh()
                    except Exception:
                        pass
                    detail = "Login failed and previous authentication was restored"
                else:
                    detail = "Login failed without changing the existing account state"
                raise ValueError(f"{detail}: {exc}") from exc

            latest = self.store.load()
            account = self.store.create_account(latest, "codex", name)
            account.metadata = {"surface": "default-vscode", "auth_artifact": AUTH_FILE}
            ensure_private_dir(Path(account.home))
            self._atomic_copy(self.live_auth, self.account_auth(account))
            latest.set_active_account(account)
            self.store.save(latest)
        return account

    @staticmethod
    def _run_codex_login(codex: str, env: dict[str, str], cancel_file: Optional[Path]):
        if cancel_file is None:
            return subprocess.run(
                [codex, "login"], capture_output=True, text=True, check=False, timeout=600, env=env
            )

        process = subprocess.Popen([codex, "login"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=env)
        deadline = time.monotonic() + 600
        while process.poll() is None:
            if cancel_file.exists():
                process.terminate()
                stdout, stderr = process.communicate(timeout=15)
                return subprocess.CompletedProcess([codex, "login"], 1, stdout, stderr or "Sign-in cancelled.")
            if time.monotonic() >= deadline:
                process.terminate()
                stdout, stderr = process.communicate(timeout=15)
                return subprocess.CompletedProcess([codex, "login"], 1, stdout, stderr or "Codex login timed out.")
            time.sleep(0.1)
        stdout, stderr = process.communicate()
        return subprocess.CompletedProcess([codex, "login"], process.returncode, stdout, stderr)

    def switch_account(self, selector: str, targets: Optional[list[str]] = None) -> SwitchResult:
        del targets
        config = self.store.load()
        previous = config.active_account("codex")
        target = config.find_account("codex", selector)
        target_auth = self.account_auth(target)
        self._validate_auth(target_auth, target.name)
        self._validate_auth(self.live_auth, "Current Codex")
        if previous and previous.id == target.id and self._same_file(self.live_auth, target_auth):
            return SwitchResult(previous.name, target.name, True, RefreshMethod.NONE, self.default_vscode_running(),
                                False, True, True)

        with self._switch_lock():
            recovery = self._recovery_path()
            self._atomic_copy(self.live_auth, recovery)
            if previous:
                ensure_private_dir(Path(previous.home))
                self._atomic_copy(self.live_auth, self.account_auth(previous))
            self._atomic_copy(target_auth, self.live_auth)
            config.set_active_account(target)
            self.store.save(config)
            try:
                if not self._refresh():
                    raise RuntimeError("a new Codex app-server was not detected")
                if not self._login_status():
                    raise RuntimeError("Codex did not report an authenticated session")
            except Exception as exc:
                self._atomic_copy(recovery, self.live_auth)
                rollback = self.store.load()
                if previous:
                    rollback.set_active_account(rollback.find_account("codex", previous.id))
                self.store.save(rollback)
                try:
                    self._refresh()
                except Exception:
                    pass
                raise ValueError(f"Switch failed and authentication was restored: {exc}") from exc

        return SwitchResult(previous.name if previous else None, target.name, True, RefreshMethod.WINDOW_RELOAD,
                            True, True, False, True,
                            ["Authentication loaded; account name could not be independently verified."])

    def remove_account(self, selector: str, *, delete_data: bool = False) -> Account:
        config = self.store.load()
        account = config.find_account("codex", selector)
        if config.active_accounts.get("codex") == account.id:
            raise ValueError("Cannot remove the active account. Switch to another account first.")
        config.accounts = [item for item in config.accounts if item.id != account.id]
        self.store.save(config)
        if delete_data and Path(account.home).exists():
            shutil.rmtree(account.home)
        return account

    def rename_account(self, selector: str, new_name: str) -> Account:
        name = new_name.strip()
        if not name:
            raise ValueError("Account name cannot be empty.")
        config = self.store.load()
        account = config.find_account("codex", selector)
        if any(item.id != account.id and item.provider == "codex" and item.name.casefold() == name.casefold()
               for item in config.accounts):
            raise ValueError(f"A Codex account named {name!r} already exists.")
        account.name = name
        self.store.save(config)
        return account

    def reauthenticate_account(self, selector: str) -> Account:
        self._validate_auth(self.live_auth, "Current Codex")
        config = self.store.load()
        account = config.find_account("codex", selector)
        ensure_private_dir(Path(account.home))
        self._atomic_copy(self.live_auth, self.account_auth(account))
        config.set_active_account(account)
        self.store.save(config)
        return account

    def account_data_is_managed(self, account: Account) -> bool:
        try:
            Path(account.home).resolve().relative_to((self.data_root / "providers" / "codex").resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def account_auth(account: Account) -> Path:
        return Path(account.home) / AUTH_FILE

    def _recovery_path(self) -> Path:
        root = self.data_root / "recovery"
        ensure_private_dir(root)
        return root / f"auth-{time.time_ns()}.json"

    def _switch_lock(self):
        return _ExclusiveLock(self.data_root / "switch.lock")

    @staticmethod
    def _validate_auth(path: Path, label: str) -> None:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'{label} authentication artifact is missing or unsafe.')
        if path.stat().st_size < 2:
            raise ValueError(f'{label} authentication artifact is empty.')
        try:
            with path.open("rb") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f'{label} authentication artifact is invalid.') from exc
        if not isinstance(value, dict):
            raise ValueError(f'{label} authentication artifact is invalid.')

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> None:
        ensure_private_dir(destination.parent)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".auth-", dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            if os.name != "nt":
                destination.chmod(0o600)
            if os.name != "nt":
                directory = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _same_file(left: Path, right: Path) -> bool:
        def digest(path: Path) -> bytes:
            value = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    value.update(chunk)
            return value.digest()
        return digest(left) == digest(right)

    def codex_login_ready(self) -> bool:
        codex = self._codex_command()
        if not codex:
            return False
        try:
            result = subprocess.run([codex, "login", "status"], capture_output=True, text=True, timeout=15,
                                    check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and "logged in" in (result.stdout + result.stderr).casefold()

    @staticmethod
    def _codex_command() -> Optional[str]:
        configured = os.environ.get("AMX_CODEX_COMMAND", "").strip()
        return configured or shutil.which("codex")

    def reload_default_vscode(self) -> bool:
        before = self.default_app_server_pids()
        try:
            self._send_companion_reload(self.companion_bridge())
            # The companion reloads after a short grace period so an integrated
            # terminal command can validate, release its lock, and print output.
            return True
        except FileNotFoundError:
            self._send_reload(self.reload_bridge_socket())
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            time.sleep(0.5)
            current = self.default_app_server_pids()
            if current and not current.issubset(before):
                return True
        return False

    def companion_bridge(self) -> CompanionBridge:
        candidates: list[tuple[object, float, CompanionBridge]] = []
        if not self.companion_root.is_dir():
            raise FileNotFoundError("The AgentMux VS Code companion bridge was not found.")
        for registration in self.companion_root.glob("vscode-*.json"):
            try:
                value = json.loads(registration.read_text(encoding="utf-8"))
                if value.get("protocol") != "agentmux-v1" or value.get("host") != "127.0.0.1":
                    continue
                pid = int(value["pid"])
                if not _pid_is_alive(pid):
                    registration.unlink(missing_ok=True)
                    continue
                port = int(value["port"])
                token = str(value["token"])
                if not 1 <= port <= 65535 or len(token) < 32:
                    continue
                bridge = CompanionBridge("127.0.0.1", port, token)
                candidates.append((value.get("workspaceName"), self._registration_timestamp(value, registration),
                                   bridge))
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return self._select_bridge(candidates, "AgentMux VS Code companion")

    @staticmethod
    def _select_bridge(candidates, label):
        workspace = Path.cwd().name
        matching = [item for item in candidates if item[0] == workspace]
        if matching:
            return max(matching, key=lambda item: item[1])[2]
        if len(candidates) == 1:
            return candidates[0][2]
        if not candidates:
            raise FileNotFoundError(f"No active {label} bridge was found.")
        raise ValueError("Multiple VS Code windows are active; run amx from the target workspace.")

    @staticmethod
    def _send_companion_reload(bridge: CompanionBridge) -> None:
        request = json.dumps({"command": "reload", "token": bridge.token}, separators=(",", ":")) + "\n"
        try:
            with socket.create_connection((bridge.host, bridge.port), timeout=5) as connection:
                connection.sendall(request.encode("utf-8"))
                response = bytearray()
                while len(response) <= 1024 * 1024 and not response.endswith(b"\n"):
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    response.extend(chunk)
            if len(response) > 1024 * 1024:
                raise ValueError("AgentMux companion returned an oversized response.")
            value = json.loads(response)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Could not contact the AgentMux VS Code companion.") from exc
        if not isinstance(value, dict) or value.get("status") != "success":
            raise ValueError("The AgentMux VS Code companion refused the reload request.")

    def reload_bridge_socket(self) -> Path:
        candidates: list[tuple[object, float, Path]] = []
        if not self.pairing_root.is_dir():
            raise FileNotFoundError("The Codex extension reload bridge was not found.")
        for registration in self.pairing_root.glob("Visual Studio Code-*"):
            try:
                value = json.loads(registration.read_text(encoding="utf-8"))
                socket_path = Path(value["socketPath"])
                normalized = os.path.normpath(str(socket_path))
                if value.get("bundleID") != "com.microsoft.VSCode":
                    continue
                if value.get("capabilities", {}).get("reload") != 1:
                    continue
                if not normalized.startswith("/tmp/Visual Studio Code-"):
                    continue
                if not socket_path.is_socket():
                    continue
                candidates.append((value.get("workspaceName"), self._registration_timestamp(value, registration),
                                   socket_path))
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue

        return self._select_bridge(candidates, "default VS Code Codex")

    @staticmethod
    def _registration_timestamp(value: dict[str, object], registration: Path) -> float:
        timestamp = value.get("timestamp")
        if isinstance(timestamp, (int, float)):
            return float(timestamp)
        if isinstance(timestamp, str):
            try:
                return float(timestamp)
            except ValueError:
                pass
        return registration.stat().st_mtime

    @staticmethod
    def _read_exact(connection: socket.socket, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = connection.recv(length - len(chunks))
            if not chunk:
                raise ValueError("Codex extension reload bridge closed unexpectedly.")
            chunks.extend(chunk)
        return bytes(chunks)

    @classmethod
    def _send_reload(cls, socket_path: Path) -> None:
        payload = json.dumps({"command": "reload"}, separators=(",", ":")).encode("utf-8")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(5)
                connection.connect(str(socket_path))
                connection.sendall(struct.pack("<I", len(payload)) + payload)
                response_length = struct.unpack("<I", cls._read_exact(connection, 4))[0]
                if response_length > 1024 * 1024:
                    raise ValueError("Codex extension reload bridge returned an oversized response.")
                response = json.loads(cls._read_exact(connection, response_length))
        except (OSError, struct.error, json.JSONDecodeError) as exc:
            raise ValueError("Could not contact the Codex extension reload bridge.") from exc
        if not isinstance(response, dict) or response.get("status") != "success":
            raise ValueError("The Codex extension refused the reload request.")

    def default_vscode_running(self) -> bool:
        return bool(self.default_app_server_pids())

    def default_app_server_pids(self) -> set[int]:
        processes = self.inspect_processes()
        commands = {item.pid: item.command for item in processes}
        return {item.pid for item in processes if item.kind == "vscode-codex"
                and "--user-data-dir" in commands.get(item.ppid, "")
                and self._is_default_vscode_command(commands.get(item.ppid, ""))}

    @staticmethod
    def _is_default_vscode_command(command: str) -> bool:
        lowered = command.casefold().replace("\\", "/")
        while "//" in lowered:
            lowered = lowered.replace("//", "/")
        markers = ("/application support/code", "/.config/code", "/appdata/roaming/code")
        return any(marker in lowered for marker in markers)

    @staticmethod
    def classify_process(pid: int, ppid: int, command: str) -> ProcessInfo:
        lowered = command.casefold()
        executable = command.split(maxsplit=1)[0] if command.strip() else ""
        if "openai.chatgpt-" in lowered and "app-server" in lowered:
            kind = "vscode-codex"
        elif executable and Path(executable).name.casefold() in {"codex", "codex.exe"}:
            kind = "terminal-codex"
        elif "visual studio code" in lowered or "code helper" in lowered:
            kind = "vscode"
        else:
            kind = "unknown"
        return ProcessInfo(pid, ppid, kind, command)

    @classmethod
    def inspect_processes(cls) -> list[ProcessInfo]:
        if os.name == "nt":
            return cls._inspect_windows_processes()
        try:
            result = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, check=False)
        except OSError:
            return []
        output = []
        for line in result.stdout.splitlines():
            fields = line.strip().split(None, 2)
            if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
                output.append(cls.classify_process(int(fields[0]), int(fields[1]), fields[2]))
        return output

    @classmethod
    def _inspect_windows_processes(cls) -> list[ProcessInfo]:
        command = ["powershell", "-NoProfile", "-Command",
                   "Get-CimInstance Win32_Process | Select ProcessId,ParentProcessId,CommandLine | ConvertTo-Json"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=15)
            values = json.loads(result.stdout or "[]")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return []
        if isinstance(values, dict):
            values = [values]
        return [cls.classify_process(int(item["ProcessId"]), int(item["ParentProcessId"]),
                                     str(item.get("CommandLine") or "")) for item in values]

    @staticmethod
    def extension_installed() -> bool:
        root = Path.home() / ".vscode" / "extensions"
        return root.exists() and any(root.glob("openai.chatgpt-*/package.json"))

    @staticmethod
    def companion_installed() -> bool:
        root = Path.home() / ".vscode" / "extensions"
        patterns = (
            "megdev.agentmux-amx-*", "megdev.agent-mux-*",
            "megdev.amx-agent-account-manager-*", "agentmux.agentmux-vscode-*",
        )
        return root.exists() and any(
            package for pattern in patterns for package in root.glob(f"{pattern}/package.json")
        )

    @staticmethod
    def install_companion() -> Path:
        source = Path(__file__).with_name("vscode_extension")
        package = source / "agentmux-vscode.vsix"
        if not package.is_file():
            raise FileNotFoundError("The bundled AgentMux VS Code extension package is missing.")
        code = find_code_command()
        if not code:
            raise FileNotFoundError(
                "VS Code's 'code' command was not found. Install it from the VS Code Command Palette first."
            )
        try:
            result = subprocess.run(
                [code, "--install-extension", str(package), "--force"],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("VS Code could not install the AgentMux companion.") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise ValueError(detail or "VS Code could not install the AgentMux companion.")
        return package

    def doctor(self) -> dict[str, object]:
        try:
            try:
                self.companion_bridge()
            except FileNotFoundError:
                self.reload_bridge_socket()
            refresh_ready = True
        except (FileNotFoundError, ValueError):
            refresh_ready = False
        return {"vscode_cli": find_code_command(), "codex_binary": shutil.which("codex"),
                "codex_extension": self.extension_installed(), "default_codex_home": self.codex_home.is_dir(),
                "companion": self.companion_installed(),
                "app_server": self.default_vscode_running(), "accounts": self.list_accounts(),
                "active": self.get_active_account(), "recovery": (self.data_root / "recovery").is_dir(),
                "refresh": refresh_ready}


class _ExclusiveLock:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self):
        ensure_private_dir(self.path.parent)
        for attempt in range(2):
            try:
                self.descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError as exc:
                if attempt or self._owner_is_alive():
                    raise ValueError("Another AgentMux switch is already in progress.") from exc
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
        os.write(self.descriptor, str(os.getpid()).encode("ascii"))
        return self

    def _owner_is_alive(self) -> bool:
        try:
            owner = int(self.path.read_text(encoding="ascii").strip())
        except ValueError:
            return False
        return _pid_is_alive(owner)

    def __exit__(self, exc_type, exc, traceback) -> None:
        os.close(self.descriptor)
        self.path.unlink(missing_ok=True)
