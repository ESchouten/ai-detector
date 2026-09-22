#!/bin/bash
set -euo pipefail
: "${MACOS_CERTIFICATE_BASE64:?Release certificate is required}"
: "${MACOS_CERTIFICATE_PASSWORD:?Certificate password is required}"
: "${MACOS_SIGN_IDENTITY:?Developer ID identity is required}"
: "${APPLE_ID:?Apple ID is required}"
: "${APPLE_TEAM_ID:?Apple team is required}"
: "${APPLE_APP_PASSWORD:?Notarization password is required}"
keychain="$RUNNER_TEMP/ai-detector-signing.keychain-db"
certificate="$RUNNER_TEMP/ai-detector-signing.p12"
password="$(openssl rand -hex 32)"
export SIGNING_CERTIFICATE_FILE="$certificate"
python3 - <<'PY'
import base64, os
from pathlib import Path
file = Path(os.environ['SIGNING_CERTIFICATE_FILE'])
file.write_bytes(base64.b64decode(os.environ['MACOS_CERTIFICATE_BASE64']))
file.chmod(0o600)
PY
security create-keychain -p "$password" "$keychain"
security set-keychain-settings -lut 21600 "$keychain"
security unlock-keychain -p "$password" "$keychain"
security import "$certificate" -P "$MACOS_CERTIFICATE_PASSWORD" -A -t cert -f pkcs12 -k "$keychain"
security set-key-partition-list -S apple-tool:,apple:,codesign: -k "$password" "$keychain"
security list-keychains -d user -s "$keychain"
xcrun notarytool store-credentials ai-detector-release --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" --keychain "$keychain"
printf 'MACOS_NOTARY_KEYCHAIN_PROFILE=ai-detector-release\n' >> "$GITHUB_ENV"
rm "$certificate"
