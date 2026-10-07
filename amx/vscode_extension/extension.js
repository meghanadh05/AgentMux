const crypto = require("crypto");
const childProcess = require("child_process");
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");
const vscode = require("vscode");

let registrationPath;
let server;
let statusBar;
let addStatusBar;

const agents = [
  { id: "codex", label: "Codex", description: "Available" }
];

const renameButton = { iconPath: new vscode.ThemeIcon("edit"), tooltip: "Rename account" };
const removeButton = { iconPath: new vscode.ThemeIcon("trash"), tooltip: "Remove account" };
const CLI_SOURCE = "https://github.com/meghanadh05/AgentMux/archive/refs/heads/main.zip";

function amxCommand() {
  return vscode.workspace.getConfiguration("agentmux").get("commandPath", "amx");
}

function codexCommand() {
  return vscode.workspace.getConfiguration("agentmux").get("codexCommandPath", "").trim();
}

function runExecutable(command, args, timeout = 30000, env = process.env) {
  return new Promise((resolve, reject) => {
    childProcess.execFile(command, args, { encoding: "utf8", timeout, env }, (error, stdout, stderr) => {
      if (error) {
        const detail = (stderr || error.message || "AgentMux command failed").trim();
        const failure = new Error(detail);
        failure.code = error.code;
        reject(failure);
        return;
      }
      resolve(stdout.trim());
    });
  });
}

async function runAmx(args, timeout = 30000) {
  try {
    const command = codexCommand();
    return await runExecutable(amxCommand(), args, timeout, {
      ...process.env,
      ...(command ? { AMX_CODEX_COMMAND: command } : {})
    });
  } catch (error) {
    if (error.code === "ENOENT") {
      const missing = new Error("AgentMux-amx CLI is not installed or is not on PATH.");
      missing.code = "AMX_CLI_NOT_FOUND";
      throw missing;
    }
    if (/Codex CLI was not found/i.test(error.message)) {
      error.code = "CODEX_CLI_NOT_FOUND";
    }
    throw error;
  }
}

function pythonCommands() {
  return process.platform === "win32" ? ["py", "python"] : ["python3", "python"];
}

async function installCli() {
  let lastError;
  try {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Installing AgentMux-amx CLI...", cancellable: false },
      async () => {
        for (const python of pythonCommands()) {
          try {
            await runExecutable(python, ["-m", "pip", "install", "--user", CLI_SOURCE], 180000);
            const scripts = await runExecutable(python, ["-c", "import os, sysconfig; " +
              "print(sysconfig.get_path('scripts', 'nt_user' if os.name == 'nt' else 'posix_user'))"]);
            const executable = path.join(scripts, process.platform === "win32" ? "amx.exe" : "amx");
            if (!fs.existsSync(executable)) throw new Error("The installed amx executable could not be found.");
            await vscode.workspace.getConfiguration("agentmux").update(
              "commandPath", executable, vscode.ConfigurationTarget.Global
            );
            return;
          } catch (error) {
            lastError = error;
            if (error.code !== "ENOENT") throw error;
          }
        }
        throw lastError || new Error("Python 3 was not found.");
      }
    );
    await refreshStatus();
    vscode.window.showInformationMessage("AgentMux-amx CLI installed and ready.");
  } catch (error) {
    vscode.window.showErrorMessage(
      `AgentMux-amx could not install its CLI: ${error.message}. Install Python 3, then use Configure CLI Path.`
    );
  }
}

function npmCommands() {
  return process.platform === "win32" ? ["npm.cmd", "npm"] : ["npm"];
}

function codexExecutable(prefix) {
  if (process.platform === "win32") return path.join(prefix, "codex.cmd");
  return path.join(prefix, "bin", "codex");
}

async function installCodexCli() {
  let lastError;
  try {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Installing official Codex CLI...", cancellable: false },
      async () => {
        for (const npm of npmCommands()) {
          try {
            await runExecutable(npm, ["install", "--global", "@openai/codex@latest"], 180000);
            const prefix = await runExecutable(npm, ["prefix", "--global"]);
            const executable = codexExecutable(prefix.trim());
            if (!fs.existsSync(executable)) throw new Error("The installed codex executable could not be found.");
            await vscode.workspace.getConfiguration("agentmux").update(
              "codexCommandPath", executable, vscode.ConfigurationTarget.Global
            );
            return;
          } catch (error) {
            lastError = error;
            if (error.code !== "ENOENT") throw error;
          }
        }
        throw lastError || new Error("Node.js and npm were not found.");
      }
    );
    await refreshStatus();
    vscode.window.showInformationMessage("Official Codex CLI installed and ready. Continue with Sign in new account.");
  } catch (error) {
    vscode.window.showErrorMessage(
      `Codex CLI could not be installed: ${error.message}. Install Node.js, then use Configure Codex CLI Path.`
    );
  }
}

async function handleCliError(error) {
  if (error?.code !== "AMX_CLI_NOT_FOUND") return false;
  const action = await vscode.window.showErrorMessage(
    "AgentMux-amx needs its local CLI before it can manage accounts.",
    "Install AgentMux-amx CLI",
    "Configure CLI Path"
  );
  if (action === "Install AgentMux-amx CLI") await installCli();
  if (action === "Configure CLI Path") {
    vscode.commands.executeCommand("workbench.action.openSettings", "agentmux.commandPath");
  }
  return true;
}

async function handleCodexCliError(error) {
  if (error?.code !== "CODEX_CLI_NOT_FOUND") return false;
  const action = await vscode.window.showErrorMessage(
    "AgentMux-amx needs the official Codex CLI to sign in to a separate account.",
    "Install Codex CLI",
    "Configure Codex CLI Path"
  );
  if (action === "Install Codex CLI") await installCodexCli();
  if (action === "Configure Codex CLI Path") {
    vscode.commands.executeCommand("workbench.action.openSettings", "agentmux.codexCommandPath");
  }
  return true;
}

async function refreshStatus() {
  try {
    const status = JSON.parse(await runAmx(["status", "--json"]));
    statusBar.text = "$(key) AgentMux";
    statusBar.tooltip = status.activeAccount
      ? `Codex: ${status.activeAccount} (${status.loaded ? "active" : "re-authentication required"})`
      : "Open AgentMux";
    statusBar.show();
  } catch (error) {
    statusBar.text = error.code === "AMX_CLI_NOT_FOUND" ? "$(cloud-download) AgentMux-amx" : "$(warning) AgentMux-amx";
    statusBar.tooltip = error.code === "AMX_CLI_NOT_FOUND"
      ? "AgentMux-amx CLI is required. Click to install or configure it."
      : error.message;
    statusBar.show();
  }
}

async function chooseAgent() {
  const status = JSON.parse(await runAmx(["status", "--json"]));
  const selected = await vscode.window.showQuickPick(agents.map((agent) => ({
    label: agent.label,
    description: agent.id === status.provider
      ? (status.activeAccount || "No active account")
      : agent.description,
    agent
  })), {
    title: "Select an agent",
    placeHolder: "AgentMux currently supports Codex"
  });
  return selected?.agent;
}

async function accountItems(agent) {
  const result = JSON.parse(await runAmx(["list", "--json"]));
  const accounts = result.accounts.filter((account) => account.provider === agent.id);
  const items = accounts.map((account) => ({
    label: `${account.active ? "$(check)" : "$(account)"} ${account.name}`,
    description: account.active && account.ready
      ? "Active"
      : (account.ready ? "" : "Re-authentication required"),
    buttons: [renameButton, removeButton],
    account,
    action: "switch"
  }));
  items.push({ label: "Actions", kind: vscode.QuickPickItemKind.Separator });
  items.push({ label: "$(add) Add account", description: `Save current ${agent.label} authentication`, action: "add" });
  items.push({ label: "$(sign-in) Sign in new account", description: `Open official ${agent.label} login`, action: "login-add" });
  for (const account of accounts.filter((item) => !item.ready)) {
    items.push({
      label: `$(refresh) Re-authenticate ${account.name}`,
      description: "Use authentication currently loaded in VS Code",
      account,
      action: "reauthenticate"
    });
  }
  return items;
}

async function renameAccount(agent, account) {
  const name = await vscode.window.showInputBox({
    title: `Rename ${agent.label} account`,
    value: account.name,
    prompt: "Enter the new account name",
    ignoreFocusOut: true,
    validateInput: (value) => value.trim() ? undefined : "Account name is required"
  });
  if (name === undefined || name.trim() === account.name) return;
  await runAmx(["rename", account.id, "--to", name.trim()]);
  vscode.window.showInformationMessage(`AgentMux renamed the account to ${name.trim()}.`);
}

async function removeAccount(agent, account) {
  const answer = await vscode.window.showWarningMessage(
    `Remove ${account.name} from AgentMux?`,
    { modal: true, detail: "Shared agent history and configuration will not be deleted." },
    "Remove"
  );
  if (answer !== "Remove") return;
  await runAmx(["remove", account.id, "--yes"]);
  vscode.window.showInformationMessage(`AgentMux removed ${account.name}.`);
}

async function reauthenticateAccount(agent, account) {
  const answer = await vscode.window.showWarningMessage(
    `Replace the saved authentication for ${account.name}?`,
    { modal: true, detail: `First sign in to ${agent.label} in this VS Code window. AgentMux will save the authentication currently loaded.` },
    "Re-authenticate"
  );
  if (answer !== "Re-authenticate") return;
  await runAmx(["reauthenticate", account.id]);
  await refreshStatus();
  vscode.window.showInformationMessage(`AgentMux updated authentication for ${account.name}.`);
}

async function showAccounts(agent) {
  while (true) {
    const items = await accountItems(agent);
    const picker = vscode.window.createQuickPick();
    picker.title = `${agent.label} accounts`;
    picker.placeholder = "Select an account to switch";
    picker.items = items;
    const result = await new Promise((resolve) => {
      picker.onDidAccept(() => resolve({ item: picker.selectedItems[0] }));
      picker.onDidTriggerItemButton((event) => resolve({ item: event.item, button: event.button }));
      picker.onDidHide(() => resolve(undefined));
      picker.show();
    });
    picker.dispose();
    if (!result?.item) return;
    const item = result.item;
    if (result.button === renameButton) await renameAccount(agent, item.account);
    else if (result.button === removeButton) await removeAccount(agent, item.account);
    else if (item.action === "add") await addAccount(agent);
    else if (item.action === "login-add") await loginAndAddAccount(agent);
    else if (item.action === "reauthenticate") await reauthenticateAccount(agent, item.account);
    else if (item.action === "switch" && !item.account.ready) await reauthenticateAccount(agent, item.account);
    else if (item.action === "switch" && !item.account.active) {
      await runAmx(["switch", agent.id, item.account.id]);
      statusBar.text = "$(sync~spin) AgentMux";
      vscode.window.showInformationMessage(`AgentMux switched to ${item.account.name}.`);
      return;
    }
  }
}

async function loginAndAddAccount(agent) {
  const name = await vscode.window.showInputBox({
    title: `Sign in new ${agent.label} account`,
    prompt: "Choose the AgentMux name before opening official login",
    placeHolder: "Work",
    ignoreFocusOut: true,
    validateInput: (value) => value.trim() ? undefined : "Account name is required"
  });
  if (name === undefined) return;
  const proceed = await vscode.window.showInformationMessage(
    `AgentMux will protect the current session and open official ${agent.label} login. It will not log out first.`,
    { modal: true },
    "Open official login"
  );
  if (proceed !== "Open official login") return;
  const cancellationRoot = fs.mkdtempSync(path.join(os.tmpdir(), "agentmux-login-"));
  const cancellationFile = path.join(cancellationRoot, "cancel");
  let cancelled = false;
  try {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: `Waiting for ${agent.label} sign-in...`, cancellable: true },
      async (_progress, token) => {
        const cancellation = token.onCancellationRequested(() => {
          cancelled = true;
          fs.writeFileSync(cancellationFile, "cancelled", { mode: 0o600 });
        });
        try {
          await runAmx(["login-add", "--cancel-file", cancellationFile, name.trim()], 600000);
        } catch (error) {
          if (!cancelled) throw error;
        } finally {
          cancellation.dispose();
        }
      }
    );
  } finally {
    fs.rmSync(cancellationRoot, { recursive: true, force: true });
  }
  if (cancelled) {
    await refreshStatus();
    vscode.window.showInformationMessage("AgentMux cancelled sign-in and restored the previous account.");
    return;
  }
  await refreshStatus();
  vscode.window.showInformationMessage(`AgentMux authenticated and saved ${name.trim()}.`);
}

async function switchAccount() {
  try {
    const agent = await chooseAgent();
    if (agent) await showAccounts(agent);
  } catch (error) {
    if (await handleCliError(error)) return;
    if (await handleCodexCliError(error)) return;
    const action = await vscode.window.showErrorMessage(`AgentMux: ${error.message}`, "Open Settings");
    if (action === "Open Settings") vscode.commands.executeCommand("workbench.action.openSettings", "agentmux.commandPath");
  }
}

async function addAccount(selectedAgent) {
  try {
    const agent = selectedAgent || await chooseAgent();
    if (!agent) return;
    const name = await vscode.window.showInputBox({
      title: `Save current ${agent.label} session`,
      prompt: `Name the ${agent.label} account currently signed in to VS Code`,
      placeHolder: "Personal",
      ignoreFocusOut: true,
      validateInput: (value) => value.trim() ? undefined : "Account name is required"
    });
    if (name === undefined) return;
    await runAmx(["add", name.trim()]);
    await refreshStatus();
    vscode.window.showInformationMessage(`AgentMux saved the current ${agent.label} session as ${name.trim()}.`);
  } catch (error) {
    if (await handleCliError(error)) return;
    if (await handleCodexCliError(error)) return;
    const action = await vscode.window.showErrorMessage(`AgentMux: ${error.message}`, "Open Settings");
    if (action === "Open Settings") {
      vscode.commands.executeCommand("workbench.action.openSettings", "agentmux.commandPath");
    }
  }
}

function workspaceName() {
  const folder = vscode.workspace.workspaceFolders?.[0];
  return folder ? path.basename(folder.uri.fsPath) : "";
}

function activate(context) {
  const token = crypto.randomBytes(32).toString("hex");
  const root = path.join(os.homedir(), ".agentmux", "bridges");
  fs.mkdirSync(root, { recursive: true, mode: 0o700 });

  server = net.createServer((connection) => {
    let buffer = "";
    let handled = false;
    connection.setEncoding("utf8");
    connection.on("data", (chunk) => {
      buffer += chunk;
      if (buffer.length > 1024 * 1024) connection.destroy();
      const newline = buffer.indexOf("\n");
      if (newline < 0 || handled) return;
      handled = true;
      try {
        const request = JSON.parse(buffer.slice(0, newline));
        if (request.token !== token || request.command !== "reload") throw new Error("unauthorized");
        connection.end(JSON.stringify({ status: "success" }) + "\n");
        setTimeout(() => vscode.commands.executeCommand("workbench.action.reloadWindow"), 2000);
      } catch {
        connection.end(JSON.stringify({ status: "error" }) + "\n");
      }
    });
  });

  server.listen(0, "127.0.0.1", () => {
    const address = server.address();
    registrationPath = path.join(root, `vscode-${process.pid}.json`);
    const registration = {
      protocol: "agentmux-v1",
      host: "127.0.0.1",
      port: address.port,
      token,
      pid: process.pid,
      workspaceName: workspaceName(),
      timestamp: Date.now()
    };
    fs.writeFileSync(registrationPath, JSON.stringify(registration), { mode: 0o600 });
  });

  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  statusBar.command = "agentmux.switchAccount";
  addStatusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 49);
  addStatusBar.text = "$(add)";
  addStatusBar.name = "AgentMux: Add Account";
  addStatusBar.tooltip = "Save the current agent account";
  addStatusBar.command = "agentmux.addAccount";
  addStatusBar.show();
  context.subscriptions.push(
    statusBar,
    addStatusBar,
    vscode.commands.registerCommand("agentmux.switchAccount", switchAccount),
    vscode.commands.registerCommand("agentmux.addAccount", addAccount),
    vscode.commands.registerCommand("agentmux.installCli", installCli),
    vscode.commands.registerCommand("agentmux.installCodexCli", installCodexCli),
    vscode.commands.registerCommand("agentmux.refreshStatus", refreshStatus),
    vscode.commands.registerCommand("agentmux.reloadWindow", () =>
      vscode.commands.executeCommand("workbench.action.reloadWindow")),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("agentmux.commandPath") || event.affectsConfiguration("agentmux.codexCommandPath")) refreshStatus();
    })
  );
  refreshStatus();
}

function deactivate() {
  if (server) server.close();
  if (registrationPath) fs.rmSync(registrationPath, { force: true });
}

module.exports = { activate, deactivate };
