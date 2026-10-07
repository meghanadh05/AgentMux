from pathlib import Path
import unittest

from amx.paths import provider_home, vscode_user_data


class PathTests(unittest.TestCase):
    def test_provider_home_uses_provider_and_account_id(self) -> None:
        root = Path("/tmp/amx-test")
        self.assertEqual(provider_home("codex", "abc", root), root / "providers" / "codex" / "abc")

    def test_vscode_user_data_uses_account_id(self) -> None:
        root = Path("/tmp/amx-test")
        self.assertEqual(vscode_user_data("abc", root), root / "vscode" / "abc")


if __name__ == "__main__":
    unittest.main()

