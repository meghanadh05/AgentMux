from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


CODE_COMMANDS = ["code", "code-insiders"]


def find_code_command() -> Optional[str]:
    for command in CODE_COMMANDS:
        found = shutil.which(command)
        if found:
            return found
    if os.name == "posix":
        mac_path = Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
        if mac_path.exists():
            return str(mac_path)
    if os.name == "nt":
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd",
            Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft VS Code" / "bin" / "code.cmd",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
    return None


def open_vscode(
    targets: List[str], env: Dict[str, str], user_data_dir: Optional[Path] = None,
) -> int:
    command = find_code_command()
    if command is None:
        raise FileNotFoundError("VS Code CLI was not found. Install VS Code and ensure the 'code' command is on PATH.")
    merged_env = os.environ.copy()
    merged_env.update(env)
    args = [command, "--new-window"]
    if user_data_dir is not None:
        user_data_dir.mkdir(parents=True, exist_ok=True)
        args.extend(["--user-data-dir", str(user_data_dir)])
    args.extend(targets)
    subprocess.Popen(args, env=merged_env)
    return 0


def is_vscode_running() -> bool:
    try:
        if os.name == "nt":
            result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Code.exe"], capture_output=True, text=True, check=False)
            return "Code.exe" in result.stdout
        pattern = "Visual Studio Code.app/Contents/MacOS/Electron" if sys.platform == "darwin" else "(^|/)code( |$)"
        return subprocess.run(["pgrep", "-f", pattern], capture_output=True, check=False).returncode == 0
    except OSError:
        return False
