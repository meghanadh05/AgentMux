from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import unittest

from amx.config import ConfigStore
from amx.models import AppConfig, CONFIG_VERSION


class ConfigStoreTests(unittest.TestCase):
    def test_create_and_reload_account(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ConfigStore(root / "config", root / "data")
            config = store.load()
            account = store.create_account(config, "codex", "personal")
            store.save(config)

            loaded = store.load()
            self.assertEqual(loaded.find_account("codex", "personal").id, account.id)
            self.assertEqual(loaded.active_account("codex").id, account.id)
            self.assertEqual(loaded.active_account().id, account.id)
            self.assertEqual(loaded.environments, [])

    def test_duplicate_names_rejected_per_provider(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ConfigStore(root / "config", root / "data")
            config = store.load()
            store.create_account(config, "codex", "personal")
            with self.assertRaises(ValueError):
                store.create_account(config, "codex", "Personal")

    def test_v1_config_migrates_account_vscode_data_to_environment(self) -> None:
        raw = {
            "version": 1,
            "activeProvider": "codex",
            "activeAccounts": {"codex": "acc-1"},
            "accounts": [
                {
                    "id": "acc-1",
                    "provider": "codex",
                    "name": "personal",
                    "home": "/tmp/codex-home",
                    "vscode_user_data_dir": "/tmp/vscode-home",
                }
            ],
        }
        config = AppConfig.from_dict(raw)
        self.assertEqual(config.version, CONFIG_VERSION)
        self.assertEqual(config.active_account().id, "acc-1")
        self.assertEqual(config.accounts[0].provider_home, "/tmp/codex-home")
        self.assertEqual(len(config.environments), 1)
        self.assertEqual(config.environments[0].account_mode, "pinned")
        self.assertEqual(config.environments[0].pinned_account_id, "acc-1")
        self.assertEqual(config.environments[0].account_ids, {"codex": "acc-1"})
        self.assertEqual(config.environments[0].user_data_dir, "/tmp/vscode-home")

    def test_single_pinned_environment_migrates_to_provider_mapping(self) -> None:
        raw = {
            "version": 2,
            "activeProvider": "codex",
            "activeAccounts": {"codex": "acc-1"},
            "accounts": [
                {
                    "id": "acc-1",
                    "provider": "codex",
                    "name": "personal",
                    "provider_home": "/tmp/codex-home",
                }
            ],
            "environments": [
                {
                    "id": "env-1",
                    "name": "main",
                    "editor": "vscode",
                    "mode": "normal",
                    "account_mode": "pinned",
                    "pinned_account_id": "acc-1",
                }
            ],
        }
        config = AppConfig.from_dict(raw)
        self.assertEqual(config.environments[0].account_ids, {"codex": "acc-1"})

    def test_create_environment_separate_from_account(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ConfigStore(root / "config", root / "data")
            config = store.load()
            account = store.create_account(config, "codex", "personal")
            environment = store.create_environment(config, "main", mode="normal")
            store.save(config)

            loaded = store.load()
            self.assertEqual(loaded.find_account("codex", "personal").id, account.id)
            self.assertEqual(loaded.find_environment("main").id, environment.id)
            self.assertEqual(loaded.find_environment("main").account_mode, "follow_active")

    def test_v2_migration_is_backed_up_and_preserves_accounts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            original = {
                "version": 2,
                "activeProvider": "codex",
                "activeAccounts": {"codex": "acc-1"},
                "active_account_id": "acc-1",
                "accounts": [{
                    "id": "acc-1", "provider": "codex", "name": "Meg",
                    "provider_home": "/preserved/codex", "metadata": {"custom": "value"}
                }],
                "environments": [{
                    "id": "env-1", "name": "Meg VS Code", "editor": "vscode",
                    "mode": "isolated", "user_data_dir": "/preserved/vscode",
                    "account_mode": "pinned", "pinned_account_id": "acc-1"
                }],
            }
            config_path = config_dir / "config.json"
            original_bytes = (json.dumps(original, indent=2) + "\n").encode()
            config_path.write_bytes(original_bytes)
            store = ConfigStore(config_dir, root / "data")

            migrated = store.load()
            store.save(migrated)

            backup = config_dir / "config.v2.backup.json"
            self.assertEqual(backup.read_bytes(), original_bytes)
            if os.name != "nt":
                self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            saved = json.loads(config_path.read_text())
            self.assertEqual(saved["version"], 3)
            self.assertEqual(saved["activeAccounts"], {"codex": "acc-1"})
            self.assertEqual(saved["accounts"][0]["id"], "acc-1")
            self.assertEqual(saved["accounts"][0]["provider_home"], "/preserved/codex")
            self.assertEqual(saved["accounts"][0]["metadata"], {"custom": "value"})
            self.assertNotIn("environments", saved)
            self.assertEqual(saved["vscodeProfiles"], [])
            self.assertEqual(saved["legacyEditorEnvironments"][0]["user_data_dir"], "/preserved/vscode")

            store.save(migrated)
            self.assertEqual(backup.read_bytes(), original_bytes)

    def test_atomic_save_failure_keeps_original_config(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ConfigStore(root / "config", root / "data")
            config = store.load()
            store.create_account(config, "codex", "Meg")
            store.save(config)
            original = store.path.read_bytes()
            config.accounts[0].name = "Changed"

            with patch("amx.config.os.replace", side_effect=OSError("simulated failure")):
                with self.assertRaises(OSError):
                    store.save(config)

            self.assertEqual(store.path.read_bytes(), original)

    def test_default_profile_is_not_stored(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ConfigStore(root / "config", root / "data")
            config = store.load()
            account = store.create_account(config, "codex", "Meg")
            self.assertEqual(config.active_accounts["codex"], account.id)
            self.assertEqual(config.vscode_profiles, [])
            with self.assertRaises(ValueError):
                store.create_vscode_profile_mapping(config, "Default")


if __name__ == "__main__":
    unittest.main()
