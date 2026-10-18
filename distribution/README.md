# Application installers and updates

One application release contains the browser application, the native detector and FFmpeg. People open **AI Detector** and set it up in their browser.

## Installation and data

The [user guide](../README.md#install) lists the supported systems and the download for each. What each installer sets up:

- **macOS**: a menu-bar menu with Open dashboard, Open at login, Check for Updates and Quit.
- **Windows**: the program for the current user, in `%LOCALAPPDATA%\AIDetector\current`, and a tray menu with the same entries.
- **Ubuntu**: the program under `/opt/ai-detector`, with an Applications and a login entry.

Login startup runs after login, under that user's account. It is not a service that monitors before anyone signs in.

Releases are not notarized by Apple or signed with a Windows publisher certificate, so macOS may ask for approval in Privacy & Security and Windows may show SmartScreen or block the installer under Smart App Control. The first download must therefore come from the official repository. Updates after that are verified against a key built into the installed copy; see [how updates are trusted](#how-updates-are-trusted).

Settings, models and recordings live in the [data folder](../README.md#good-to-know), outside the installed program, and updates and uninstallers leave them alone. On Linux that folder follows `$XDG_DATA_HOME`, and `AIDETECTOR_DATA_DIR` selects another folder on every system.

The released detector and web executables kept `config.json`, `app.json` and `detections/` beside the program; the [import guide](../web/README.md#bring-an-existing-installation-into-setup) moves such a folder into the application.

## Updates

[Sparkle](https://sparkle-project.org/documentation/) updates the Mac application and [Velopack](https://docs.velopack.io/integrating/overview) installs and updates the Windows one. Their versions are pinned in `macos/build-launcher.sh`, `windows/dotnet-tools.json`, `windows/Directory.Packages.props` and the lockfiles.

The native menu checks daily and on request, downloads after confirmation while monitoring keeps running, and then offers a restart. Nothing is installed or restarted silently. **Include preview updates** considers the newest build of either channel; it starts on for preview installations and off for official ones. Turning it off on Windows can install an older official release; the Mac keeps its preview until a newer official build exists, because Sparkle does not downgrade.

Before an update is applied the launcher asks the web process to stop and waits for it to drain the detector and exit successfully. A detector that fails to drain cancels the update restart rather than being cut off. A failed download leaves the running version in place.

Mac updates can be binary deltas against the previous releases, with a full download as fallback. Windows always downloads the full package: rebuilding a package from a delta re-compresses it, and the result would not match the size and hash that the signed feed vouches for.

## How updates are trusted

Both platforms use one Ed25519 key pair. The public key is built into every installed application.

- **Mac**: Sparkle verifies the signed feed and each archive before extracting it. Payloads carry ad-hoc code signatures, which satisfy local integrity checks without naming a publisher.
- **Windows**: `release_signatures.py` signs the exact bytes of the Velopack feed, prefixed with `AI Detector Windows updates v1\n`. The published `releases.win.json` is an envelope holding that payload and its signature together, so they cannot be published out of step. In the launcher, `SignedFeed` verifies the signature before the release list is parsed, and `VerifiedUpdateManager` checks every cached package against the signed SHA-256 hashes, again immediately before shutting monitoring down.

An unsigned feed, a wrong key or a changed package is refused; there is no unsigned fallback. This stops anyone without the private key from introducing an update. It does not stop a host from hiding updates or replaying an older signed feed, and it does not replace the operating system's publisher trust. Whoever controls the signing key or the release workflow controls updates.

## Launchers

The native launchers own the menu, login startup and updates. Everything about cameras and detection stays in the web application.

- `web/desktop/runtime.ts` binds the dashboard port before SvelteKit starts. A second launch proves with a nonce-based HMAC exchange that the port belongs to AI Detector, then opens its dashboard; it cannot start a second detector. `--background` suppresses opening the browser and `--quit` requests an authenticated shutdown and waits for it.
- Both launchers restart a web process that exits unexpectedly, after 2, 4, 8, 16 and then 30 seconds, without a limit; ten minutes of running resets the delay. Quit and update shutdown cancel that. This is recovery from an exit, not a watchdog for a hung process.
- Losing the native menu leaves the web process and monitoring running. Opening the application again attaches a new menu to the running instance.
- The web process reports a fatal problem as one bounded `AI_DETECTOR_ERROR ` line on stderr, which the launcher shows once.
- The web process says `AI_DETECTOR_MONITORING on` or `off` on stderr, ten seconds after it starts and within ten seconds of monitoring being switched on or off. While it is on, the launcher asks the system not to go to sleep by itself: an activity with `idleSystemSleepDisabled` on a Mac, `SetThreadExecutionState` on Windows. The request stays while the web process restarts and ends with the launcher. A menu attached to an already running instance cannot hear that server, so it holds the request for as long as it is attached. A closed lid still puts a laptop to sleep, and a Windows laptop with Modern Standby honours the request for five minutes on battery. The Linux package has no launcher and leaves sleep to the system's own settings.
- `windows/launcher` is a small .NET Framework 4.8 program, using the runtime that supported Windows versions already include.
- The Mac bundle embeds PyInstaller's `aidetector.app` under `Contents/Helpers/Detector.app` and links to it, so no unsigned Python files sit in `Contents/MacOS`.

The SvelteKit executable adapter carries a small patch: upstream has no application-bootstrap hook and no way to pass compiler arguments. The patch delegates startup to `web/desktop` and holds no application logic. Remove it when upstream offers the hooks.

## Windows NVIDIA runtime

The Windows installer carries no GPU binaries. When automatic inference finds an NVIDIA device with compute capability 7.5 or newer, the web application's process manager downloads a CUDA environment into the data folder and runs the same detector source in it. With driver branch 580 or newer that environment uses CUDA 13.2. An older driver from branch 560 on gets CUDA 12.6, except on Blackwell cards such as the RTX 50 series, which CUDA 12.6 predates. Otherwise starting stops with a request to update the driver, and does not fall back to Windows ML. An explicit ONNX provider and a configuration without a YOLO model bypass the download; a computer without such a device uses the bundled Windows ML build.

- The build stages `detector/nvidia-runtime/`: the detector source, an entry script, uv, a `runtime.json` naming the Python version, and four locks exported from the detector's lockfile: `pylock.cuda13.toml` and `pylock.cuda12.toml` from the `nvidia` and `nvidia-cuda12` extras, and `pylock.tensorrt-cuda13.toml` and `pylock.tensorrt-cuda12.toml` from the optional TensorRT groups. Every package is pinned by URL and SHA-256.
- uv installs Python and the packages under `runtimes/nvidia/<hash>/`, with its cache in `cache/uv/`. The hash covers the Python version and the lock, not the application version, so an application update reuses the environment and runs its own newer detector source in it. A driver update across branch 580 prepares the other environment once.
- A GPU check must pass before `ready.json` marks the environment complete, and runs again at every launch. An interrupted download is retried; a failure stays visible and never silently falls back to the CPU. Pause and quit stop a running preparation.
- On compute capability 8.0 and newer, TensorRT is installed after the CUDA check. If that fails, CUDA stays in use and the attempt is deferred for 24 hours. Engines are built on the user's GPU by the detector (see [inference backends](../detector/ARCHITECTURE.md#inference-backends)) and are never shipped.

`test_nvidia_runtime.py` checks the staged payload and resolves every lock without downloading GPU binaries. CI installs the real packages of both CUDA versions on a Windows runner; it has no GPU, so GPU speed and model accuracy still need an NVIDIA machine with representative footage.

## Code map

| Change | Owner |
| --- | --- |
| Port ownership, parent pipe, browser launch, graceful shutdown | `web/desktop/runtime.ts`, `host.ts`, `instance.ts`, `browser.ts` |
| Data-folder rules | `web/desktop/paths.ts`, also used by the server |
| Network discovery (`aidetector.local`) | `web/desktop/network.ts` |
| Native menus and process ownership | `macos/Launcher.swift`, `macos/DesktopProcess.swift`, `windows/launcher/` |
| Verified Windows updates | `windows/launcher/Updates/` |
| Build stages | `build.py`; CI calls the same commands |
| Payload layout per platform | `package.py` |
| Installers | `installers.py` |
| Update feeds, deltas and signatures | `updates.py`, `update_channels.py`, `release_signatures.py`, `sign_macos.py` |
| Reusing a frozen detector in CI | `tested_detector.py` |
| Public test data | `fixtures/` |

## Local builds and tests

Install uv, Node, pnpm and Bun. Python is pinned in [`detector/.python-version`](../detector/.python-version), other tools in `toolchain.json`, and pnpm in `web/package.json`. Windows launcher builds need the listed .NET SDK; Linux installer builds need `desktop-file-validate` and `dpkg-deb`.

One command builds a complete preview for the computer it runs on, checks setup, detection and graceful shutdown, and creates the installer:

```sh
uv run --project detector --extra default --with-requirements distribution/requirements.txt python distribution/build.py all
```

It checks the host, the tools and the output folder before compiling. Previews have version `0.0.0` and updates disabled, and the command never installs the result. Use `--output` for another empty folder and `--detector PATH` to reuse an already frozen detector. Run one build at a time per checkout.

CI runs the stages separately: `build.py detector`, `web` and `launcher --output DIRECTORY`. `--version` is the numeric application version, `--ref` the Git reference the programs report, and `--channel preview` makes a test build that keeps the presets it was built with. `build.py stamp-detector FOLDER --ref REF` writes a new reference into an already frozen detector, which CI uses to skip freezing when the detector's sources did not change.

Install one inference extra at a time: `default`, `nvidia`, `nvidia-cuda12` or `windowsml`. On Linux, `default` takes Torch from PyTorch's CPU index, which keeps several gigabytes of unused CUDA libraries out of the installer. Linux packages are compressed with Zstandard level 9 and Mac deltas with LZFSE: both give a slightly larger download for a much shorter build.

Fast checks:

```sh
uv run --project detector --extra default --with-requirements distribution/requirements.txt python -m unittest discover -s distribution -p 'test_*.py'
pnpm --dir web quality
bun test ./web/desktop/host.test.ts
```

Windows launcher checks; the last two, the portable update tests, also run on macOS and Linux:

```sh
dotnet tool restore --tool-manifest distribution/windows/dotnet-tools.json
dotnet restore distribution/windows/launcher-tests/Launcher.Tests.csproj --locked-mode
dotnet build distribution/windows/launcher/Launcher.csproj --no-restore --configuration Release --warnaserror
dotnet test distribution/windows/launcher-tests/Launcher.Tests.csproj --no-restore --configuration Release
dotnet restore distribution/windows/update-tests/Update.Tests.csproj --locked-mode
dotnet test distribution/windows/update-tests/Update.Tests.csproj --no-restore --configuration Release
```

After changing NuGet dependencies, regenerate the lockfiles with `dotnet restore … --force-evaluate`.

Some tests need a built artifact and are skipped without it: set `SPARKLE_SDK` to the extracted SDK for the Mac delta round trip, `WINDOWS_LAUNCHER` to the compiled launcher folder for the Velopack package test, and `DESKTOP_WEB_EXECUTABLE` to the built web executable for the shutdown and occupied-port tests. They use temporary data and public test keys and never install anything.

What no test here establishes: installing a downloaded application on a clean machine, the update and relaunch dialogs, login startup, and inference on real hardware.

Regenerate the artwork with `swift distribution/macos/render-artwork.swift` and `python distribution/windows/render-artwork.py`. The first also renders the home screen icons in `web/static/`, from the web application's favicon and `macos/home-screen-icon.svg`.

## GitHub Actions previews

Push a `test-*` tag at the commit to test, with a new name for each build:

```sh
git tag test-2026-09-25-1
git push origin test-2026-09-25-1
```

GitHub runs **Application download** from that commit. When every platform passes, the installers are on the resulting **prerelease**: a Windows ZIP holding the setup EXE, a Mac DMG and a Linux DEB. The `.nupkg` and `.delta` files beside them are for automatic updates. The container image is published under the tag's name, and as the branch whose newest commit was tagged, such as `rework-stars`. The run can also be started by hand for a branch, which publishes to the same preview channel and that branch's image.

Previews show version `0.0.N`, where `N` is the workflow's run number. Every release also has an internal build version `N.0.0` that orders builds across both channels, so a preview can follow an official release with a higher display version. Keep the workflow's file name and its run-number sequence.

A published build is never rebuilt. Retry a failed run; after a successful one, push a new tag.

Prefer a pushed tag when the branch changes workflow files. Creating the release tag from a manual run on such a branch needs a repository secret `RELEASE_TOKEN` with Contents and Workflows write permission, because GitHub's built-in token cannot be given the second.

[CI workflows](#ci-workflows) describes the jobs, their artifacts and how to debug a failure.

## Publishing a release

Push an increasing `vX.Y.Z` tag. A version with a build suffix is rejected.

A version with a prerelease suffix, such as `v1.0.0-rc.0`, is a release candidate. It is published on the preview channel under that name, which the release page and the application's sidebar show. Windows, macOS and Linux show its preview version `0.0.N`, by which updaters order it among the previews, so test builds pushed after it still reach its installations. Its installations receive the official release as any preview installation does. Like any preview it keeps the presets it was built with. Its container image is published as `1.0.0-rc.0`, never as `latest`.

The workflow reads the signed history of the channel, builds the Mac deltas and the Windows packages, and combines both channels into one newly signed feed. When every platform has succeeded it publishes the versioned release and promotes the feeds to the fixed **app-update-channels** release, which the launchers read; **app-updates** and **app-preview-updates** hold each channel's own history, from which the Mac deltas and the combined feed are built. Release runs are serialized because both channels write the same feeds. Never edit or delete a published version: installed applications and retained deltas refer to it.

Two entries under **Settings → Secrets and variables → Actions** are required:

- variable `SPARKLE_PUBLIC_KEY`: the base64 public Ed25519 key built into both launchers;
- secret `SPARKLE_PRIVATE_KEY`: the 32-byte seed, base64-encoded, as exported by Sparkle's `generate_keys -x`.

The production key is backed up in the maintainer's macOS login Keychain under account `io.github.eschouten.ai-detector`; `generate_keys --account io.github.eschouten.ai-detector -p` prints its public half. GitHub Secrets cannot be read back, so that Keychain entry is the backup. Never replace one half without the other: installed applications trust the public key they were built with. The public test keys in `fixtures/` must never sign a release.

Before the first real pair of versions, try a signed update on a Mac and on Windows: leave monitoring running during the download, defer the restart, apply it, and confirm that monitoring resumes with the same settings, recordings and login preference. Also try an update that skips a version and one whose download was interrupted.

## CI workflows

| Workflow | Runs on | Does |
| --- | --- | --- |
| [Application download](../.github/workflows/application.yml) | `v*`, `test-*`, manual | Checks all three systems, builds and tests the native applications, then publishes signed official or preview updates and the container image. |
| [Detector Tests](../.github/workflows/detector-tests.yml) | Relevant pull requests and pushes to `main`, manual, and every application build | Lint, formatting and types; tests on three systems, with branch coverage on Linux; schemas and the wheel. |
| [Web and setup tests](../.github/workflows/web-tests.yml) | The same | Unit tests on three systems; static checks, the production server and Compose checks on Linux. |
| [Desktop distribution tests](../.github/workflows/distribution-tests.yml) | Relevant pull requests and pushes to `main`, manual | Native launchers, the compiled web process, installers and update packages. |
| [Container image](../.github/workflows/container-tests.yml) | Pull requests and pushes to `main` that change the `Dockerfile`, its ignore file or the dependency files it installs from, manual | Builds the image for amd64 and arm64 without publishing it and runs the container smoke check. |
| [End-to-end test](../.github/workflows/e2e-tests.yml) | Every pull request and push to `main`, manual | Sets up Cow Catcher in the browser, with a camera that plays the example clip, and receives its alerts. |
| [Workflow syntax](../.github/workflows/workflow-tests.yml) | Every application build and distribution test run | Lints workflow files and their embedded scripts. |

An application build runs the detector and web checks for the exact commit it releases. After the release configuration, these start together: native compilation per system, those checks, and a real installation of the Windows NVIDIA runtime. Each installer waits only for its own system's binaries, and the desktop tests for those binaries run beside packaging. Publication needs every installer, test and check to succeed. Runs are serialized across official and preview releases because both write the same update feeds.

Freezing the detector is the slowest step, and its result depends only on the detector's sources, its locked dependencies and the build scripts. A preview build therefore first looks for an earlier application build of this repository that froze and smoke-tested the same inputs, takes that build's binaries, and writes its own reference into `aidetector/version.py`, which the freeze keeps as a plain file for this purpose. If none is found, or anything on that path fails, it freezes and smoke-tests as usual. Official `v*` releases always freeze afresh. Editing `application.yml`, `build.py` or the PyInstaller hooks changes those inputs, so the next build freezes again. `tested_detector.py` accepts an earlier build only from this repository's own tag or manual runs, never from a pull request.

Artifacts of a run:

- `native-build-PLATFORM`: the tested binaries, including the launcher, as a tar to keep executable permissions and macOS symlinks, kept seven days so a packaging retry can reuse them. A small `detector-PLATFORM-HASH` marker beside it names the detector inputs it contains.
- `AI-Detector-PLATFORM`: one installer each, a Mac `.dmg`, a Windows setup `.exe` or a Linux `.deb`.
- `update-files-PLATFORM` (Mac and Windows): update packages, deltas and signed feeds for the publishing job.

Every build also builds `ghcr.io/eschouten/ai-detector` for amd64 and arm64 on native runners, and publishes it only after both architectures pass the container smoke check and the detector, web and workflow checks succeed: an official release as `X.Y.Z` and `latest`, a release candidate as `X.Y.Z-rc.N`, and a test build under its tag. Every build also moves the image of each branch whose newest commit it was built from, such as `rework-stars` or `main`. The image and the desktop release do not wait for each other, but the next build waits for both.

Python is pinned in [`detector/.python-version`](../detector/.python-version); the other tool versions are in `toolchain.json`, `web/package.json` and the lockfiles. The workflows call the same `build.py` stages as a local build, through these actions:

| Action | Does |
| --- | --- |
| [setup-web](../.github/actions/setup-web/action.yml) | Node, pnpm, Bun, caches and the locked web installation |
| [setup-detector](../.github/actions/setup-detector/action.yml) | uv, Python and the detector's locked dependencies |
| [setup-distribution](../.github/actions/setup-distribution/action.yml) | Python and uv, the web setup, and on Windows .NET with the installer tool |
| [build-launcher](../.github/actions/build-launcher/action.yml) | Compiles the native launcher |
| [test-distribution](../.github/actions/test-distribution/action.yml) | Packaging and process lifecycle checks against the compiled web application, and the .NET tests on Windows |
| [package-application](../.github/actions/package-application/action.yml) | Assembles tested binaries, smoke-tests the application, creates installers and update feeds |
| [setup-container](../.github/actions/setup-container/action.yml) | Buildx and registry login |

To debug a failure, open the first failing step, not the jobs skipped after it; `gh run view RUN_ID --log-failed` prints its log. Failure diagnostics are kept for seven days. Run the matching check locally: `actionlint` for the workflow files, and the [local checks](#local-builds-and-tests) for the rest.

## Existing Linux Docker startup

`linux_startup.py` is a separate helper for an existing Docker Engine installation on a systemd desktop. The [user guide](../README.md#start-automatically-on-a-jetson-or-linux-desktop) has the command and what it sets up; the login entry waits for the dashboard before it opens the browser.

The Linux package grants `cap_net_bind_service` to `/opt/ai-detector/AI Detector` so that the dashboard can use port 80 without running as root. Without that permission the dashboard takes port 8080 or the next free one.
