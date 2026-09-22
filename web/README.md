# AI Detector web application

The SvelteKit application provides first-run camera setup, detector controls, camera previews, and saved detections. Most users should use the [complete application download](../README.md).

## Complete application

Open the bundled **AI Detector** executable. It opens `http://localhost:8765/`: new installations go to Setup and configured installations go to Detections. In Setup, the user names a camera, enters its RTSP/HTTP stream address and chooses calving, mounting or general object detection. Disk recording is enabled automatically. Telegram and advanced settings are optional.

The web process owns one detector process. It validates saved configurations with the bundled detector before replacing the file, applies changes to an enabled detector, exposes failures in setup, and drains detection when stopped. Automatic mode selects Docker for an NVIDIA GPU reported by its driver on Windows/Linux, and the native detector otherwise. Docker startup checks a CUDA operation against the release's pinned image. Missing prerequisites have browser links; the user can explicitly select the native runtime.

The executable defaults to `127.0.0.1:8765`, opens a localhost URL without depending on mDNS, and uses the user's application data directory. `HOST`, `PORT` and `OPEN_BROWSER=false` override serving behavior. `HOST=0.0.0.0` opts into LAN access and mDNS. There is no login system; use LAN mode only on a trusted network. Closing a browser tab leaves the app running. Stop disables automatic resume; closing and reopening the application while enabled resumes detection.

## Development

Use Node 24 and pnpm 9.15.9:

```sh
pnpm install --frozen-lockfile
pnpm dev
pnpm check
pnpm test
pnpm build
```

To exercise managed detection from source, point `AIDETECTOR_EXECUTABLE` to the detector executable and `AIDETECTOR_DATA_DIR` to a disposable data directory before starting the web server. `AIDETECTOR_DOCKER_IMAGE` optionally selects the exact matching image. With no detector executable configured, the web server remains a frontend for a separately managed detector.

Settings are read without creating or rewriting files. Saves use temporary files and atomic rename; malformed JSON remains an error. The built-in first-run presets are bundled from `../config/detector`, so setup does not fetch them from GitHub. Camera connections and the first model download still need network access.

`pnpm test` runs platform selection, process lifecycle, cancellation, restart, configuration failure, GPU check failure, credential redaction and data persistence tests. Process fixture tests run on POSIX; Windows shutdown is covered by the Python stdin-control tests and the complete bundle smoke in release CI. `pnpm check` currently reports eight existing Svelte initial-value warnings in unrelated components/editor state.

## Building executables

Set `AI_DETECTOR_WEB_TARGET` to `windows-x64-baseline`, `darwin-arm64` or `linux-x64-baseline` when running `pnpm build`. The complete [application workflow](../.github/workflows/application.yml) builds and packages the web executable, the native detector and FFmpeg together, then tests the result. The standalone web workflow remains available.

The patched executable adapter opens the browser and emits SvelteKit's shutdown event. The manager uses a pipe to request graceful detector shutdown on every OS; it does not depend on Windows POSIX signal behavior. A 30-second stop deadline prevents an unresponsive detector from holding the application indefinitely, with an explicit warning if forced shutdown was necessary. Runtime output displayed in the browser is bounded and URL credentials are redacted.

## Docker

Build from the repository root, since setup presets are shared with the detector:

```sh
docker build -f web/Dockerfile -t ai-detector-web .
```

The image serves port 3000 and reads configuration/recordings in `/data`. The existing Compose files expose port 80. This separately managed deployment intentionally has no Docker socket mount and cannot launch another detector from the web UI.

Containers restart at boot when Docker starts, unless deliberately stopped. A web server inside Docker cannot open the host's desktop browser; the [Linux startup helper](../README.md#start-automatically-on-a-jetson-or-linux-desktop) installs a separate desktop-login launcher that waits for the web app and opens its home route.
