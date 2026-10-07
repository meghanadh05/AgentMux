# Manual Codex Account Switch Observation

Observed: 2026-10-07

This experiment used the normal VS Code installation and the shared `~/.codex` home. File contents and credential values were never printed. Snapshots recorded paths, types, sizes, permissions, modification times, and SHA-256 hashes.

## Baseline

- Preserved implementation: commit `c0829c3`
- Tests: 24 passed
- Snapshot coverage: 12,412 entries and 8,715 regular files
- Snapshot errors: 0
- Default VS Code main process and its Codex app-server were identified separately from an older AgentMux-isolated instance.

## Meg To gtp2

The user signed out of Meg and authenticated gtp2 through the official Codex extension. gtp2 became active and existing history remained visible.

Observed stable files:

- `config.toml`: content unchanged
- `state_5.sqlite`: content unchanged during this interval
- `thread_history_1.sqlite`: content unchanged

Observed authentication change:

- `auth.json`: content, size or modification time changed; permissions remained `0600`

Runtime activity also changed WAL, log, queue, cache, session-index, current-session, lock, shell-snapshot, and temporary files. Those changes occurred while Codex was actively running and are not evidence that they belong to the authentication boundary.

## gtp2 To Meg

The user signed out of gtp2 and authenticated Meg through the official Codex extension. Meg became active and existing history remained visible.

Observed stable files:

- `config.toml`: content unchanged
- `thread_history_1.sqlite`: content unchanged

Observed authentication change:

- `auth.json`: content and metadata changed again; permissions remained `0600`
- The returned Meg artifact was not byte-for-byte identical to the initial Meg artifact. AgentMux must therefore preserve the latest current artifact before switching away instead of treating initial registration as permanent.

`state_5.sqlite` and its WAL changed during this interval. It is shared runtime state and is excluded from the authentication boundary. Plugin-cache updates and this active Codex session produced substantial unrelated filesystem churn.

## Current Classification

| Class | Paths |
| --- | --- |
| Authentication candidate | `auth.json` |
| Shared Codex state | `config.toml`, `state_*.sqlite*`, `thread_history_*.sqlite*`, `sessions/`, `session_index.jsonl` |
| Transient/runtime | `tmp/`, `thread-writer-locks/`, `shell_snapshots/`, `ipc/`, SQLite WAL/SHM files |
| Logging/cache | `logs_*.sqlite*`, `queue_*.sqlite*`, `cache/`, `models_cache.json`, `plugins/cache/` |
| Unknown | None currently selected for modification |

Only the complete opaque `auth.json` artifact is a candidate for controlled replacement. No token fields should be parsed or merged.

## Refresh Evidence

The official manual authentication flow resulted in a new default VS Code main process, extension host, and Codex app-server. Inspection of the installed extension shows that its internal `codex-app-server-restart` event executes `workbench.action.reloadWindow`. The extension does not contribute a public app-server restart command.

The currently supported refresh candidate is therefore a reload of the relevant default VS Code window. Directly killing the child app-server remains unproven and should not be automated.
