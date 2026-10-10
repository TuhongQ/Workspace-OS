#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
KIND="${1:-iphoneos}"
BUILD="$(mktemp -d "$ROOT/build-XXXXXX")"
APP="$BUILD/Payload/Workspace OS.app"
mkdir -p "$APP"
SDK="$(xcrun --sdk "$KIND" --show-sdk-path)"
TARGET=arm64-apple-ios16.5
if [ "$KIND" = iphonesimulator ]; then TARGET=arm64-apple-ios16.5-simulator; fi
xcrun swiftc -parse-as-library -O -target "$TARGET" -sdk "$SDK" -module-name WorkspaceOSPad -module-cache-path "$BUILD/ModuleCache" -framework SwiftUI -framework UIKit -framework UniformTypeIdentifiers "$ROOT/Sources/WorkspacePad.swift" -o "$APP/WorkspaceOSPad"
cp "$ROOT/Info.plist" "$APP/Info.plist"
for size in 120 152 167 180; do
  sips -z "$size" "$size" "$ROOT/AppIcon.png" --out "$APP/Icon$size.png" >/dev/null
done
codesign --force --sign - --timestamp=none "$APP"
if [ "$KIND" = iphoneos ]; then
  (cd "$BUILD" && ditto -c -k --keepParent Payload WorkspaceOS-iPad-1.0.0-preview.ipa)
  shasum -a 256 "$BUILD/WorkspaceOS-iPad-1.0.0-preview.ipa"
fi
echo "$APP"
