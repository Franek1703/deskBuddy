#!/usr/bin/env bash
# Install the collector as a per-user launchd agent (run on the machine that holds the CLI logins).
# usage: deploy/install_collector_launchd.sh <codex-bin> <claude-bin>
set -euo pipefail
codex="${1:?path to codex}"; claude="${2:?path to claude}"
repo="$(cd "$(dirname "$0")/.." && pwd)"
dst="$HOME/Library/LaunchAgents/pl.deskbuddy.collector.plist"
mkdir -p "$repo/deploy/local/data" "$HOME/Library/LaunchAgents"
sed -e "s#@REPO@#$repo#g" -e "s#@CODEX_BIN@#$codex#g" -e "s#@CLAUDE_BIN@#$claude#g" \
    -e "s#@NODE_BIN_DIR@#$(dirname "$codex")#g" \
    "$repo/deploy/launchd/pl.deskbuddy.collector.plist.template" > "$dst"
plutil -lint "$dst"
launchctl bootout "gui/$(id -u)/pl.deskbuddy.collector" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$dst"
launchctl kickstart -k "gui/$(id -u)/pl.deskbuddy.collector"
echo "collector agent loaded; log: $repo/deploy/local/collector.log"
