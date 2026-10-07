# Publishing the AgentMux VS Code Extension

The extension source lives in `amx/vscode_extension/`. Publishing requires a unique Visual Studio Marketplace publisher ID and Marketplace credentials; those cannot be created or chosen by the repository itself.

## Prepare

1. Create a publisher at the [Visual Studio Marketplace publisher management page](https://marketplace.visualstudio.com/manage/publishers/).
2. Confirm the manifest publisher ID is `meghanadh05`.
3. Update the version and changelog.

## Validate And Package

```bash
cd amx/vscode_extension
npm install
npm run package
```

This creates `agentmux-vscode-<version>.vsix`. Test it before publishing:

```bash
code --install-extension agentmux-vscode-<version>.vsix
```

## Publish

For an initial manual release, authenticate `vsce` with the publisher credentials and publish:

```bash
npx vsce login meghanadh05
npm run publish
```

Alternatively, upload the generated VSIX through the publisher management page. Keep publishing credentials out of the repository. For automated releases, store credentials as protected CI secrets and follow Microsoft's current secure publishing guidance.

The authoritative process and current authentication requirements are documented in [Publishing Extensions](https://code.visualstudio.com/api/working-with-extensions/publishing-extension).
