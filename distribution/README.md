# Application installers and updates

One application release contains the browser app, native detector, FFmpeg and optional pinned Docker image metadata. Users open **AI Detector** and configure it in their browser. Native execution is the default; Docker is an advanced option.

## Installation and data

| Target | Installer | Desktop integration |
| --- | --- | --- |
| macOS 14+ Apple Silicon | `AI-Detector-VERSION-macos-arm64.dmg` | Drag to Applications. The menu bar offers Open dashboard, Open at login, Check for Updates and Quit. Login startup uses Apple's `SMAppService`. |
| Windows 11 24H2+ x64 | `AI-Detector-VERSION-windows-x64-setup.exe` | Velopack installs for the current user and opens the app. First launch offers login startup. The tray offers Open dashboard, Start at login, Check for Updates and Quit. |
| Ubuntu 22.04/24.04 amd64 | `AI-Detector-VERSION-linux-amd64.deb` | Installs under `/opt/ai-detector` with Applications and XDG login entries. Upgrade through the package manager. |

Closing the browser leaves monitoring active. **Pause** disables saved automatic resume. **Quit** drains monitoring and preserves the enabled choice for next launch. Desktop startup runs after login, under that user's account; keep the computer awake while monitoring is needed.

The first download must come from the official repository and be trusted independently. Updates prove continuity with the key bundled in that installed copy. Releases are not Apple-notarized or signed with a Windows publisher certificate. macOS may require explicit approval in Privacy & Security; Windows may show SmartScreen warnings or block unknown applications under Smart App Control or managed policies. The application does not disable these OS protections.

Settings, models and recordings stay outside installed application files:

- macOS: `~/Library/Application Support/AI Detector`
- Windows: `%LOCALAPPDATA%\AI Detector` (the application itself uses `%LOCALAPPDATA%\AIDetector\current`)
- Linux: `$XDG_DATA_HOME/ai-detector`, defaulting to `~/.local/share/ai-detector`

`AIDETECTOR_DATA_DIR` selects another data directory. Legacy portable installations with adjacent `config.json` retain their location. Keep a backup of the complete data folder. Updates and normal uninstallers preserve data. Windows portable ZIPs require manual replacement and do not offer in-app updates.

The first updater-enabled release must be installed manually. On Mac, quit the previous application and replace it in Applications. For an older Windows **Inno Setup** installation, quit AI Detector, uninstall the old program, then run the new setup; its external data remains available. This avoids two installed copies and an old uninstaller that owns the same startup entry. Subsequent installed Windows releases update through Velopack.

## Update behavior

[Sparkle 2.10.0](https://sparkle-project.org/documentation/) handles Mac updates. [Velopack 1.2.158](https://docs.velopack.io/integrating/overview) handles Windows installation and updates. Their versions are pinned in `macos/build-launcher.sh`, `.config/dotnet-tools.json` and `windows/Directory.Packages.props` and the lockfiles.

The native menu checks for updates, downloads after confirmation, then offers a restart. Downloads leave monitoring running. Automatic checks run daily; they do not silently restart monitoring. Windows disables Velopack's automatic apply-on-startup. Mac disables Sparkle's automatic download/install option. Deferred Windows downloads remain available as **Update and restart**.

On Mac, Sparkle's normal termination request asks the web child to stop through its private pipe and waits for a successful exit. Losing the native parent also drains the child; a failed shutdown cancels the termination request. On Windows, the launcher first asks the web child to drain, waits for its successful exit, then calls `WaitExitThenApplyUpdates` before exiting itself. This also keeps a slow detector shutdown outside Velopack's 60-second exit-wait deadline. A failed download leaves the running version available and offers a retry. Unusable cached packages are removed so retry downloads a fresh copy; a deferred update with unreadable metadata returns to that same download path.

Framework tools generate binary deltas against previous full packages. The last three versions remain in the feed; Sparkle can generate direct deltas from the previous two, and Velopack can chain retained deltas. Both frameworks can fall back to a full download. Download savings depend on the actual changed bytes; rebuilding or re-signing components can affect delta size. The current workflow still rebuilds the detector for each application release.

## Launcher boundaries

`web/desktop/runtime.ts` binds the dashboard port before SvelteKit initialization. A second invocation verifies a nonce-based HMAC response from the local instance before opening its dashboard. It cannot start a second detector or mistake an unrelated service for AI Detector. `--background` suppresses the initial browser launch. `--quit` requests authenticated shutdown and waits for the existing process to exit.

`windows/launcher` is a small .NET Framework 4.8 application, using the runtime already included in supported Windows versions. It calls Velopack's startup hooks before starting the bundled `ai-detector-web.exe`. The web child announces readiness through stdout; only the process that owns the dashboard port announces readiness and gets a tray icon. `web/desktop/host.ts` accepts `quit` through stdin. Losing the native parent pipe also drains monitoring. Detector configuration and supervision remain in the web application.

Both native launchers retain the web child's `AI_DETECTOR_ERROR ` diagnostic from stderr and display it once. Diagnostics are single-line, bounded summaries; ordinary logs keep flowing without being retained in the Mac launcher. The web runtime only opens its own error dialog for standalone Windows execution. A detector that exits unsuccessfully during draining, or needs a forced stop, causes an unsuccessful web-process exit and prevents the native updater from treating that shutdown as successful. Pausing still saves the disabled startup choice when draining fails.

`windows/launcher/Updates` adds signature verification at Velopack’s update-source boundary. `SignedFeed` verifies the Ed25519 signature with Bouncy Castle before parsing the release list; `SignedUpdateSource` supplies verified metadata to Velopack and retains a signed copy for a deferred restart. `VerifiedUpdateManager` checks cached packages against signed SHA256 hashes, including immediately before shutdown. Downloads, delta reconstruction and replacement remain Velopack’s responsibility.

The native shell and web executable are separate files within one tested application version. There is no separate user-facing web/detector update choice. The optional NVIDIA image remains identified by its matching digest.

The Mac payload embeds PyInstaller's `aidetector.app` under `Contents/Helpers/Detector.app`. PyInstaller separates Python resources from native libraries and preserves their runtime paths. Relative links expose the detector and application metadata beside the web executable without putting unsigned Python files in `Contents/MacOS`.

## Code map

| Change | Owner |
| --- | --- |
| Port ownership, parent pipe, browser launch and graceful shutdown | `web/desktop/runtime.ts`, `host.ts`, `instance.ts`, `browser.ts` |
| Installed and development data-directory rules | `web/desktop/paths.ts`, also imported by the server stores |
| Optional LAN discovery | `web/desktop/network.ts`, using `bonjour-service` |
| Native menus and process ownership | `macos/Launcher.swift`, `macos/DesktopProcess.swift`, `windows/launcher/` |
| Common build stages | `build.py`; release automation invokes these same commands |
| Platform payload layouts and archives | `package.py`, with one assembly function per platform |
| Native installer creation | `installers.py` |
| Shared public test data | `fixtures/` |

The executable adapter still needs a small integration patch: upstream 0.1.7 has no application-bootstrap hook or extra Bun compiler arguments. The patch copies `web/desktop`, delegates startup to `startDesktop`, passes compile arguments and fixes target-dependent executable naming. SvelteKit asset discovery, embedding and HTTP handling remain with the adapter. Remove the patch when upstream provides equivalent hooks; do not move application logic back into it.

The desktop source participates in normal web formatting, ESLint complexity limits, TypeScript checks and dependency rules. It does not import web feature services. Test fixtures import the actual runtime; no test rewrites production source text.

## Local builds and tests

Install uv, Node, pnpm and Bun. Pinned CI versions live in `toolchain.json`; pnpm follows `web/package.json`. Windows launcher builds also need the listed .NET SDK. Linux installer builds need `desktop-file-validate` and `dpkg-deb`.

From the repository root, one command builds a complete native preview, checks setup/detection/graceful shutdown, and creates its installer:

```sh
uv run --no-project --python 3.11 --with-requirements distribution/requirements.txt python distribution/build.py all
```

The command checks the host OS and CPU architecture, required tools, an optional frozen detector and the output destination before compilation. It rejects unsupported or mismatched targets. Previews use version `0.0.0` with production updates disabled. The command installs locked component dependencies and uses an isolated environment for packaging tools. It never installs the resulting application or enables startup.

Use `--output /path/to/a/fresh/directory` for another build. To iterate on the desktop without freezing Python again, add `--detector /path/to/aidetector.app` on Mac or the frozen `aidetector` folder on Windows/Linux. Relative input/output paths resolve from the directory where the command is launched, including when a build stage runs a tool from the repository root. Nonempty preview output folders are rejected before building. Build metadata and existing standalone FFmpeg staging are restored after each stage, including a failed build. Combined builds exclude standalone FFmpeg assets. PyInstaller specifications and intermediates stay under `detector/build/`; frozen programs go under `detector/dist/`, and the compiled web executable goes under `web/dist/`. Run one build at a time in a checkout because compilation uses the component build directories.

CI uses `python distribution/build.py detector --platform PLATFORM`, `web --platform PLATFORM` and `launcher --platform PLATFORM --output DIRECTORY` as separate stages. The launcher stage writes `mac-launcher` plus `sparkle/`, or `windows-launcher/`, under its output directory. Standalone component releases use the same PyInstaller hooks, compiler warmup and FFmpeg staging. The detector stage's `--type default` or `--type windowsml` selects both build metadata and the installed dependency extra; Windows ML requires Windows. CUDA and TensorRT builds require an explicitly prepared GPU dependency environment and `--skip-dependencies`, so a normal dependency sync cannot replace it. `--name` accepts an artifact filename rather than an output path.

Application version parsing uses `semver`, pinned in `build-requirements.txt`. The shared CI setup action installs these small build dependencies before running stages; `requirements.txt` includes them for local builds and packaging tests. For individual web or launcher stages outside CI, install `build-requirements.txt` first. Detector-only builds do not load packaging dependencies. Tag prefixes and the numeric installer version remain application policy; semantic-version validation belongs to the library.

Detector and distribution Python tooling uses the repository's `ruff.toml`; CI does not maintain separate distribution lint rules. The root `.dockerignore` owns the web Docker build context and excludes local settings, recordings, reports and staged native FFmpeg assets. The detector's Docker context is its own directory and uses `detector/.dockerignore`.

PyInstaller discovers ONNX imports normally and includes its data and package metadata. The unused `onnx.reference` evaluator is excluded because importing it crashes the Windows DLL scan. ONNX Runtime remains the inference engine; packaged smoke tests cover both an ONNX model and conversion of a PyTorch checkpoint, including reuse of the converted model.

`package.py` assembles the application folder without archiving it. After validation and installer creation, `python distribution/build.py archive APPLICATION_FOLDER` creates the final ZIP and checksum once. The complete local build follows the same ordering.

Fast checks:

```sh
uv run --no-project --python 3.11 --with-requirements distribution/requirements.txt python -m unittest discover -s distribution -p 'test_*.py'
pnpm --dir web quality
bun test ./web/desktop/host.test.ts
```

The VS Code **Distribution: tests** task supplies these Python dependencies automatically. `Desktop distribution tests` runs on pull requests on Mac, Windows and Linux, without requiring an NVIDIA build or production credentials. It includes native compilation, Windows tray tests, packaging tests and parent-process lifecycle tests.

Windows checks can also run directly:

```sh
dotnet tool restore
dotnet restore distribution/windows/launcher-tests/Launcher.Tests.csproj --locked-mode
dotnet build distribution/windows/launcher/Launcher.csproj --no-restore --configuration Release --warnaserror
dotnet test distribution/windows/launcher-tests/Launcher.Tests.csproj --no-restore --configuration Release
dotnet restore distribution/windows/update-tests/Update.Tests.csproj --locked-mode
dotnet test distribution/windows/update-tests/Update.Tests.csproj --no-restore --configuration Release
```

NuGet package versions live in `windows/Directory.Packages.props`. A configuration test checks that the separately pinned Velopack CLI matches the runtime package. The launcher and WinForms tests explicitly target `win-x64`, matching the installer and keeping NuGet lockfiles consistent across build hosts. After changing their dependencies, regenerate both lockfiles with `dotnet restore distribution/windows/launcher-tests/Launcher.Tests.csproj --force-evaluate`; CI continues to use locked restore. Portable update/recovery tests run on every OS; WinForms tray tests execute only on Windows.

Set `SPARKLE_SDK` to the extracted SDK on Mac for the real delta round-trip test. Set `WINDOWS_LAUNCHER` to the compiled launcher directory on Windows for the Velopack package/delta reconstruction test. Set `DESKTOP_WEB_EXECUTABLE` to the built web executable to exercise normal, failed and hung detector shutdowns and an occupied dashboard port. These tests compile a small detector fixture and allow the real 30-second shutdown deadline to expire. CI supplies the paths on each matching runner. Fixtures use temporary data and public test keys; they never install the app, enable login startup or contact cameras. Mac bundle tests need LaunchServices access, and disk-image creation needs `hdiutil`.

The payload smoke starts the web executable directly, verifies browser setup, native detection and a real image archive, then requires successful graceful shutdown. A timeout or nonzero exit fails the smoke; force-killing is failure cleanup only. Separate lifecycle tests exercise the actual Mac process owner through quit, parent crash, reopen, failed drain and diagnostic delivery. Readiness waits have explicit deadlines and report the captured logs. Downloaded-app installation, update/relaunch UI, login startup and hardware inference still require qualification on each target OS.

Mac artwork lives in `macos/`; regenerate it with `swift distribution/macos/render-artwork.swift`. Regenerate the Windows icon with `python distribution/windows/render-artwork.py` (Pillow required). Include the generated assets when changing the artwork.

## GitHub Actions previews

Push an `app/test-*` tag at the commit you want to test:

```sh
git tag app/test-2026-09-25-1
git push origin app/test-2026-09-25-1
```

Choose a new tag name for each build. The tagged commit must include this workflow's test-tag trigger. GitHub runs **Application download** from that commit, even when the workflow is not yet on `main`.

Open the run in **Actions**, then download `AI-Detector-macos-arm64`, `AI-Detector-windows-x64` or `AI-Detector-linux-x64` under **Artifacts**. Extract the artifact ZIP to find the installer. Each download includes the web app, detector and FFmpeg. Preview installers use version `0.0.0`; the application records the tag so builds remain identifiable.

Preview builds also publish their matching NVIDIA image under its commit-specific tag. They do not create a GitHub release, publish update feeds or enable production updates. When the workflow is available on `main`, **Run workflow** with a development branch selected provides the same preview behavior.

## Release publishing

Use increasing, stable `app/vX.Y.Z` tags. Prerelease/build-suffix versions are rejected by this stable channel. Use `app/test-*` tags or manual branch runs for previews with production updates disabled.

The workflow downloads the previous update bases, verifies the signed Windows feed and base checksum, and invokes `generate_appcast` or `vpk pack`. It uploads complete installers, full update packages and deltas to the versioned application release. Once every platform succeeds, it publishes that release and promotes only `appcast.xml` and `releases.win.json` to the fixed **app-updates** GitHub release. Asset URLs point at immutable `app/vX.Y.Z` releases. The fixed feed avoids GitHub's ambiguous “latest release”, which may refer to a separate web or detector release. Builds are serialized, and a stable version cannot replace an equal or newer version in the feed. Keep historical versioned assets available; existing clients and retained deltas reference them. Do not edit a published application version in place.

Configure two entries in **Settings → Secrets and variables → Actions**:

- Repository variable `SPARKLE_PUBLIC_KEY`: the base64 public Ed25519 key, pinned in both desktop applications.
- Repository secret `SPARKLE_PRIVATE_KEY`: the exact 32-byte seed, base64-encoded, exported by Sparkle 2.10's `generate_keys -x`. This existing key is used for both platforms. Keep it backed up; fixtures' public test keys must never be used for releases.

Every tagged release reuses the same key. The workflow checks that both entries exist before building; it exposes the private key only to the signing steps, and never puts it in a download. No Apple, Microsoft or certificate-authority account is required.

AI Detector's production Sparkle key is backed up in the maintainer's macOS login Keychain under account `io.github.eschouten.ai-detector`. Use Sparkle's `generate_keys --account io.github.eschouten.ai-detector -p` to retrieve its public key. When transferring the key to another Mac, follow [Sparkle's key export/import instructions](https://sparkle-project.org/documentation/#eddsa-ed25519-signatures) with that same account. Keep private exports outside the checkout, restrict file permissions, and remove them after transfer. GitHub Secrets cannot be read back as a backup. Do not replace either key independently: installed applications trust the public key embedded in their release.

Mac payloads receive ad-hoc code signatures, which satisfy local code integrity requirements without establishing a publisher identity. Sparkle signs the feed and update archives with our Ed25519 key. Both feed and pre-extraction signature verification are required; feed verification failures never expire into an unsigned fallback.

For Windows, `release_signatures.py` signs the exact UTF-8 Velopack feed bytes prefixed with `AI Detector Windows updates v1\n`. The published `releases.win.json` is a JSON envelope containing base64 `payload` and `signature` fields. Keeping both in one asset avoids a feed/signature publication race. Python's `cryptography` signs at build time; Bouncy Castle verifies on the client. Versions, package URLs, sizes and SHA256 hashes are all covered by the signature. Velopack verifies packages against these authenticated hashes. Unsigned feeds, mismatched keys and modified packages fail closed; cached updates are verified again before monitoring shuts down. A deferred restart can use its cached signed feed without an internet connection.

Signature verification prevents an attacker without our private key from introducing a new update. It cannot stop a host from hiding updates or replaying a previously signed feed. Velopack rejects downgrades relative to the installed version. The first installer still needs an independently trusted source, and compromising the release signing key or its build workflow compromises update trust. OS publisher trust and reputation are separate from this guarantee.

Before publishing the first real pair of versions, qualify a signed update on Mac and Windows: leave monitoring active during download, defer the restart, then apply it and confirm monitoring resumes with the same configuration, recordings and login preference. Also test a missed-version/full-download fallback and recovery from an interrupted download. Fixtures do not establish successful installation on a clean machine, OS acceptance or hardware behavior.

## Existing Linux Docker startup

`linux_startup.py` remains a separate Python 3.10+ helper for an existing systemd Docker Engine installation. Run it as the desktop user; it requests sudo for Docker configuration and daemon startup. See the [installation command](../README.md#start-automatically-on-a-jetson-or-linux-desktop). Docker supervises the existing Compose project.

The helper copies its launcher to `$XDG_DATA_HOME/ai-detector/startup.py` and writes `$XDG_CONFIG_HOME/autostart/ai-detector.desktop`. At login it waits for the dashboard before opening the browser. It does not change automatic-login settings. Uninstalling the helper removes only those startup files. Jetson image/runtime qualification and independently managed Compose updates remain separate from native desktop updates.
