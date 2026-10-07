<p align="center">
  <img src="amx/vscode_extension/images/icon.png" alt="AgentMux" width="160">
</p>

# AgentMux (`amx`)

**Switch Codex accounts in your normal VS Code window without separating your local history or editor setup.**

AgentMux saves complete Codex authentication artifacts under friendly account names and swaps only the active authentication file. Your shared Codex configuration, sessions, thread history, databases, extensions, and VS Code settings remain in place.

> AgentMux currently supports Codex. The provider-first interface is designed for additional coding agents later.

## Features

- Switch saved Codex accounts from the VS Code status bar or terminal.
- Save the Codex session currently signed in to VS Code.
- Sign in to a different account through official Codex browser authentication in an isolated temporary home.
- Rename, remove, and re-authenticate saved accounts from VS Code.
- Preserve shared `~/.codex` history and configuration.
- Recover the previous credential automatically when switching or new-account login fails.
- Work on macOS, Linux, and Windows without Accessibility automation or simulated input.

## Requirements

- Python 3.9 or newer
- Visual Studio Code with the `code` command available
- Official Codex CLI and VS Code extension

To enable the `code` command on macOS, open the VS Code Command Palette and run **Shell Command: Install 'code' command in PATH**.

## Install

### macOS and Linux

```bash
git clone <repository-url> agentmux
cd agentmux
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
amx setup
amx doctor
```

### Windows PowerShell

```powershell
git clone <repository-url> agentmux
cd agentmux
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -e .
amx setup
amx doctor
```

Restart VS Code once after `amx setup`. The bottom status bar will show **AgentMux** and a neighboring **+** action.

## VS Code Workflow

### Save the current session

Use this when Codex is already signed in to the account you want to keep:

1. Click **+** beside **AgentMux**.
2. Select **Codex**.
3. Enter a memorable account name.

AgentMux copies the current opaque `~/.codex/auth.json` artifact. It never asks for a password or prints token fields.

### Sign in to a different account

1. Click **AgentMux**.
2. Select **Codex**.
3. Select **Sign in new account**.
4. Choose an AgentMux account name.
5. Complete the official Codex browser login.

The login runs with a temporary isolated `CODEX_HOME`; the existing live credential is not modified while authentication is in progress. After login succeeds, AgentMux atomically activates the new credential, reloads VS Code, verifies Codex login readiness, and records the account. Failure restores the previous credential.

### Switch accounts

1. Click **AgentMux**.
2. Select **Codex**. The active account appears beside the provider name.
3. Select an account.

The current account is marked **Active**. Only accounts that need attention display **Re-authentication required**. Edit and trash icons rename or remove a registration; **Add account** remains at the bottom.

## CLI

```text
amx add ACCOUNT                 Save the current Codex session
amx list                        List saved accounts
amx switch [AGENT] [ACCOUNT]    Switch accounts
amx status                      Show active-account status
amx rename [ACCOUNT]            Rename an account
amx remove [ACCOUNT]            Remove a registration
amx doctor                      Check switching readiness
amx setup                       Install the VS Code companion
```

Examples:

```bash
amx add Personal
amx list
amx switch Work
amx switch codex Personal
amx status
amx rename Work
amx remove "Old Account"
```

Running `amx switch` without arguments prompts for the provider and account. Account names containing spaces are accepted by the interactive commands.

## How Switching Works

For every switch, AgentMux:

1. Creates a protected recovery copy of the live authentication.
2. Saves the latest authentication for the current account.
3. Atomically installs the selected account's saved artifact.
4. Requests a normal VS Code window reload through the bundled companion.
5. Checks Codex login readiness without sending a model request.
6. Restores the previous credential and active mapping if verification fails.

The normal VS Code window briefly reloads. AgentMux does not create VS Code Profiles, alternate user-data directories, or account-specific history stores.

## Security

AgentMux treats authentication as an opaque file and modifies only:

```text
~/.codex/auth.json
```

It does not inspect token values or modify:

```text
~/.codex/config.toml
~/.codex/state_*.sqlite*
~/.codex/thread_history_*.sqlite*
~/.codex/sessions/
```

The VS Code companion listens only on loopback, uses a random per-session token, and stores its private registration under `~/.agentmux/bridges/`. AgentMux does not scrape browser cookies, collect passwords, implement OAuth, kill Codex processes, or automate the desktop.

Saved credentials and recovery copies are private to the current OS user. On POSIX systems, credential files use mode `0600` and managed directories use user-only permissions.

## Data Locations

| Platform | AgentMux data |
| --- | --- |
| macOS | `~/Library/Application Support/amx/` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/amx/` |
| Windows | `%LOCALAPPDATA%\amx\` |

## Limitations

- Codex is the only supported provider in this release.
- AgentMux cannot guarantee that a provider will never revoke a refresh token server-side.
- Re-authentication is required when Codex reports that a saved credential has expired or been revoked.
- The VS Code companion must be active for automatic window reloads.

## Development

Run the test suite:

```bash
python3 -m pytest
```

Build the VS Code extension package:

```bash
cd amx/vscode_extension
npm install
npm run package
```

See [Publishing the VS Code Extension](docs/publishing-vscode-extension.md) for Marketplace release steps.

## Independence

AgentMux is an independent open-source project and is not affiliated with or endorsed by OpenAI or Microsoft.

## License

MIT. See [LICENSE](LICENSE).
