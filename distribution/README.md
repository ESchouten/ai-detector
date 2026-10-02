# Application installers and updates

One application release contains the browser app, native detector, FFmpeg and optional pinned Docker image metadata. Users open **AI Detector** and configure it in their browser. Native execution is the default; Docker is an advanced option.

## Installation and data

| Target | Installer | Desktop integration |
| --- | --- | --- |
| macOS 14+ Apple Silicon | `AI-Detector-VERSION-macos-arm64.dmg` | Drag to Applications. The menu bar offers Open dashboard, Open at login, Check for Updates and Quit. Login startup uses Apple's `SMAppService`. |
| Windows 10 22H2+ / Windows 11 x64 | `AI-Detector-VERSION-windows-x64-setup.zip` | Extract the ZIP and run its setup EXE. Velopack installs for the current user and opens the app. First launch offers login startup. The tray offers Open dashboard, Start at login, Check for Updates and Quit. |
| Ubuntu 22.04/24.04 amd64 | `AI-Detector-VERSION-linux-amd64.deb` | Installs under `/opt/ai-detector` with Applications and XDG login entries. Upgrade through the package manager. |

Closing the browser leaves monitoring active. **Pause** disables saved automatic resume. **Quit** drains monitoring and preserves the enabled choice for next launch. Desktop startup runs after login, under that user's account; keep the computer awake while monitoring is needed.

The first download must come from the official repository and be trusted independently. Updates prove continuity with the key bundled in that installed copy. Releases are not Apple-notarized or signed with a Windows publisher certificate. macOS may require explicit approval in Privacy & Security; Windows may show SmartScreen warnings or block unknown applications under Smart App Control or managed policies. The application does not disable these OS protections.

Settings, models and recordings stay outside installed application files:

- macOS: `~/Library/Application Support/AI Detector`
- Windows: `%LOCALAPPDATA%\AI Detector` (the application itself uses `%LOCALAPPDATA%\AIDetector\current`)
- Linux: `$XDG_DATA_HOME/ai-detector`, defaulting to `~/.local/share/ai-detector`

`AIDETECTOR_DATA_DIR` selects another data directory. Legacy portable installations with adjacent `config.json` retain their location. Keep a backup of the complete data folder. Updates and normal uninstallers preserve data. Older portable Windows applications require manual replacement and do not offer in-app updates. The current Windows ZIP contains an installer; applications installed through it support in-app updates.

The first updater-enabled release must be installed manually. On Mac, quit the previous application and replace it in Applications. For an older Windows **Inno Setup** installation, quit AI Detector, uninstall the old program, then run the new setup; its external data remains available. This avoids two installed copies and an old uninstaller that owns the same startup entry. Subsequent installed Windows releases update through Velopack.

For legacy releases that kept data beside the executable, retain that whole old folder until migration finishes. On the new application's first setup screen choose **Use existing setup**, select the old folder, and import. The existing setup steps are populated with the saved cameras, rules and notification settings; recordings remain viewable. Copying is the default, with an optional link to the old archive for large collections. See the [import guide](../web/README.md#bring-an-existing-installation-into-setup). Do not uninstall or delete a legacy folder containing the only copy of its data before importing it.

## Update behavior

[Sparkle 2.10.0](https://sparkle-project.org/documentation/) handles Mac updates. [Velopack 1.2.158](https://docs.velopack.io/integrating/overview) handles Windows installation and updates. Their versions are pinned in `macos/build-launcher.sh`, `.config/dotnet-tools.json` and `windows/Directory.Packages.props` and the lockfiles.

The native menu checks for updates, downloads after confirmation, then offers a restart. **Include preview updates** considers the newest published build from either channel. It starts checked for preview installations and unchecked for official installations; the saved preference survives updates. Turning it off restricts updates to official releases. Windows can then install an older official release; Mac keeps the installed preview until a newer official build is available, because Sparkle does not support downgrades. Downloads leave monitoring running. Automatic checks run daily; they do not silently restart monitoring. Windows disables Velopack's automatic apply-on-startup. Mac disables Sparkle's automatic download/install option. Deferred Windows downloads remain available as **Update and restart**, provided they still match the chosen channel preference.

On Mac, Sparkle's normal termination request asks the web child to stop through its private pipe and waits for a successful exit. Losing the native parent leaves monitoring running; a failed explicit shutdown cancels the termination request. On Windows, the launcher first asks the web child to drain, waits for its successful exit, then calls `WaitExitThenApplyUpdates` before exiting itself. This also keeps a slow detector shutdown outside Velopack's 60-second exit-wait deadline. A failed download leaves the running version available and offers a retry. A download replaces a corrupt cached package immediately; a deferred update with unreadable metadata clears its package so the next attempt can download again. Update failures include their operation and exception in Velopack's log at `%LOCALAPPDATA%\velopack\velopack_AIDetector.log`.

Framework tools generate binary deltas against previous full packages. Feeds retain up to three versions; Sparkle can generate direct deltas from up to two available previous archives, and Velopack can chain retained deltas. A deleted archive (HTTP 404) is skipped as a delta base and removed from the staged feed. Mac staging retains only successfully downloaded bases, so removed previews do not reappear in the next published feed. Other HTTP errors and checksum failures still stop the build. Both frameworks can fall back to a full download. Download savings depend on the actual changed bytes; rebuilding or re-signing components can affect delta size. The current workflow still rebuilds the detector for each application release.

## Launcher boundaries

`web/desktop/runtime.ts` binds the dashboard port before SvelteKit initialization. A second invocation verifies a nonce-based HMAC response from the local instance before opening its dashboard. It cannot start a second detector or mistake an unrelated service for AI Detector. `--background` suppresses the initial browser launch. `--quit` requests authenticated shutdown and waits for the existing process to exit.

`windows/launcher` is a small .NET Framework 4.8 application, using the runtime already included in supported Windows versions. It calls Velopack's startup hooks before starting the bundled `ai-detector-web.exe`. The web child announces readiness through stdout; the port owner or a reattached controller announces readiness and gets a tray icon. `web/desktop/host.ts` accepts `quit` through stdin. Losing the native parent pipe leaves monitoring running; reopening the native menu attaches to the existing authenticated instance. Detector configuration and supervision remain in the web application.

Both native launchers restart an unexpectedly exited web process, including exit zero, after 2, 4, 8, 16 and then 30 seconds. There is no attempt limit; ten minutes of running resets the delay. Automatic restarts suppress opening another browser tab. Quit and update shutdown cancel pending retries and drain the child. The private `AI_DETECTOR_STOPPING` marker also suppresses recovery for authenticated `--quit`. A termination signal sent directly to the web process drains it, but its still-running native owner resumes it; native app termination cancels recovery. A token-matched `desktop-shutdown.json` receipt carries the owner's shutdown outcome to a reattached menu, so a failed drain cannot become a successful update restart. This is process-exit recovery, not a watchdog for hung processes or a service that runs before login. Separately managed Linux and Docker deployments retain their external supervisor.

Both native launchers retain the web child's `AI_DETECTOR_ERROR ` diagnostic from stderr and display it once. Diagnostics are single-line, bounded summaries; ordinary logs keep flowing without being retained in the Mac launcher. The web runtime only opens its own error dialog for standalone Windows execution. A detector that exits unsuccessfully during draining, or needs a forced stop, causes an unsuccessful web-process exit and prevents the native updater from treating that shutdown as successful. Pausing still saves the disabled startup choice when draining fails.

`windows/launcher/Updates` adds signature verification at Velopack’s update-source boundary. `SignedFeed` verifies the Ed25519 signature with Bouncy Castle before parsing the release list; `SignedUpdateSource` supplies verified metadata to Velopack and retains a signed copy for a deferred restart. `VerifiedUpdateManager` checks cached packages against signed SHA256 hashes, including immediately before shutdown. Windows sets Velopack's `MaximumDeltasBeforeFallback` to zero: delta reconstruction re-compresses the ZIP, which need not match the signed full-archive size or hash even when its extracted contents are identical. Downloading the original full package preserves that verification without a failed delta attempt. Downloads and replacement remain Velopack’s responsibility; the separately installed NVIDIA runtime is reused. Mac still uses Sparkle deltas. New Windows feeds omit deltas, including historical entries, so older installed launchers also take the full-download path. Existing published assets are left in place.

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

Install uv, Node, pnpm and Bun. The Python version is pinned once in [`detector/.python-version`](../detector/.python-version); other CI tool versions live in `toolchain.json`, and pnpm follows `web/package.json`. uv supplies the pinned Python on every OS, including security releases without official Windows/macOS installers. Windows launcher builds also need the listed .NET SDK. Linux installer builds need `desktop-file-validate` and `dpkg-deb`.

From the repository root, one command builds a complete native preview, checks setup/detection/graceful shutdown, and creates its installer:

```sh
uv run --project detector --extra default --with-requirements distribution/requirements.txt python distribution/build.py all
```

The command checks the host OS and CPU architecture, required tools, an optional frozen detector and the output destination before compilation. It rejects unsupported or mismatched targets. Previews use version `0.0.0` with production updates disabled. The command installs locked component dependencies and uses an isolated environment for packaging tools. It never installs the resulting application or enables startup.

Use `--output /path/to/a/fresh/directory` for another build. To iterate on the desktop without freezing Python again, add `--detector /path/to/aidetector.app` on Mac or the frozen `aidetector` folder on Windows/Linux. Relative input/output paths resolve from the directory where the command is launched, including when a build stage runs a tool from the repository root. Nonempty preview output folders are rejected before building. Build metadata and existing standalone FFmpeg staging are restored after each stage, including a failed build. Combined builds exclude standalone FFmpeg assets. PyInstaller specifications and intermediates stay under `detector/build/`; frozen programs go under `detector/dist/`, and the compiled web executable goes under `web/dist/`. Run one build at a time in a checkout because compilation uses the component build directories.

CI uses `python distribution/build.py detector --platform PLATFORM`, `web --platform PLATFORM` and `launcher --platform PLATFORM --output DIRECTORY` as separate stages. The launcher stage writes `mac-launcher` plus `sparkle/`, or `windows-launcher/`, under its output directory. These commands also support local component builds, sharing the same PyInstaller hooks, compiler warmup and FFmpeg staging. Desktop releases distribute the complete application; component tags publish containers only. The detector stage's `--type default` or `--type windowsml` selects both build metadata and the installed dependency extra; Windows ML requires Windows. CUDA and TensorRT builds require an explicitly prepared GPU dependency environment and `--skip-dependencies`, so a normal dependency sync cannot replace it. `--name` accepts an artifact filename rather than an output path.

On Linux, the `default` extra obtains Torch and Torchvision from PyTorch's CPU index. This avoids bundling several gigabytes of unused CUDA libraries into the native installer. The `nvidia` extra and NVIDIA container runtime keep their GPU dependencies; Mac builds retain MPS support. Install one inference extra at a time: `default`, `nvidia`, or `windowsml`. Use the pinned uv 0.12.19; CI reads that requirement from `detector/pyproject.toml`.

Windows application builds also stage `detector/nvidia-runtime/`: the same detector source, a small entry script, uv and its licenses, a `runtime.json` generated from the shared `detector/.python-version` pin, and two locks exported from the canonical detector lockfile: `pylock.toml` for CUDA and `pylock.tensorrt.toml` for the optional optimization. GPU binaries are not included. On Windows 10 and Windows 11, automatic inference on an NVIDIA device with compute capability 7.5 or newer selects this runtime. Driver branch 572 or newer is required. PyTorch checkpoints run directly through CUDA; compute capability 8.0+ additionally tries direct TensorRT engines. Explicit ONNX providers, snapshot-only configurations and Docker bypass this download; computers without a supported NVIDIA device retain the bundled Windows ML runtime. This bootstrap belongs to the complete application, not the standalone one-file detector.

The web process manager uses uv to install Python and binary dependencies in the application's data directory. Windows NVIDIA dependencies select PyTorch 2.11.0/Torchvision 0.26.0 from the official CUDA 12.8 index and ONNX Runtime GPU below 1.27 to retain CUDA 12.8 compatibility. The exported locks contain URLs and SHA-256 hashes; installations require hashes. CUDA dependencies and TensorRT native libraries/bindings use wheels. The sole source-package exception is NVIDIA's small pure-Python `tensorrt-cu12` wrapper; it does not compile CUDA/C++. Its internal pip installer is disabled so uv owns dependency installation. The optional group pins TensorRT 10.16.1.11 for CUDA 12 and sources its library wheels from NVIDIA's index. uv 0.12.19's pylock installer is experimental, so its executable is pinned and the actual Windows download/install path is tested in the application workflow. No system Python, CUDA Toolkit or driver installer is invoked.

Environments live under `runtimes/nvidia/<dependency-hash>/` beside `runtimes/python/` and `cache/uv/`. The identity includes the Python version and exported dependency lock, not the application version. App updates therefore reuse dependencies while running the updated bundled source. uv's package cache and hardlinks reuse unchanged wheels when dependencies change. A successful GPU kernel check publishes `ready.json`; incomplete downloads remain retryable. Every launch checks the GPU again, even for a cached environment. Pause/quit abort and reap the active preparation child. Failed preparation stays visible without silently switching to CPU. Older cached environments are retained for app rollback; the settings backup excludes these runtime/cache directories.

TensorRT is installed only after the CUDA check passes, before the detector process starts. `tensorrt.json` records optional readiness or a 24-hour retry delay, keyed by its separate lock, GPU UUID and driver. An unavailable optional package leaves CUDA usable; cancellation still stops startup. A successful library/builder check adds the internal `--prefer-tensorrt` flag. The Python adapter owns engine building and its separate compatibility cache in `models/prepared/tensorrt/`; see [detector architecture](../detector/ARCHITECTURE.md). It starts monitoring with cached engines or CUDA, then prepares missing engines serially in the background. The helper builds through Ultralytics and runs GPU smoke predictions before publishing, with a thirty-minute deadline per model. After all attempts finish, a `models_ready` record asks the desktop to drain and restart monitoring once if any new engines are available. Pause/quit prevents relaunch; failed-only, cached-only and cancelled attempts do not request it. Engines are generated on the user's GPU and are never bundled into installers.

`test_nvidia_runtime.py` checks the staged source and resolves both hashed Windows locks without downloading GPU binaries. `web/tests/nvidia-runtime.test.ts` covers selection, cache reuse, cancellation, optional fallback/retry, failed preparation and managed process startup. Application CI stages the same payload with `python distribution/nvidia_runtime.py OUTPUT --version REF` in an independent Windows job and sets `NVIDIA_RUNTIME_BUNDLE` for `nvidia-runtime-installed.test.ts`: it installs the real CUDA and TensorRT packages, imports the native libraries and validates the CLI. Hosted runners have no GPU; the test also verifies that a missing GPU never publishes readiness. `test_prepared_engines.py` has an additional real engine build/inference test that requires CUDA and TensorRT. GPU performance and model accuracy still need qualification on an NVIDIA machine with representative footage.

Application version parsing uses `semver`, pinned in `build-requirements.txt`. The shared CI setup action installs these small build dependencies before running stages; `requirements.txt` includes them for local builds and packaging tests. For individual web or launcher stages outside CI, install `build-requirements.txt` first. Detector-only builds do not load packaging dependencies. Tag prefixes and the numeric installer version remain application policy; semantic-version validation belongs to the library.

Detector and distribution Python tooling uses the repository's `ruff.toml`; CI does not maintain separate distribution lint rules. The root `.dockerignore` owns the web Docker build context and excludes local settings, recordings, reports and staged native FFmpeg assets. The detector's Docker context is its own directory and uses `detector/.dockerignore`.

PyInstaller discovers ONNX imports normally and includes its data and package metadata. The unused `onnx.reference` evaluator and `onnxruntime.quantization` tools that import it are excluded because they crash the Windows DLL scan. The detector exports FP32/FP16 models, without INT8 calibration. ONNX Runtime remains the inference engine, including FP16 conversion support; packaged smoke tests cover both an ONNX model and conversion of a PyTorch checkpoint, including reuse of the converted model.

`package.py` assembles the payload used by the native installer. A complete local build creates one installer for the platform, without an additional portable ZIP or `.sha256` sidecar. Release publishing wraps the Windows setup EXE in a ZIP and attaches Mac and Linux installers directly. For development or troubleshooting, `python distribution/build.py archive APPLICATION_FOLDER` can explicitly create a portable ZIP from an assembled folder; these archives are not published with application releases.

Fast checks:

```sh
uv run --project detector --extra default --with-requirements distribution/requirements.txt python -m unittest discover -s distribution -p 'test_*.py'
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

Set `SPARKLE_SDK` to the extracted SDK on Mac for the real delta round-trip test. Set `WINDOWS_LAUNCHER` to the compiled launcher directory on Windows for the Velopack full-update packaging test. Set `DESKTOP_WEB_EXECUTABLE` to the built web executable to exercise normal, failed and hung detector shutdowns and an occupied dashboard port. These tests compile a small detector fixture and allow the real 30-second shutdown deadline to expire. CI supplies the paths on each matching runner. Fixtures use temporary data and public test keys; they never install the app, enable login startup or contact cameras. Mac bundle tests need LaunchServices access, and disk-image creation needs `hdiutil`.

The payload smoke starts the web executable directly, verifies browser setup, native detection and a real image archive, then requires successful graceful shutdown. A timeout or nonzero exit fails the smoke; force-killing is failure cleanup only. Separate lifecycle tests exercise the actual Mac process owner through quit, parent crash, reopen, failed drain and diagnostic delivery. Readiness waits have explicit deadlines and report the captured logs. Downloaded-app installation, update/relaunch UI, login startup and hardware inference still require qualification on each target OS.

Mac artwork lives in `macos/`; regenerate it with `swift distribution/macos/render-artwork.swift`. Regenerate the Windows icon with `python distribution/windows/render-artwork.py` (Pillow required). Include the generated assets when changing the artwork.

## CI and release structure

Pull requests and pushes to `main` run the affected web, detector and distribution checks. Feature branches can run them manually; pushing an application test tag runs a self-contained release build without also triggering the branch test workflows.

Application builds start native compilation, the matching NVIDIA image, web/detector checks and a fresh NVIDIA runtime installation test in parallel. Each installer waits for its own platform's tested binaries; Windows and Linux also require the image digest for their optional Docker mode. macOS packaging has no NVIDIA dependency. Publication requires all three installers, workflow lint, both test suites and the NVIDIA installation check. Native steps use a YAML anchor, installers share `.github/actions/package-application`, and `.github/actions/test-distribution` is shared with ordinary distribution CI. Release runs remain serialized because both channels update the same feeds.

The build summary links each job with its result and duration and lists installer artifact sizes. Skipped jobs have no duration. Failed test/build jobs retain diagnostics for seven days. Native artifacts retain executable permissions and framework symlinks in a tar archive for seven days; installer artifacts remain the downloads documented below. A packaging-only retry can reuse tested binaries from the same run while that artifact is retained. Changes to the detector dependency manifest or lock also trigger distribution checks. The independent NVIDIA check installs production web dependencies with scripts disabled and omits the Bun compiler and frontend development tools; the actual CUDA/TensorRT installation remains a fresh install.

Container layers use separate GHCR registry cache tags for application, standalone detector architectures and web architectures. These caches are reusable across version tags and do not occupy the GitHub Actions dependency cache. Detector image jobs clean the ephemeral runner only below a 35 GiB free-space budget; lightweight web and manifest jobs skip cleanup. The detector Dockerfile pins both Ultralytics base digests and installs dependencies before copying source or stamping a version. The web image pins a multi-platform Node 24 base digest. Update base digests deliberately and qualify the corresponding target; the ARM64 detector base must remain compatible with the supported Jetson generation.

Standalone container releases build amd64 and arm64 on native runners, using shared build and manifest steps for both components. Builds upload candidate images by digest and smoke-check that exact image: the detector CLI must start, and the web image must execute its bundled FFmpeg and serve the setup page. GPU execution still requires target hardware. Version/latest tags are published only after both architectures, the component's reusable test suite and workflow lint succeed. A failed test leaves the published release tags untouched; digest artifacts are retained for seven days for retries.

Linux packages explicitly use Zstandard level 9, supported by the Ubuntu 22.04/24.04 packaging tools. Windows uses Velopack's `BestSpeed` delta strategy, and macOS uses Sparkle's LZFSE delta compression. These choices preserve payload contents while favoring build time over the smallest possible download. The installer tests extract Linux packages and reconstruct Windows/macOS deltas to check contents. PyInstaller relies on upstream hooks for ImageIO's FFmpeg binary and ONNX Runtime provider libraries; dynamic Ultralytics and LiteLLM modules still receive full collection. Windows ML also requires full ONNX Runtime collection because its model preparation helpers import Python files using runtime path changes. The packaged PT-model smoke test exercises this path on Windows before an installer can be published.

Local measurements on 2026-10-01 informed these compression choices. Repacking the existing Linux release payload on Ubuntu 22.04 took 480 seconds with the default compression versus 25 seconds with Zstandard level 9; the package grew from 409 to 462 MiB. Level 3 took seven seconds but produced a 502 MiB package. Velopack 1.2.158 generated a representative binary delta in 82.4 seconds with `BestSize` versus 2.2 seconds with `BestSpeed`, with a 3% larger delta and identical reconstructed files. These Apple Silicon host measurements compare compression strategies, not end-to-end GitHub runner times or Windows GPU performance.

Sparkle's representative binary-delta comparison took 161.7 seconds with LZMA versus 144.8 seconds with LZFSE, with a 1.3% larger delta. Both reconstructed identical file contents and permissions. Binary differencing still dominates this case; faster compression alone does not remove the whole delta-generation cost. The signed feed and update round-trip tests exercise the selected compression too.

## GitHub Actions previews

Push an `app/test-*` tag at the commit you want to test:

```sh
git tag app/test-2026-09-25-1
git push origin app/test-2026-09-25-1
```

Choose a new tag name for each build. The tagged commit must include this workflow's test-tag trigger. GitHub runs **Application download** from that commit, even when the workflow is not yet on `main`.

After every platform passes, download the installer from the resulting GitHub **prerelease**. The run also retains `AI-Detector-macos-arm64`, `AI-Detector-windows-x64` and `AI-Detector-linux-x64` under **Artifacts**. Each artifact ZIP contains just one installer: the Mac `.dmg`, Windows setup `.exe`, or Linux `.deb`. The installer includes the web app, detector and FFmpeg. Separate Mac and Windows `update-files-*` artifacts hold updater payloads and signed feeds used by the publishing job; they are not needed for installation.

Versioned application releases offer one installer download per OS: a Windows ZIP containing only the setup EXE, a Mac DMG and a Linux DEB. The Windows ZIP preserves the download route used for earlier releases where direct EXE downloads were blocked. Windows full `.nupkg` packages and available Mac `.delta` files remain attached for automatic updates. Sparkle uses the same `.dmg` as manual installation. Signed feeds live only on the dedicated feed releases; duplicate versioned feeds, portable application ZIPs and separate `.sha256` files are not published. Velopack's package hashes inside the signed feed and Sparkle's archive signatures remain required. GitHub's automatically generated source-code archives and Actions artifact ZIP wrappers are separate from these application assets.

Preview installers display `0.0.N`, where `N` is the Application download workflow's increasing run number. GitHub marks the release as a prerelease. Every release also has an internal build version `N.0.0`, shared across both channels. Sparkle uses it as `CFBundleVersion`, while `CFBundleShortVersionString` remains the visible release version. Windows retains its package version and includes the build version in authenticated update metadata. This allows a newly published preview to follow an official release with a higher display version. Keep the workflow run-number sequence increasing; do not reset it when renaming or replacing the workflow.

Older clients and Mac delta generation retain the separate **app-preview-updates** and **app-updates** feeds. New clients use the combined **app-update-channels** feed. Sparkle applies its native channel filter; Windows filters authenticated metadata before Velopack selects and installs the package. Both channels require the configured signing key. Each preview also publishes its matching NVIDIA image under its commit-specific tag.

Install the first updater-enabled preview manually. Older `0.0.0` previews have no updater. Subsequent installed Mac and Windows releases receive this channel-selection feature through their existing updater. Use **Include preview updates** and **Check for Updates** in the native menu. Downloads preserve configuration and recordings. These are alternative installations of the same application, not two applications to run side by side. Older portable Windows applications and Linux packages still require manual updates.

When the workflow is available on `main`, **Run workflow** with a development branch selected publishes the same preview channel. The release receives an immutable `app/test-run-RUN_ID` tag at the tested commit. Retrying a failed run keeps its version and tag; after successful publication, start a new run or push a new test tag instead of rebuilding a published version.

Prefer a pushed test tag when the branch changes workflow files. GitHub can publish an existing tag with its normal workflow token. Creating a release tag from a branch whose workflow files differ from `main` requires a repository `RELEASE_TOKEN` secret with Contents and Workflows write permissions; the built-in token cannot receive Workflows permission. The workflow uses that token when configured. See [GitHub's release API permissions](https://docs.github.com/en/rest/releases/releases#create-a-release).

## Release publishing

Use increasing, stable `app/vX.Y.Z` tags. Prerelease/build-suffix versions are rejected by this stable channel. Use `app/test-*` tags or manual branch runs for the separate preview channel.

The workflow reads signed release history from the selected channel, downloads delta bases only for Mac, and invokes `generate_appcast` or `vpk pack --delta None` for Windows. `update_channels.py` verifies the other channel's published feed and combines both choices into a newly signed feed. Once every platform succeeds, the workflow publishes the versioned release, updates its channel's compatibility feed, and promotes the combined feeds to **app-update-channels**. Asset URLs remain immutable. Fixed feeds avoid GitHub's ambiguous “latest release”, which may refer to a separate web or detector release. Release runs are serialized across both channels to prevent competing feed promotions; NVIDIA, Windows, Mac and Linux builds within a run still execute in parallel. A build must advance the sequence across both channels. Keep historical versioned assets available; existing clients and retained deltas reference them. Do not edit a published application version in place.

See [the workflow map](../.github/README.md) for triggers, checks and local debugging commands.

Configure two entries in **Settings → Secrets and variables → Actions**:

- Repository variable `SPARKLE_PUBLIC_KEY`: the base64 public Ed25519 key, pinned in both desktop applications.
- Repository secret `SPARKLE_PRIVATE_KEY`: the exact 32-byte seed, base64-encoded, exported by Sparkle 2.10's `generate_keys -x`. This existing key is used for both platforms. Keep it backed up; fixtures' public test keys must never be used for releases.

Every tagged release reuses the same key. The workflow checks that both entries exist before building; it exposes the private key only to the signing steps, and never puts it in a download. No Apple, Microsoft or certificate-authority account is required.

AI Detector's production Sparkle key is backed up in the maintainer's macOS login Keychain under account `io.github.eschouten.ai-detector`. Use Sparkle's `generate_keys --account io.github.eschouten.ai-detector -p` to retrieve its public key. When transferring the key to another Mac, follow [Sparkle's key export/import instructions](https://sparkle-project.org/documentation/#eddsa-ed25519-signatures) with that same account. Keep private exports outside the checkout, restrict file permissions, and remove them after transfer. GitHub Secrets cannot be read back as a backup. Do not replace either key independently: installed applications trust the public key embedded in their release.

Mac payloads receive ad-hoc code signatures, which satisfy local code integrity requirements without establishing a publisher identity. Sparkle signs the feed and update archives with our Ed25519 key. Both feed and pre-extraction signature verification are required; feed verification failures never expire into an unsigned fallback.

For Windows, `release_signatures.py` signs the exact UTF-8 Velopack feed bytes prefixed with `AI Detector Windows updates v1\n`. The published `releases.win.json` is a JSON envelope containing base64 `payload` and `signature` fields. Keeping both in one asset avoids a feed/signature publication race. Python's `cryptography` signs at build time; Bouncy Castle verifies on the client. Versions, package URLs, sizes and SHA256 hashes are all covered by the signature. Velopack verifies packages against these authenticated hashes. Unsigned feeds, mismatched keys and modified packages fail closed; cached updates are verified again before monitoring shuts down. A deferred restart can use its cached signed feed without an internet connection.

Signature verification prevents an attacker without our private key from introducing a new update. It cannot stop a host from hiding updates or replaying a previously signed feed. Windows accepts an older build only when leaving an installed preview for official releases; a newer build may have a lower display version when changing channels. Sparkle always requires a newer internal build version. The first installer still needs an independently trusted source, and compromising the release signing key or its build workflow compromises update trust. OS publisher trust and reputation are separate from this guarantee.

Before publishing the first real pair of versions, qualify a signed update on Mac and Windows: leave monitoring active during download, defer the restart, then apply it and confirm monitoring resumes with the same configuration, recordings and login preference. Also test a missed-version/full-download fallback and recovery from an interrupted download. Fixtures do not establish successful installation on a clean machine, OS acceptance or hardware behavior.

## Existing Linux Docker startup

`linux_startup.py` remains a separate Python 3.10+ helper for an existing systemd Docker Engine installation. Run it as the desktop user; it requests sudo for Docker configuration and daemon startup. See the [installation command](../README.md#start-automatically-on-a-jetson-or-linux-desktop). Docker supervises the existing Compose project.

The helper copies its launcher to `$XDG_DATA_HOME/ai-detector/startup.py` and writes `$XDG_CONFIG_HOME/autostart/ai-detector.desktop`. At login it waits for the dashboard before opening the browser. It does not change automatic-login settings. Uninstalling the helper removes only those startup files. Jetson image/runtime qualification and independently managed Compose updates remain separate from native desktop updates.

The Linux DEB depends on `libcap2-bin` and applies `cap_net_bind_service` only to `/opt/ai-detector/AI Detector` in `postinst configure`, including upgrades. This allows the default port 80 without running the dashboard as root. Portable/source Linux deployments must choose an unprivileged port or arrange the equivalent permission themselves.

The common builder logs command durations. Local PyInstaller builds reuse processed libraries; `--clean` opts into clearing them. Tagged CI builds do not save this cache because GitHub restricts reuse across different tags. Mac update preparation downloads its two delta bases concurrently; packaging and feed publication still use their established ordering.
