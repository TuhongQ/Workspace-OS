# Workspace OS Windows 2.2.0

Windows integrated desktop package: control center and web dashboard in one WPF/WebView2 application.

## Files

- `WorkspaceOS-Windows-2.2.0-source.zip` — source archive from local source commit `94a523b147150ee7e18c21f288077838c55f6afc` (2026-09-24). It includes the Windows PowerShell entry points, Python core, dashboard/templates, and integrated WPF host. Personal workspace files, runtime settings, logs, credentials, and signing keys are excluded.
- Installer: `WorkspaceOS-NEXUS-Integrated-Windows-2.2.0-Setup.exe` — distributed as the GitHub Release asset, not committed to the repository tree.

## Compatibility and setup

- Windows x64; self-contained .NET 8 host and bundled Python runtime.
- WebView2 Runtime is required; setup attempts to install it if missing.
- Configure the local Workspace and NAS UNC path after installation. NAS credentials are not included.
- Desktop shortcut is selectable during setup; Start Menu and uninstall entries are provided.

## Verification and limitations

- Package SHA-256: `E870FD15DA568E8990FFD79B36E3EEC47675A29DEEF1FB7272DD18FE1D1F64E0`
- Source archive SHA-256: `934F262E90F6A7E655896A97F4675BA905053049A5FED203CA3A92AF96BD7D57`
- The installer is not digitally signed. Windows SmartScreen may show an unknown-publisher warning.
- The installer was previously smoke-tested locally; this release record does not claim fresh testing on a clean Windows machine or a live NAS.
