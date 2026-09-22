# Application installers and startup

The release boundary is the complete application: browser app, native detector, FFmpeg and optional pinned Docker image metadata. Users open **AI Detector**, follow setup in their browser and reopen the same shortcut for later use. Native execution is the automatic default; Docker remains an explicit advanced option.

## Platform packages

| Target                   | Installer                                   | Desktop integration                                                                                                                                                                                                                                             |
| ------------------------ | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| macOS 14+ Apple Silicon  | `AI-Detector-VERSION-macos-arm64.dmg`       | Drag the `.app` to Applications. Tagged releases require signing and notarization. A menu-bar app provides Open dashboard, Open at login and Quit. Login startup uses Apple's `SMAppService`, with the user's choice and any required System Settings approval. |
| Windows 11 24H2+ x64     | `AI-Detector-VERSION-windows-x64-setup.exe` | Inno Setup installs under the current user's Programs directory, adds a Start-menu shortcut and uninstaller, and offers login startup. The installer requests graceful application shutdown before upgrade or removal and waits for its process to finish.      |
| Ubuntu 22.04/24.04 amd64 | `AI-Detector-VERSION-linux-amd64.deb`       | The package manager installs under `/opt/ai-detector`, adds an Applications entry and a standard XDG login-startup entry. Startup Applications can disable it. Removal/upgrade first requests graceful shutdown of the installed executable.                    |

These are packaging targets. Clean-machine installation, actual camera operation and hardware acceleration must be qualified on each supported target before claiming a verified release. This change does not retroactively sign older downloads. Portable ZIPs remain available for technical users; keep their files together. The macOS ZIP contains the same app bundle.

Closing a browser tab leaves monitoring active. **Pause** disables saved automatic resume. Quitting the application stops its runtime gracefully and preserves the enabled choice for next launch. Use Quit in the macOS menu bar, the Windows Start-menu “Quit AI Detector” shortcut, or the Ubuntu application’s Quit context action. Windows uninstall/upgrade and Linux package removal/upgrade also coordinate shutdown. New desktop installations keep data in the user's data directory; existing portable installations with adjacent `config.json` retain that location. Ordinary installer updates and uninstallers do not delete settings or recordings. Monitoring status and Pause are browser controls; Windows and Linux do not currently have a tray menu.

Desktop automatic startup means **after login**, under the same account as interactive operation. It is not a pre-login service or a promise that GPU providers work under another account. The app must stay running and the computer must stay awake. The existing Jetson Docker helper below has a separate boot contract.

## Executable lifecycle

`distribution/desktop-instance.ts` is copied by the executable adapter into its compilation input. The server binds its port before initializing SvelteKit, so a second launch cannot start a second detector. It publishes a random identity token in the user's data directory (owner-only permissions on POSIX). A second invocation verifies a nonce-based HMAC response from the fixed loopback endpoint before opening the existing dashboard. A port occupied by an unrelated service is an error, not an invitation to open that service. Redirects are refused. The token is never sent to the endpoint.

`--background` starts without opening a browser. `--quit` requires the same authenticated local protocol and waits for the original process to finish draining; a shutdown timeout fails the operation. Normal launch and login startup open the browser. The endpoint is a narrow desktop-instance protocol, not an authenticated remote-control API. It does not make the web app suitable for public exposure.

SvelteKit's `init` hook initializes saved monitoring at server startup, independently of any HTTP request. Build-time imports do not start detection. The parent sends `stop\n` through stdin; EOF also requests shutdown. The detector drains accepted work. Application shutdown preserves enabled monitoring; an explicit dashboard pause disables it. Runtime health and readiness remain separate from successful process launch.

## Build and verification

`application.yml` builds each installer from the same commit as the optional NVIDIA image. It checks distribution scripts and launcher protocol tests, smoke-tests ONNX and PT inference in each frozen detector, checks/builds the web app, assembles the payload and boots the complete bundle with generated local media. No camera, external alert service or pretrained-weight download is needed for that smoke.

Run the commands below from the repository root with Python 3.12, Node 24 and Bun 1.3.9 available. Install the pinned web dependencies first (`pnpm --dir web install --frozen-lockfile` with pnpm 9.15.9). Build the frozen detector using the complete **Build detector** step in [the workflow](../.github/workflows/application.yml), which includes its required PyInstaller hooks. Build the web payload with `AI_DETECTOR_WEB_TARGET=darwin-arm64 pnpm --dir web build` for the macOS example. These commands require macOS and Xcode Command Line Tools and produce an **unsigned local preview**, not a release.

Compile the menu-bar executable before packaging:

```sh
xcrun swiftc -parse-as-library -target arm64-apple-macos14.0 \
  distribution/macos/Launcher.swift -o /tmp/ai-detector-launcher
python distribution/package.py \
  --detector detector/dist/aidetector --web web/dist/ai-detector-web \
  --ffmpeg web/node_modules/ffmpeg-static/ffmpeg \
  --output application-dist --platform macos-arm64 --version 0.0.0 \
  --mac-launcher /tmp/ai-detector-launcher
python distribution/smoke.py application-dist/AI-Detector-macos-arm64
python distribution/installers.py application-dist/AI-Detector-macos-arm64 \
  --platform macos-arm64 --version 0.0.0
```

Output payload directories must be fresh. Packaging preserves framework symlinks, executable permissions and the data boundary. Version inputs are validated before entering native installer metadata. The CLI platform name for Linux is `linux-x64`; its Debian artifact uses the architecture name `amd64`. Windows installer creation requires Inno Setup; Linux installer creation requires `desktop-file-validate` and `dpkg-deb`. Building an installer does not install it.

For contributors, after installing the web dependencies above:

```sh
python -m unittest discover -s distribution -p 'test_*.py'
node --test distribution/desktop-instance.test.ts
```

Tests build only temporary package trees and launch local fixture processes. They never register login items, install a package, enable a service or contact a camera. The Bun integration fixture proves initialization without a browser request, a second launch without a second initialization, retention of the HTTP port while async shutdown completes, and release of its UDP socket on quit. A separate child-process fixture verifies that the quit command waits through delayed draining. Tests also check package layouts/checksums, symlinks, refusal to overwrite, desktop-entry validity where available, source-independent startup and bounded failure handling. macOS launcher compilation is checked on the macOS release runner. Windows installer compilation and `.deb` construction run on their native runners.

The Bun fixture is skipped if Bun or the installed adapter is missing; Linux desktop-entry integration is skipped on other platforms. Check the skip reasons rather than treating a shorter successful run as equivalent coverage. The release workflow installs these dependencies before running the fixtures. The complete-bundle smoke on macOS starts the bundled web executable directly; it does not exercise clicking the AppKit launcher, approving a login item or reopening after desktop login. Local unsigned DMG creation and `hdiutil verify` passed; those checks establish image construction and integrity, not publisher trust or OS acceptance.

## Signing and release gates

A tag matching `app/v*` cannot publish through the release job unless every native build and signing step succeeds. Manual workflow runs produce **unsigned preview artifacts** for developers, never production releases. No Gatekeeper or Windows signature bypass is part of installation.

Configure these GitHub release secrets:

- macOS: `MACOS_CERTIFICATE_BASE64` (Developer ID Application `.p12`), `MACOS_CERTIFICATE_PASSWORD`, `MACOS_SIGN_IDENTITY` (full `Developer ID Application: …` name), `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` for notarization.
- Windows: `WINDOWS_CERTIFICATE_BASE64` (trusted code-signing `.pfx`) and `WINDOWS_CERTIFICATE_PASSWORD`. The signing helper uses Windows SDK SignTool with SHA-256 and a timestamp, preserves already-valid vendor signatures, verifies new signatures, and also signs the installer and uninstaller through Inno Setup. Organizations using hardware-backed or hosted signing must connect their approved signing service in that helper; a nonexportable key cannot be converted into this PFX credential.

Apple signing runs from a temporary CI keychain, signs nested native code before the enclosing app, enables hardened runtime, notarizes/staples the app, then creates and notarizes/staples the disk image. The JIT entitlement applies only to the bundled Bun/Python executables. Signing keys are removed in the workflow's final cleanup. The signed application payload is launch-tested again. Checksums and ZIPs are regenerated after signing. A checksum is integrity metadata, not a publisher signature.

External gates remain real: trusted signing credentials, clean downloaded-artifact installation, Windows/macOS hardware inference and login startup, OS local-network permissions, clean Ubuntu package installation and upgrade, sleep/lid behavior, reboot tests and the precise Jetson appliance image. CI fixtures and compilation cannot establish those outcomes. New Windows publishers can still encounter reputation prompts despite a valid signature.

References: [Apple login items](https://developer.apple.com/documentation/servicemanagement/smappservice), [Apple notarization](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow), [Inno per-user installation](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm), [Inno signed uninstallers](https://jrsoftware.org/ishelp/topic_setup_signeduninstaller.htm), [desktop entries](https://specifications.freedesktop.org/desktop-entry/latest-single/).

## Existing Linux Docker startup

`linux_startup.py` remains a separate Python 3.10+ helper for an existing systemd Docker Engine installation. Run it as the desktop user; it requests sudo for Docker configuration and daemon startup. See the [installation command](../README.md#start-automatically-on-a-jetson-or-linux-desktop). It validates Compose restart policies, enables Docker's existing service, and starts the same Compose project. Docker remains the container supervisor; no competing detector service is installed.

It copies its launcher to `$XDG_DATA_HOME/ai-detector/startup.py` and writes `$XDG_CONFIG_HOME/autostart/ai-detector.desktop`, using the standard home-directory defaults. At login it waits up to five minutes for HTTP success, follows the home redirect, then opens the browser. Reinstall updates the same files; uninstall removes only those files. It does not alter automatic-login settings. Headless containers run without browser activity.

The JetPack 6 Compose example uses the matching NVIDIA image/runtime. This helper does not install Docker/drivers, add browser control of separately managed detectors or turn the native desktop application into a pre-login service. Detector configuration changes in that separate Compose deployment still require its documented restart.
