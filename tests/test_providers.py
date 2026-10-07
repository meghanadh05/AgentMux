import unittest
from pathlib import Path
from unittest.mock import patch

from amx.models import Account
from amx.providers.codex import CodexProvider


class ProviderTests(unittest.TestCase):
    def test_codex_env_sets_codex_home(self) -> None:
        account = Account("id", "codex", "personal", "/tmp/codex")
        self.assertEqual(CodexProvider().env(account), {"CODEX_HOME": "/tmp/codex"})

    def test_codex_launch_uses_isolated_home_and_preserves_cwd(self) -> None:
        account = Account("id", "codex", "personal", "/tmp/legacy-provider-home")
        with patch("amx.providers.base.subprocess.call", return_value=0) as call, \
             patch.object(CodexProvider, "executable_path", return_value="/usr/bin/codex"), \
             patch.dict("os.environ", {"CODEX_HOME": "/tmp/stale-provider-home"}):
            self.assertEqual(CodexProvider().launch(account, ["--help"]), 0)
        self.assertEqual(call.call_args.kwargs["env"]["CODEX_HOME"], "/tmp/legacy-provider-home")
        self.assertEqual(call.call_args.kwargs["cwd"], str(Path.cwd()))


if __name__ == "__main__":
    unittest.main()
