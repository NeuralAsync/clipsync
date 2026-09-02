#!/bin/bash
# Builds "Start ClipSync.app" — a tiny launcher (no tray icon of its own)
# that asks launchd to (re)start the real clipsync LaunchAgent, then exits.
#
# Why this exists instead of a .app that runs clipsync directly: macOS's
# ControlCenter refuses the NSStatusItem "scene" request over XPC
# (BSServiceConnectionErrorDomain code 3) for GUI apps launched via
# LaunchServices (double-click / Launchpad / `open`) — the process runs
# fine, but the tray icon never renders. A Terminal-launched or
# launchd-launched process doesn't hit this. This launcher sidesteps it by
# never creating a status item itself: it just runs `launchctl kickstart`
# and quits, and the real process comes up through launchd.
#
# Usage: ./build_mac_launcher.sh

set -euo pipefail
cd "$(dirname "$0")"

APP="/Applications/Start ClipSync.app"
ICONSET=$(mktemp -d)/icon.iconset
mkdir -p "$ICONSET"

python3 -c "
from PIL import Image, ImageDraw

def make_icon(size, board_color='#3b82c4', dot_color='#2ecc71'):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 64
    body = (12*s, 10*s, 52*s, 58*s)
    draw.rounded_rectangle(body, radius=6*s, fill=board_color, outline='#1c1c1c', width=max(1,int(2*s)))
    clip = (24*s, 4*s, 40*s, 16*s)
    draw.rounded_rectangle(clip, radius=4*s, fill='#1c1c1c')
    draw.rounded_rectangle((19*s, 26*s, 45*s, 31*s), radius=2*s, fill='#ffffff')
    draw.rounded_rectangle((19*s, 36*s, 39*s, 41*s), radius=2*s, fill='#ffffff')
    draw.ellipse((40*s, 42*s, 58*s, 60*s), fill=dot_color, outline='#1c1c1c', width=max(1,int(2*s)))
    return img

for sz in (16, 32, 128, 256, 512):
    make_icon(sz).save('$ICONSET/icon_%dx%d.png' % (sz, sz))
    make_icon(sz*2).save('$ICONSET/icon_%dx%d@2x.png' % (sz, sz))
make_icon(1024).save('$ICONSET/icon_1024x1024.png')
"

ICNS=$(mktemp -d)/AppIcon.icns
iconutil -c icns "$ICONSET" -o "$ICNS"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ICNS" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Start ClipSync</string>
    <key>CFBundleDisplayName</key>
    <string>Start ClipSync</string>
    <key>CFBundleIdentifier</key>
    <string>com.clipsync.launcher</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>StartClipSync</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSUIElement</key>
    <true/>
    <key>LSBackgroundOnly</key>
    <true/>
</dict>
</plist>
EOF

cat > "$APP/Contents/MacOS/StartClipSync" << 'EOF'
#!/bin/bash
launchctl kickstart -k "gui/$(id -u)/com.clipsync.app"
EOF
chmod +x "$APP/Contents/MacOS/StartClipSync"

codesign -s - --force "$APP"

echo "Built: $APP"
