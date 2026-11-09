# Shipping dsd as a Mac app

## What gets shipped

`dsd.app` (Apple Silicon) is made of:

- a **Tauri shell** (a native window using the system WebKit), plus
- the **Python backend frozen with PyInstaller**, in `Contents/Resources/backend/dsd/`.

On launch the shell:
1. starts the backend on a free localhost port,
2. shows a splash screen until the backend responds,
3. loads the UI.

Quitting the app stops the backend.

Users don't need Python, uv or Node. They do need **git** and **Claude Code** (installed and logged in).

| Piece | Where |
|---|---|
| Build everything locally | `packaging/build-macos.sh` → `app/src-tauri/target/release/bundle/dmg/dsd_<ver>_aarch64.dmg` |
| Freeze spec | `packaging/dsd.spec` |
| Desktop shell | `app/src-tauri/` (`src/main.rs`, `tauri.conf.json`) |
| Homebrew cask template | `packaging/homebrew/Casks/dsd.rb` |
| CI release | `.github/workflows/release.yml` (runs on a `v*` tag) |

## How testers install it (no Apple account needed)

```sh
brew install --cask OWNER/dsd/dsd
```

This installs `dsd.app` into /Applications and links the bundled `dsd` command onto PATH. Claude Code needs that command for the project MCP server (`dsd mcp`).

The build isn't notarized yet, so the cask clears macOS's download quarantine flag after installing. Without that, Gatekeeper would refuse to open the app.

To install from the DMG instead:
1. Drag the app to Applications.
2. Open it via right-click → **Open**. On macOS 15+, go to System Settings → Privacy & Security → **Open Anyway**.
3. Click **Install dsd command** in the app.

How to use it:
1. Open **dsd**.
2. Click **Choose folder…** and pick a git repo. The app offers to set it up (`dsd init`).
3. Click **+ New session**. Claude Code starts in a fresh worktree, already wired to the project's plans, docs and runs.
4. Track experiments from any terminal with `dsd exec -b <benchmark> -- python train.py`. Scripts don't need to import anything.

## One-time setup to publish

1. **Push this repo to GitHub**, e.g. `OWNER/dsd`. The cask URL points at its Releases.
2. **Create the tap repo** `OWNER/homebrew-dsd` (empty, public). Homebrew maps `OWNER/dsd` to it.
3. **Create a fine-grained token** with *Contents: read & write* on `homebrew-dsd`. Add it as the secret `TAP_TOKEN` on the main repo. The release workflow then updates the cask's version and sha256 on every release.
4. Keep the versions in sync: `pyproject.toml`, `app/src-tauri/tauri.conf.json`, `app/src-tauri/Cargo.toml`.
5. Release:
   ```sh
   git tag v0.1.0 && git push origin v0.1.0
   ```
   CI builds the DMG on an Apple Silicon runner, publishes the GitHub Release and bumps the cask.

Without `TAP_TOKEN`, copy `packaging/homebrew/Casks/dsd.rb` into the tap repo by hand, replacing `OWNER/REPO`, `version` and `sha256`. CI prints the sha256 in the release notes.

## Going public: signing and notarization

You need an Apple Developer Program membership ($99/yr). Then:

1. Create a **Developer ID Application** certificate and export it as a `.p12`. Add these repo secrets:
   - `APPLE_CERTIFICATE`: the .p12, base64-encoded
   - `APPLE_CERTIFICATE_PASSWORD`
   - `APPLE_SIGNING_IDENTITY`: `Developer ID Application: Your Name (TEAMID)`
2. Create an **App Store Connect API key** (Users and Access → Integrations). Add these secrets:
   - `APPLE_API_KEY`: the key id
   - `APPLE_API_ISSUER`
   - `APPLE_API_KEY_P8`: the .p8 contents
3. Tauri signs the app and notarizes the DMG during `tauri build`.
   - The PyInstaller backend needs signing too. Pass `--codesign-identity` / `codesign_identity` in `dsd.spec`, or sign `Contents/Resources/backend` before bundling, using the **hardened runtime**.
   - It also needs these entitlements: `com.apple.security.cs.allow-unsigned-executable-memory` and `com.apple.security.cs.disable-library-validation`. Python loads native extensions.
4. Delete the `postflight` quarantine block from the cask.

## Later

- **Auto-update:** `tauri-plugin-updater` with a `latest.json` on GitHub Releases. It uses its own signing key pair, separate from Apple's.
- **Intel Macs:** add a `macos-13` job. PyInstaller can't build a universal backend, so ship two DMGs.
- **SDK on PyPI** (e.g. `dsd-sdk`), so `import dsd` works in users' own environments. `dsd exec` covers most cases without it.
