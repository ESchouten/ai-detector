#!/bin/bash
set -euo pipefail

# Keep the framework and its release tools together; verify the pinned upstream archive.
sdk=$1
output=$2
mkdir -p "$sdk"
curl --fail --location --silent --show-error \
  https://github.com/sparkle-project/Sparkle/releases/download/2.10.0/Sparkle-2.10.0.tar.xz \
  --output "$sdk/Sparkle.tar.xz"
echo "c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c  $sdk/Sparkle.tar.xz" | shasum -a 256 --check
tar -xf "$sdk/Sparkle.tar.xz" -C "$sdk"
xcrun swiftc -parse-as-library -target arm64-apple-macos14.0 \
  -module-cache-path "$sdk/module-cache" -F "$sdk" -framework Sparkle \
  -Xlinker -rpath -Xlinker @executable_path/../Frameworks \
  "$(dirname "$0")/DesktopProcess.swift" "$(dirname "$0")/Launcher.swift" -o "$output"
