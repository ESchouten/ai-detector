# Application installers and updates

One application release contains the browser application, the native detector, FFmpeg and, for the optional Docker engine, the digest of its matching image. People open **AI Detector** and set it up in their browser.

## Installation and data

| Target | Installer | Desktop integration |
| --- | --- | --- |
| macOS 14+ Apple Silicon | `AI-Detector-VERSION-macos-arm64.dmg` | Drag to Applications. Menu bar: Open dashboard, Open at login, Check for Updates, Quit. |
| Windows 10 22H2+ / Windows 11 x64 | `AI-Detector-VERSION-windows-x64-setup.zip` | Extract and run the setup EXE; it installs for the current user. Tray: Open dashboard, Open at login, Check for Updates, Quit. |
| Ubuntu 22.04/24.04 amd64 | `AI-Detector-VERSION-linux-amd64.deb` | Installs under `/opt/ai-detector` with an Applications and a login entry. Upgrade with the package manager. |

Login startup runs after login, under that user's account. It is not a service that monitors before anyone signs in.

Releases are not notarized by Apple or signed with a Windows publisher certificate, so macOS may ask for approval in Privacy & Security and Windows may show SmartScreen or block the installer under Smart App Control. The first download must therefore come from the official repository. Updates after that are verified against a key built into the installed copy; see [how updates are trusted](#how-updates-are-trusted).

Settings, models and recordings live outside the installed program, and updates and uninstallers leave them alone:

- macOS: `~/Library/Application Support/AI Detector`
- Windows: `%LOCALAPPDATA%\AI Detector` (the program itself is in `%LOCALAPPDATA%\AIDetector\current`)
- Linux: `$XDG_DATA_HOME/ai-detector`, by default `~/.local/share/ai-detector`

`AIDETECTOR_DATA_DIR` selects another folder.

The released detector and web executables kept `config.json`, `app.json` and `detections/` beside the program. To move such an installation, keep that whole folder, install the application, choose **Use existing setup** in its first setup step and select the old folder. See the [import guide](../web/README.md#bring-an-existing-installation-into-setup). Do not delete the old folder before importing.

## Updates

[Sparkle](https://sparkle-project.org/documentation/) updates the Mac application and [Velopack](https://docs.velopack.io/integrating/overview) installs and updates the Windows one. Their versions are pinned in `macos/build-launcher.sh`, `.config/dotnet-tools.json`, `windows/Directory.Packages.props` and the lockfiles.

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
- `windows/launcher` is a small .NET Framework 4.8 program, using the runtime that supported Windows versions already include.
- The Mac bundle embeds PyInstaller's `aidetector.app` under `Contents/Helpers/Detector.app` and links to it, so no unsigned Python files sit in `Contents/MacOS`.

The SvelteKit executable adapter carries a small patch: upstream has no application-bootstrap hook and no way to pass compiler arguments. The patch delegates startup to `web/desktop` and holds no application logic. Remove it when upstream offers the hooks.

## Windows NVIDIA runtime

The Windows installer carries no GPU binaries. When automatic inference finds an NVIDIA device with compute capability 7.5 or newer, the web application's process manager downloads a CUDA environment into the data folder and runs the same detector source in it. That device needs driver branch 572 or newer: with an older driver, starting stops with a request to update the driver, and does not fall back to Windows ML. An explicit ONNX provider, a configuration without a YOLO model, and the Docker engine bypass the download; a computer without such a device uses the bundled Windows ML build.

- The build stages `detector/nvidia-runtime/`: the detector source, an entry script, uv, a `runtime.json` naming the Python version, and two locks exported from the detector's lockfile, `pylock.toml` for CUDA and `pylock.tensorrt.toml` for the optional TensorRT group. Every package is pinned by URL and SHA-256.
- uv installs Python and the packages under `runtimes/nvidia/<hash>/`, with its cache in `cache/uv/`. The hash covers the Python version and the lock, not the application version, so an application update reuses the environment and runs its own newer detector source in it.
- A GPU check must pass before `ready.json` marks the environment complete, and runs again at every launch. An interrupted download is retried; a failure stays visible and never silently falls back to the CPU. Pause and quit stop a running preparation.
- On compute capability 8.0 and newer, TensorRT is installed after the CUDA check. If that fails, CUDA stays in use and the attempt is deferred for 24 hours. Engines are built on the user's GPU by the detector (see [inference backends](../detector/ARCHITECTURE.md#inference-backends)) and are never shipped.

`test_nvidia_runtime.py` checks the staged payload and resolves both locks without downloading GPU binaries. CI installs the real packages on a Windows runner; it has no GPU, so GPU speed and model accuracy still need an NVIDIA machine with representative footage.

## Code map

| Change | Owner |
| --- | --- |
| Port ownership, parent pipe, browser launch, graceful shutdown | `web/desktop/runtime.ts`, `host.ts`, `instance.ts`, `browser.ts` |
| Data-folder rules | `web/desktop/paths.ts`, also used by the server |
| Network discovery (`ai-detector.local`) | `web/desktop/network.ts` |
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

CI runs the stages separately: `build.py detector --platform PLATFORM`, `web --platform PLATFORM` and `launcher --platform PLATFORM --output DIRECTORY`. `build.py stamp-detector FOLDER --version REF` writes a new version into an already frozen detector, which CI uses to skip freezing when the detector's sources did not change. `build.py archive FOLDER` makes a portable ZIP for troubleshooting; releases do not publish one.

Install one inference extra at a time: `default`, `nvidia` or `windowsml`. On Linux, `default` takes Torch from PyTorch's CPU index, which keeps several gigabytes of unused CUDA libraries out of the installer. Linux packages are compressed with Zstandard level 9 and Mac deltas with LZFSE: both give a slightly larger download for a much shorter build.

Fast checks:

```sh
uv run --project detector --extra default --with-requirements distribution/requirements.txt python -m unittest discover -s distribution -p 'test_*.py'
pnpm --dir web quality
bun test ./web/desktop/host.test.ts
```

Windows launcher checks:

```sh
dotnet tool restore
dotnet restore distribution/windows/launcher-tests/Launcher.Tests.csproj --locked-mode
dotnet build distribution/windows/launcher/Launcher.csproj --no-restore --configuration Release --warnaserror
dotnet test distribution/windows/launcher-tests/Launcher.Tests.csproj --no-restore --configuration Release
dotnet restore distribution/windows/update-tests/Update.Tests.csproj --locked-mode
dotnet test distribution/windows/update-tests/Update.Tests.csproj --no-restore --configuration Release
```

After changing NuGet dependencies, regenerate the lockfiles with `dotnet restore … --force-evaluate`.

Some tests need a built artifact and are skipped without it: set `SPARKLE_SDK` to the extracted SDK for the Mac delta round trip, `WINDOWS_LAUNCHER` to the compiled launcher folder for the Velopack package test, and `DESKTOP_WEB_EXECUTABLE` to the built web executable for the shutdown and occupied-port tests. They use temporary data and public test keys and never install anything.

What no test here establishes: installing a downloaded application on a clean machine, the update and relaunch dialogs, login startup, and inference on real hardware.

Regenerate the artwork with `swift distribution/macos/render-artwork.swift` and `python distribution/windows/render-artwork.py`.

## GitHub Actions previews

Push an `app/test-*` tag at the commit to test, with a new name for each build:

```sh
git tag app/test-2026-09-25-1
git push origin app/test-2026-09-25-1
```

GitHub runs **Application download** from that commit. When every platform passes, the installers are on the resulting **prerelease**: a Windows ZIP holding the setup EXE, a Mac DMG and a Linux DEB. The `.nupkg` and `.delta` files beside them are for automatic updates. The run can also be started by hand for a branch, which publishes to the same preview channel.

Previews show version `0.0.N`, where `N` is the workflow's run number. Every release also has an internal build version `N.0.0` that orders builds across both channels, so a preview can follow an official release with a higher display version. Keep the workflow's file name and its run-number sequence.

A published build is never rebuilt. Retry a failed run; after a successful one, push a new tag.

Prefer a pushed tag when the branch changes workflow files. Creating the release tag from a manual run on such a branch needs a repository secret `RELEASE_TOKEN` with Contents and Workflows write permission, because GitHub's built-in token cannot be given the second.

The [workflow guide](../.github/README.md) describes the jobs, their artifacts and how to debug a failure.

## Publishing a release

Push an increasing `app/vX.Y.Z` tag. Versions with a prerelease or build suffix are rejected on this channel.

The workflow reads the signed history of the channel, builds the Mac deltas and the Windows packages, and combines both channels into one newly signed feed. When every platform has succeeded it publishes the versioned release and promotes the feeds to the fixed **app-update-channels** release, which the launchers read; **app-updates** and **app-preview-updates** hold each channel's own history, from which the Mac deltas and the combined feed are built. Release runs are serialized because both channels write the same feeds. Never edit or delete a published version: installed applications and retained deltas refer to it.

Two entries under **Settings → Secrets and variables → Actions** are required:

- variable `SPARKLE_PUBLIC_KEY`: the base64 public Ed25519 key built into both launchers;
- secret `SPARKLE_PRIVATE_KEY`: the 32-byte seed, base64-encoded, as exported by Sparkle's `generate_keys -x`.

The production key is backed up in the maintainer's macOS login Keychain under account `io.github.eschouten.ai-detector`; `generate_keys --account io.github.eschouten.ai-detector -p` prints its public half. GitHub Secrets cannot be read back, so that Keychain entry is the backup. Never replace one half without the other: installed applications trust the public key they were built with. The public test keys in `fixtures/` must never sign a release.

Before the first real pair of versions, try a signed update on a Mac and on Windows: leave monitoring running during the download, defer the restart, apply it, and confirm that monitoring resumes with the same settings, recordings and login preference. Also try an update that skips a version and one whose download was interrupted.

## Existing Linux Docker startup

`linux_startup.py` is a separate helper for an existing Docker Engine installation on a systemd desktop; see the [command](../README.md#start-automatically-on-a-jetson-or-linux-desktop). It enables Docker at boot, starts the Compose project and installs a login entry that waits for the dashboard and opens the browser. Uninstalling removes only those startup files.

The Linux package grants `cap_net_bind_service` to `/opt/ai-detector/AI Detector` so that the dashboard can use port 80 without running as root. Portable and source deployments must choose another port or arrange that themselves.
