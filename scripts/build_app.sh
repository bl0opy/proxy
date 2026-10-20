#!/bin/zsh
set -euo pipefail

ROOT=${0:A:h:h}
APP="$ROOT/build/Proxy.app"
VERSION=0.1.0

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

xcrun clang -O2 -Wall -DPROJECT_DIR="\"$ROOT\"" -o "$APP/Contents/MacOS/proxy" "$ROOT/app/launcher.c"
"$ROOT/.venv/bin/python" "$ROOT/app/make_icon.py" "$APP/Contents/Resources/Proxy.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key><string>com.bl0opy.proxy</string>
    <key>CFBundleName</key><string>Proxy</string>
    <key>CFBundleDisplayName</key><string>Proxy</string>
    <key>CFBundleExecutable</key><string>proxy</string>
    <key>CFBundleIconFile</key><string>Proxy</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSUIElement</key><true/>
    <key>NSMicrophoneUsageDescription</key><string>Proxy listens only while you hold the push-to-talk key.</string>
    <key>NSAppleEventsUsageDescription</key><string>Proxy controls the apps you ask it to.</string>
</dict>
</plist>
PLIST

codesign --force --sign - "$APP"
echo "built $APP"
