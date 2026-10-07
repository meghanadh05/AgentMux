# Default VS Code Codex Switching

AgentMux uses the normal VS Code installation and shared `~/.codex` state.

## Authentication Boundary

Manual Meg to gtp2 to Meg observation established `auth.json` as the only authentication artifact selected for replacement. The returned Meg artifact differed from the initial artifact, so AgentMux saves the latest live artifact before every switch.

The following remain shared and untouched:

- configuration
- state and thread-history databases, including WAL and SHM files
- sessions and session indexes
- logs, queues, caches, plugins, IPC, locks, and temporary files

## Transaction

`amx switch ACCOUNT` acquires an exclusive lock, validates the live and target artifacts, creates a recovery artifact, saves the latest current artifact, atomically replaces the live artifact, updates active metadata, reloads the default VS Code window, and checks `codex login status`.

Failure after activation restores the recovery artifact and previous active-account metadata, then attempts one reload so the extension consumes the restored authentication.

## Refresh Boundary

The bundled AgentMux VS Code companion exposes an authenticated loopback bridge on macOS, Linux, and Windows. Each VS Code window publishes a private registration containing its workspace, local port, random session token, and process ID. AgentMux selects the live registration for the current workspace and requests `workbench.action.reloadWindow`. The companion acknowledges the request and applies a short grace period before reloading so commands launched inside VS Code can validate authentication, release the transaction lock, and print their result.

The Codex extension's Unix-socket bridge remains a macOS compatibility fallback. AgentMux does not simulate keyboard input, require Accessibility permission, or terminate editor processes.

Terminal Codex and unknown Codex processes are never terminated.

## Verification Boundary

AgentMux verifies that the target artifact was loaded, the app-server restarted, and `codex login status` reports an authenticated session. Codex does not expose a bounded supported command that returns the ChatGPT account name, so the target account name is not independently verified without consuming model usage.
