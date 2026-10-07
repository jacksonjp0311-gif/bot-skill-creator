#!/usr/bin/env bash
# Put the Bot Skill Creator logo on the desktop. Clicking it opens the studio.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ICON="$ROOT/docs/assets/bot-skill-creator.png"
PYTHON="${BSC_PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { printf 'Python 3.11+ is required. Set BSC_PYTHON to your interpreter.\n' >&2; exit 1; }
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
[[ -f "$ICON" ]] || { printf 'The Bot Skill Creator icon is missing from this folder.\n' >&2; exit 1; }

case "$(uname -s)" in
  Darwin) DESKTOP="$HOME/Desktop" ;;
  *) DESKTOP="${XDG_DESKTOP_DIR:-$HOME/Desktop}" ;;
esac
mkdir -p "$DESKTOP"

if [[ "$(uname -s)" == "Darwin" ]]; then
  APP="$DESKTOP/Bot Skill Creator.app"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  cp "$ICON" "$APP/Contents/Resources/logo.png"
  cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Bot Skill Creator</string>
  <key>CFBundleDisplayName</key><string>Bot Skill Creator</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIdentifier</key><string>local.bot-skill-creator</string>
  <key>CFBundleIconFile</key><string>logo</string>
  <key>CFBundlePackageType</key><string>APPL</string>
</dict></plist>
EOF
  cat > "$APP/Contents/MacOS/launch" <<EOF
#!/bin/bash
cd "$ROOT"
exec bash "$ROOT/start.sh"
EOF
  chmod +x "$APP/Contents/MacOS/launch"
  printf 'Bot Skill Creator is on the desktop. Click the icon to open it.\n%s\n' "$APP"
  exit 0
fi

LAUNCHER="$DESKTOP/Bot Skill Creator.desktop"
cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Name=Bot Skill Creator
Comment=Open the local skill studio
Exec=bash "$ROOT/start.sh"
Path=$ROOT
Icon=$ICON
Terminal=false
Categories=Development;
EOF
chmod +x "$LAUNCHER"
mkdir -p "$HOME/.local/share/applications"
cp "$LAUNCHER" "$HOME/.local/share/applications/bot-skill-creator.desktop"
printf 'Bot Skill Creator is on the desktop. Click the icon to open it.\n%s\n' "$LAUNCHER"
