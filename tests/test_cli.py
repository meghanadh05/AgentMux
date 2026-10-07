from io import StringIO
import json
import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from amx.cli import main
from amx.codex_vscode import CompanionBridge, CodexVSCodeManager, ProcessInfo, RefreshMethod, _ExclusiveLock
from amx.config import ConfigStore


def write_auth(path: Path, identity: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fixture_identity": identity}), encoding="utf-8")
    path.chmod(0o600)


class AuthSwitchTests(unittest.TestCase):
    def manager(self, root: Path, *, refresh=lambda: True, login_status=lambda: True) -> CodexVSCodeManager:
        return CodexVSCodeManager(ConfigStore(root / "config", root / "data"), codex_home=root / "codex",
                                  refresh=refresh, login_status=login_status)

    def register(self, manager: CodexVSCodeManager, name: str, identity: str):
        write_auth(manager.live_auth, identity)
        return manager.add_account(name)[0]

    def test_add_registers_current_opaque_auth(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            account = self.register(manager, "Personal", "personal")
            self.assertEqual(manager.account_auth(account).read_bytes(), manager.live_auth.read_bytes())
            if os.name != "nt":
                self.assertEqual(manager.account_auth(account).stat().st_mode & 0o777, 0o600)
            self.assertEqual(manager.get_active_account().name, "Personal")

    def test_login_add_preserves_previous_and_saves_new_authentication(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            previous = self.register(manager, "Personal", "personal-latest")

            def login(*args, **kwargs):
                write_auth(Path(kwargs["env"]["CODEX_HOME"]) / "auth.json", "work")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("amx.codex_vscode.shutil.which", return_value="codex"), \
                    patch("amx.codex_vscode.subprocess.run", side_effect=login) as run:
                account = manager.login_and_add_account("Work")
            self.assertIn("personal-latest", manager.account_auth(previous).read_text())
            self.assertIn("work", manager.account_auth(account).read_text())
            self.assertEqual(manager.get_active_account().id, account.id)
            self.assertEqual(run.call_args.args[0], ["codex", "login"])
            self.assertNotEqual(run.call_args.kwargs["env"]["CODEX_HOME"], str(manager.codex_home))

    def test_login_add_restores_previous_authentication_on_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            previous = self.register(manager, "Personal", "personal")

            def failed_login(*args, **kwargs):
                write_auth(Path(kwargs["env"]["CODEX_HOME"]) / "auth.json", "partial")
                return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "cancelled"})()

            with patch("amx.codex_vscode.shutil.which", return_value="codex"), \
                    patch("amx.codex_vscode.subprocess.run", side_effect=failed_login):
                with self.assertRaisesRegex(ValueError, "previous authentication was restored"):
                    manager.login_and_add_account("Work")
            self.assertIn("personal", manager.live_auth.read_text())
            self.assertEqual(manager.get_active_account().id, previous.id)
            self.assertEqual([view.account.name for view in manager.list_accounts()], ["Personal"])

    def test_login_add_allows_the_first_account_on_a_fresh_machine(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))

            def login(*args, **kwargs):
                write_auth(Path(kwargs["env"]["CODEX_HOME"]) / "auth.json", "first-account")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("amx.codex_vscode.shutil.which", return_value="codex"), \
                    patch("amx.codex_vscode.subprocess.run", side_effect=login):
                account = manager.login_and_add_account("Personal")
            self.assertEqual(account.name, "Personal")
            self.assertIn("first-account", manager.live_auth.read_text())
            self.assertEqual(manager.get_active_account().id, account.id)

    def test_login_add_cancellation_restores_previous_authentication(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.manager(root)
            previous = self.register(manager, "Personal", "personal")
            cancel_file = root / "cancel"
            cancel_file.write_text("cancelled", encoding="ascii")

            class LoginProcess:
                returncode = None

                def poll(self): return None
                def terminate(self): self.terminated = True
                def communicate(self, timeout=None): return "", ""

            with patch("amx.codex_vscode.shutil.which", return_value="codex"), \
                    patch("amx.codex_vscode.subprocess.Popen", return_value=LoginProcess()):
                with self.assertRaisesRegex(ValueError, "previous authentication was restored"):
                    manager.login_and_add_account("Work", cancel_file=cancel_file)
            self.assertIn("personal", manager.live_auth.read_text())
            self.assertEqual(manager.get_active_account().id, previous.id)
            self.assertEqual([view.account.name for view in manager.list_accounts()], ["Personal"])

    def test_switch_saves_latest_current_and_activates_target(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            personal = self.register(manager, "Personal", "personal-old")
            college = self.register(manager, "College", "college")
            config = manager.store.load(); config.set_active_account(personal); manager.store.save(config)
            write_auth(manager.live_auth, "personal-refreshed")
            result = manager.switch_account("College")
            self.assertTrue(result.success)
            self.assertEqual(result.refresh_method, RefreshMethod.WINDOW_RELOAD)
            self.assertIn("personal-refreshed", manager.account_auth(personal).read_text())
            self.assertEqual(manager.live_auth.read_bytes(), manager.account_auth(college).read_bytes())
            self.assertEqual(manager.get_active_account().name, "College")
            self.assertTrue(any((manager.data_root / "recovery").iterdir()))

    def test_switch_does_not_touch_shared_codex_state(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            personal = self.register(manager, "Personal", "personal")
            college = self.register(manager, "College", "college")
            config = manager.store.load(); config.set_active_account(personal); manager.store.save(config)
            shared = manager.codex_home / "thread_history_1.sqlite"
            shared.write_bytes(b"shared-history")
            manager.switch_account(college.id)
            self.assertEqual(shared.read_bytes(), b"shared-history")

    def test_failed_refresh_rolls_back_auth_and_active_account(self) -> None:
        with TemporaryDirectory() as tmp:
            calls = []
            manager = self.manager(Path(tmp), refresh=lambda: calls.append(True) or False)
            personal = self.register(manager, "Personal", "personal")
            self.register(manager, "College", "college")
            config = manager.store.load(); config.set_active_account(personal); manager.store.save(config)
            write_auth(manager.live_auth, "personal-latest")
            with self.assertRaisesRegex(ValueError, "restored"):
                manager.switch_account("College")
            self.assertIn("personal-latest", manager.live_auth.read_text())
            self.assertEqual(manager.get_active_account().name, "Personal")
            self.assertEqual(len(calls), 2)

    def test_failed_login_status_rolls_back(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp), login_status=lambda: False)
            personal = self.register(manager, "Personal", "personal")
            self.register(manager, "College", "college")
            config = manager.store.load(); config.set_active_account(personal); manager.store.save(config)
            with self.assertRaisesRegex(ValueError, "restored"):
                manager.switch_account("College")
            self.assertEqual(manager.get_active_account().name, "Personal")

    def test_switch_to_loaded_active_account_is_noop(self) -> None:
        with TemporaryDirectory() as tmp:
            refreshed = []
            manager = self.manager(Path(tmp), refresh=lambda: refreshed.append(True) or True)
            self.register(manager, "Personal", "personal")
            result = manager.switch_account("Personal")
            self.assertEqual(result.refresh_method, RefreshMethod.NONE)
            self.assertFalse(refreshed)

    def test_missing_target_auth_is_rejected_before_live_change(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            personal = self.register(manager, "Personal", "personal")
            college = self.register(manager, "College", "college")
            config = manager.store.load(); config.set_active_account(personal); manager.store.save(config)
            manager.account_auth(college).unlink()
            before = manager.live_auth.read_bytes()
            with self.assertRaisesRegex(ValueError, "missing or unsafe"):
                manager.switch_account("College")
            self.assertEqual(manager.live_auth.read_bytes(), before)

    def test_concurrent_switch_lock_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            lock = Path(tmp) / "switch.lock"
            with _ExclusiveLock(lock):
                with self.assertRaisesRegex(ValueError, "already in progress"):
                    with _ExclusiveLock(lock):
                        pass

    def test_stale_switch_lock_is_reclaimed(self) -> None:
        with TemporaryDirectory() as tmp:
            lock = Path(tmp) / "switch.lock"
            lock.write_text("999999999", encoding="ascii")
            with patch("amx.codex_vscode.os.kill", side_effect=ProcessLookupError):
                with _ExclusiveLock(lock):
                    self.assertEqual(lock.read_text(encoding="ascii"), str(os.getpid()))
            self.assertFalse(lock.exists())

    def test_remove_active_account_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            self.register(manager, "Personal", "personal")
            with self.assertRaisesRegex(ValueError, "active account"):
                manager.remove_account("Personal")

    def test_rename_account_allows_spaces(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            account = self.register(manager, "Work", "work")
            renamed = manager.rename_account(account.id, "College Account")
            self.assertEqual(renamed.name, "College Account")
            self.assertEqual(manager.get_active_account().name, "College Account")

    def test_cli_rename_prompts_for_new_name(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.manager(root)
            self.register(manager, "Work Account", "work")
            with patch("amx.cli._manager", return_value=manager), patch("builtins.input", return_value="Personal Main"):
                self.assertEqual(main(["rename", "Work", "Account"]), 0)
            self.assertEqual(manager.get_active_account().name, "Personal Main")

    def test_cli_rename_accepts_noninteractive_name(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            account = self.register(manager, "Work", "work")
            with patch("amx.cli._manager", return_value=manager):
                self.assertEqual(main(["rename", account.id, "--to", "Personal Main"]), 0)
            self.assertEqual(manager.get_active_account().name, "Personal Main")

    def test_reauthenticate_replaces_saved_authentication(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            account = self.register(manager, "Personal", "old")
            write_auth(manager.live_auth, "new")
            with patch("amx.cli._manager", return_value=manager):
                self.assertEqual(main(["reauthenticate", account.id]), 0)
            self.assertIn("new", manager.account_auth(account).read_text())

    def test_cli_remove_accepts_unquoted_spaced_name_and_cleans_data(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.manager(root)
            old = self.register(manager, "Old Account", "old")
            self.register(manager, "Current", "current")
            with patch("amx.cli._manager", return_value=manager), patch("builtins.input", return_value="yes"):
                self.assertEqual(main(["remove", "Old", "Account"]), 0)
            self.assertFalse(Path(old.home).exists())
            self.assertEqual([view.account.name for view in manager.list_accounts()], ["Current"])

    def test_cli_switch_prompts_for_agent_then_account(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            first = self.register(manager, "Personal", "personal")
            self.register(manager, "Work Account", "work")
            with patch("amx.cli._manager", return_value=manager), \
                    patch("builtins.input", side_effect=["1", "1"]):
                self.assertEqual(main(["switch"]), 0)
            self.assertEqual(manager.get_active_account().id, first.id)

    def test_cli_switch_accepts_agent_and_unquoted_account(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            target = self.register(manager, "Work Account", "work")
            self.register(manager, "Personal", "personal")
            with patch("amx.cli._manager", return_value=manager):
                self.assertEqual(main(["switch", "codex", "Work", "Account"]), 0)
            self.assertEqual(manager.get_active_account().id, target.id)

    def test_cli_json_output_is_safe_for_vscode_extension(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            self.register(manager, "Personal", "secret-fixture")
            output = StringIO()
            with patch("amx.cli._manager", return_value=manager), patch("sys.stdout", output):
                self.assertEqual(main(["list", "--json"]), 0)
            value = json.loads(output.getvalue())
            self.assertEqual(value["accounts"][0]["name"], "Personal")
            self.assertNotIn("secret-fixture", output.getvalue())

            output = StringIO()
            with patch("amx.cli._manager", return_value=manager), patch("sys.stdout", output):
                self.assertEqual(main(["status", "--json"]), 0)
            self.assertEqual(json.loads(output.getvalue())["activeAccount"], "Personal")

    def test_managed_account_data_is_detected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.manager(root)
            account = self.register(manager, "Personal", "personal")
            self.assertTrue(manager.account_data_is_managed(account))
            account.provider_home = str(manager.codex_home)
            self.assertFalse(manager.account_data_is_managed(account))

    def test_cli_surface_is_small(self) -> None:
        output = StringIO()
        with patch("sys.stdout", output), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        text = output.getvalue()
        for command in ("add", "list", "switch", "status", "rename", "remove", "doctor", "setup"):
            self.assertIn(command, text)
        for removed in ("open", "claude", "profile", "alias", "migrate", "run"):
            self.assertNotIn(removed, text)

    def test_process_classification_does_not_confuse_terminal_codex(self) -> None:
        extension = CodexVSCodeManager.classify_process(1, 10, "/x/openai.chatgpt-1/bin/codex app-server")
        terminal = CodexVSCodeManager.classify_process(2, 20, "/opt/homebrew/bin/codex")
        unknown = CodexVSCodeManager.classify_process(3, 30, "/tmp/codex-helper")
        empty = CodexVSCodeManager.classify_process(4, 40, "")
        self.assertEqual([extension.kind, terminal.kind, unknown.kind, empty.kind],
                         ["vscode-codex", "terminal-codex", "unknown", "unknown"])

    @unittest.skipIf(os.name == "nt", "legacy reload bridge uses Unix-domain sockets")
    def test_reload_bridge_prefers_current_workspace_and_newest_registration(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pairing = root / "pairing"
            pairing.mkdir()
            manager = CodexVSCodeManager(ConfigStore(root / "config", root / "data"),
                                          codex_home=root / "codex", pairing_root=pairing)
            for index, (workspace, timestamp) in enumerate((("other", 30), (Path.cwd().name, 10),
                                                             (Path.cwd().name, 20))):
                path = Path(f"/tmp/Visual Studio Code-{index}")
                registration = {"bundleID": "com.microsoft.VSCode", "workspaceName": workspace,
                                "socketPath": str(path), "timestamp": timestamp,
                                "capabilities": {"reload": 1}}
                (pairing / f"Visual Studio Code-{index}").write_text(json.dumps(registration))
            with patch("amx.codex_vscode.Path.is_socket", return_value=True):
                self.assertEqual(manager.reload_bridge_socket(), Path("/tmp/Visual Studio Code-2"))

    @unittest.skipIf(os.name == "nt", "legacy reload bridge uses Unix-domain sockets")
    def test_reload_bridge_protocol(self) -> None:
        response = json.dumps({"status": "success"}).encode("utf-8")

        class Connection:
            def __init__(self):
                self.received = bytearray(struct.pack("<I", len(response)) + response)
                self.sent = b""

            def __enter__(self): return self
            def __exit__(self, *args): return None
            def settimeout(self, timeout): self.timeout = timeout
            def connect(self, path): self.path = path
            def sendall(self, data): self.sent = data
            def recv(self, length):
                chunk = bytes(self.received[:length])
                del self.received[:length]
                return chunk

        connection = Connection()
        with patch("amx.codex_vscode.socket.socket", return_value=connection):
            CodexVSCodeManager._send_reload(Path("/tmp/Visual Studio Code-test"))
        length = struct.unpack("<I", connection.sent[:4])[0]
        self.assertEqual(json.loads(connection.sent[4:4 + length]), {"command": "reload"})
        self.assertEqual(connection.timeout, 5)

    def test_companion_registration_prefers_current_workspace(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pairing = root / "pairing"
            companion = root / "bridges"
            companion.mkdir()
            manager = CodexVSCodeManager(ConfigStore(root / "config", root / "data"),
                                          codex_home=root / "codex", pairing_root=pairing,
                                          companion_root=companion)
            for index, workspace in enumerate(("other", Path.cwd().name)):
                value = {"protocol": "agentmux-v1", "host": "127.0.0.1", "port": 4000 + index,
                         "token": "a" * 64, "pid": os.getpid(), "workspaceName": workspace, "timestamp": index}
                (companion / f"vscode-{index}.json").write_text(json.dumps(value))
            self.assertEqual(manager.companion_bridge(), CompanionBridge("127.0.0.1", 4001, "a" * 64))

    def test_companion_reload_protocol(self) -> None:
        response = bytearray(b'{"status":"success"}\n')

        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def sendall(self, data): self.sent = data
            def recv(self, length):
                chunk = bytes(response[:length]); del response[:length]; return chunk

        connection = Connection()
        bridge = CompanionBridge("127.0.0.1", 4321, "b" * 64)
        with patch("amx.codex_vscode.socket.create_connection", return_value=connection) as connect:
            CodexVSCodeManager._send_companion_reload(bridge)
        connect.assert_called_once_with(("127.0.0.1", 4321), timeout=5)
        self.assertEqual(json.loads(connection.sent), {"command": "reload", "token": "b" * 64})

    def test_companion_reload_returns_without_waiting_for_process_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            bridge = CompanionBridge("127.0.0.1", 4321, "c" * 64)
            with patch.object(manager, "companion_bridge", return_value=bridge), \
                    patch.object(manager, "_send_companion_reload") as send, \
                    patch.object(manager, "default_app_server_pids", return_value={10}):
                self.assertTrue(manager.reload_default_vscode())
            send.assert_called_once_with(bridge)

    def test_default_vscode_markers_are_cross_platform(self) -> None:
        commands = [
            "code --user-data-dir=/Users/me/Library/Application Support/Code",
            "code --user-data-dir=/home/me/.config/Code",
            r"Code.exe --user-data-dir=C:\\Users\\me\\AppData\\Roaming\\Code",
        ]
        self.assertTrue(all(CodexVSCodeManager._is_default_vscode_command(value) for value in commands))

    def test_default_vscode_process_detection_ignores_missing_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = self.manager(Path(tmp))
            app_server = ProcessInfo(42, 999, "vscode-codex", "codex app-server")
            with patch.object(manager, "inspect_processes", return_value=[app_server]):
                self.assertEqual(manager.default_app_server_pids(), set())

    def test_companion_install_uses_vscode_cli(self) -> None:
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "vscode_extension"
            source.mkdir()
            package = source / "agentmux-vscode.vsix"
            package.write_bytes(b"vsix")
            with patch("amx.codex_vscode.Path.with_name", return_value=source), \
                    patch("amx.codex_vscode.find_code_command", return_value="code"), \
                    patch("amx.codex_vscode.subprocess.run") as run:
                run.return_value.returncode = 0
                installed = CodexVSCodeManager.install_companion()
            self.assertEqual(installed, package)
            run.assert_called_once_with(
                ["code", "--install-extension", str(package), "--force"],
                capture_output=True, text=True, check=False, timeout=60,
            )

    def test_atomic_copy_permissions(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX permissions")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, destination = root / "source", root / "nested" / "auth.json"
            write_auth(source, "fixture")
            CodexVSCodeManager._atomic_copy(source, destination)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
