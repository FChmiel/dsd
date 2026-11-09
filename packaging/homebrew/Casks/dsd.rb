# Homebrew cask for dsd. Lives in your tap repo: github.com/OWNER/homebrew-dsd -> Casks/dsd.rb
# Testers install with:   brew install --cask OWNER/dsd/dsd
# The release workflow rewrites `version` and `sha256` on each tagged release.
cask "dsd" do
  version "0.1.0"
  sha256 "REPLACE_WITH_DMG_SHA256"

  url "https://github.com/OWNER/REPO/releases/download/v#{version}/dsd_#{version}_aarch64.dmg"
  name "dsd"
  desc "Plans, docs, experiments and Claude Code sessions for data science"
  homepage "https://github.com/OWNER/REPO"

  depends_on arch: :arm64
  depends_on macos: ">= :monterey"

  app "dsd.app"
  # The app bundles its own backend; expose it as the `dsd` command (Claude Code runs `dsd mcp`).
  binary "#{appdir}/dsd.app/Contents/Resources/backend/dsd/dsd"

  postflight do
    # Tester builds are not notarized yet: clear the download quarantine so macOS will open the app.
    # Delete this block once releases are signed with a Developer ID and notarized.
    system_command "/usr/bin/xattr", args: ["-dr", "com.apple.quarantine", "#{appdir}/dsd.app"]
  end

  # ~/.dsd is deliberately not zapped: it holds your project registry and git worktrees (possibly unmerged work).
  zap trash: [
    "~/Library/Application Support/dev.dsd.app",
    "~/Library/Caches/dev.dsd.app",
    "~/Library/Logs/dev.dsd.app",
    "~/Library/WebKit/dev.dsd.app",
  ]
end
