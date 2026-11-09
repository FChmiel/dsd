#!/usr/bin/env bash
# Build dsd.app + DMG for Apple Silicon.
#   packaging/build-macos.sh            -> app/src-tauri/target/release/bundle/{macos/dsd.app,dmg/dsd_<ver>_aarch64.dmg}
# Unsigned (ad-hoc) by default. To sign + notarize, export APPLE_SIGNING_IDENTITY ("Developer ID Application: …")
# plus APPLE_API_KEY / APPLE_API_ISSUER / APPLE_API_KEY_PATH; Tauri picks them up.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.cargo/bin:$PATH"

echo "==> UI"
(cd ui && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null)

echo "==> Freeze backend (PyInstaller)"
uv sync --group packaging >/dev/null
uv run --group packaging pyinstaller packaging/dsd.spec --noconfirm \
  --distpath build/pyinstaller --workpath build/pyinstaller-work >/dev/null
build/pyinstaller/dsd/dsd version >/dev/null   # smoke test

echo "==> Tauri app"
cd app
npm ci --no-audit --no-fund >/dev/null
if [[ -n "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  npx tauri build --config "{\"bundle\":{\"macOS\":{\"signingIdentity\":\"${APPLE_SIGNING_IDENTITY}\"}}}"
else
  npx tauri build
fi
cd ..

echo "==> DMG"
# Plain hdiutil (no Finder/AppleScript), so it works headless and on CI.
BUNDLE=app/src-tauri/target/release/bundle
APP="$BUNDLE/macos/dsd.app"
codesign --verify --deep --strict "$APP"
VERSION=$(sed -n 's/^  "version": "\(.*\)",/\1/p' app/src-tauri/tauri.conf.json)
DMG="$BUNDLE/dmg/dsd_${VERSION}_aarch64.dmg"
STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
mkdir -p "$BUNDLE/dmg" && rm -f "$DMG"
hdiutil create -volname "dsd" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG" >/dev/null
rm -rf "$STAGE"
if [[ -n "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  codesign --sign "$APPLE_SIGNING_IDENTITY" "$DMG"
  if [[ -n "${APPLE_API_KEY_PATH:-}" ]]; then
    xcrun notarytool submit "$DMG" --key "$APPLE_API_KEY_PATH" --key-id "$APPLE_API_KEY" --issuer "$APPLE_API_ISSUER" --wait
    xcrun stapler staple "$DMG"
  fi
fi
echo
ls -lh "$DMG"
shasum -a 256 "$DMG"
