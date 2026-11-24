# Releasing dsd

Releases are cut by hand and built by CI. A tag builds everything into a **draft** GitHub Release, and nothing is public until you publish it. Publishing updates the Homebrew cask.

## What a release contains

| File | What it is |
|---|---|
| `dsd_<version>_aarch64.dmg` | The Mac app (Apple Silicon): a Tauri window plus the Python backend frozen with PyInstaller. Users don't need Python, uv or Node. |
| `dsd-<version>-py3-none-any.whl` | The Python package with the built web UI: `uv tool install <wheel URL>` puts `dsd` on PATH on any OS. |
| `dsd-<version>.tar.gz` | The source distribution. |
| `SHA256SUMS` | Checksums of the above. |

Users need **git** and, for the agent features, **Claude Code** (installed and logged in). On launch, the app starts the backend on a free localhost port, shows a splash screen until it responds, then loads the UI. Quitting the app stops the backend.

| Piece | Where |
|---|---|
| Version and changelog helper | `scripts/release.py` |
| Changelog | `CHANGELOG.md` |
| CI on pull requests | `.github/workflows/ci.yml` |
| Release build | `.github/workflows/release.yml` |
| Homebrew cask update | `.github/workflows/homebrew.yml`, from the template `packaging/homebrew/Casks/dsd.rb` |
| Mac app build | `packaging/build-macos.sh`, `packaging/dsd.spec`, `app/src-tauri/` |

## One-time setup

1. **Create the tap repo:** an empty public repo `FChmiel/homebrew-dsd`. Homebrew maps `fchmiel/dsd` to it.
2. **Create a fine-grained token** with *Contents: read and write* on `homebrew-dsd` only. Add it to this repo as the Actions secret `TAP_TOKEN`.
   Without it, the homebrew workflow prints the filled-in cask in its log, for you to copy into the tap by hand.

## Releasing a version

1. **Prepare** on a branch from an up-to-date main:
   ```sh
   python scripts/release.py 0.2.0
   ```
   This sets the version in `src/dsd/__init__.py` (which the Python package reads), `app/src-tauri/tauri.conf.json`, `Cargo.toml` and `Cargo.lock`. It also moves `## Unreleased` in `CHANGELOG.md` to `## 0.2.0 - <date>`.
2. **Write the notes** under the new changelog heading: what changed, for users, in a few bullets. They become the release notes.
3. **Open a "Release 0.2.0" PR** and merge it once CI is green.
4. **Optional dry run:** Actions → **release** → *Run workflow* on any branch builds the DMG and the wheel as downloadable artifacts, without releasing anything.
5. **Tag main:**
   ```sh
   git checkout main && git pull
   git tag v0.2.0 && git push origin v0.2.0
   ```
   The release workflow checks that every version matches the tag and that the changelog has notes. It then builds and smoke-tests the DMG and the wheel, and creates a **draft** release with the files, the notes, install instructions and checksums.
6. **Check the draft:** download the DMG and open the app, then run `uv tool install` on the wheel and run `dsd ui`.
7. **Publish** the draft on GitHub. The homebrew workflow fills in the cask's version and sha256 and pushes it to the tap.
8. **Check the cask:** `brew update && brew upgrade --cask dsd` (or `brew install --cask fchmiel/dsd/dsd`).

A tag with a suffix, like `v0.2.0-rc.1`, makes a prerelease, which doesn't update the cask.

If something goes wrong after tagging, delete the draft and the tag (`git push --delete origin v0.2.0`), fix it on main, and tag again.

## How users install it

```sh
brew install --cask fchmiel/dsd/dsd
```

This installs `dsd.app` into /Applications and puts the bundled `dsd` command on PATH. Claude Code needs that command to start the MCP server (`dsd mcp`).

The app isn't notarized yet, so the cask clears macOS's download quarantine flag after installing; without that, Gatekeeper would refuse to open it. To install from the DMG instead:
1. Drag the app to Applications.
2. Open it with right-click → **Open**. On macOS 15 and later, go to System Settings → Privacy & Security → **Open Anyway**.
3. Click **Install dsd command** in the app.

## Signing and notarization (optional)

You need an Apple Developer Program membership ($99 a year). Then:

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
   - It also needs these entitlements, because Python loads native extensions: `com.apple.security.cs.allow-unsigned-executable-memory` and `com.apple.security.cs.disable-library-validation`.
4. Delete the `postflight` quarantine block from the cask.

## Later

- **Auto-update:** `tauri-plugin-updater` with a `latest.json` on GitHub Releases. It uses its own signing key pair, separate from Apple's.
- **Intel Macs:** add a `macos-13` job. PyInstaller can't build a universal backend, so ship two DMGs.
- **PyPI:** `dsd` is taken there, so the package needs another name (for example `dsd-workspace`). The command and `import dsd` can stay.
