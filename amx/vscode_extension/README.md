# AgentMux-amx for VS Code

Save and switch Codex accounts without leaving your normal VS Code window or separating local Codex history.

## What It Provides

- **AgentMux-amx** status-bar menu for provider and account selection
- **+** status-bar action to save the current Codex session
- **Sign in new account** using official Codex browser authentication in an isolated temporary home
- Active and re-authentication-required account states
- Rename and remove actions on each account
- Automatic VS Code reload after a verified switch
- Command Palette actions for switching, adding, refreshing, and reloading

Codex is the only supported provider in this release.

## Requirements

The extension needs the local `amx` CLI. If it is missing, select **Install AgentMux-amx CLI** from the error prompt or Command Palette. It installs the CLI in the background, saves the executable path in VS Code settings, and refreshes automatically. Python 3 is required.

To install manually from the cloned repository, keep `amx` available on VS Code's PATH:

```bash
python3 -m pip install -e .
amx setup
amx doctor
```

For a custom executable location, set **AgentMux: Command Path** to the full `amx` path.

The official Codex extension and Codex sign-in are separate requirements. AgentMux-amx never installs Codex or signs in on your behalf.

## Account Actions

**Add account** saves the Codex session currently signed in to VS Code under a name you choose.

**Sign in new account** runs official `codex login` with a temporary isolated `CODEX_HOME`. The existing live credential remains untouched during browser authentication. AgentMux activates and records the new session only after login succeeds; failure restores the previous credential.

Use **Cancel** in the sign-in notification to stop the temporary login. AgentMux restores the previous active account and does not save a partial account.

Selecting a saved account atomically switches the opaque authentication artifact and reloads VS Code. Shared Codex configuration, sessions, and thread history stay in `~/.codex`.

## Security

The extension delegates credential operations to the local AgentMux CLI. It never reads, parses, prints, or transmits authentication tokens. Its reload bridge listens only on loopback and authenticates each request with a random per-session token.

AgentMux is independent and is not affiliated with or endorsed by OpenAI or Microsoft.
