# AI Detector web application

The SvelteKit application provides first-run camera setup, detector controls, camera previews, and saved detections. Most users should use the [complete application download](../README.md).

## Complete application

Install and open **AI Detector** using the [platform package](../distribution/README.md#platform-packages). It opens `http://localhost:8765/`: incomplete installations go to Setup; completed installations go to Recordings, or Cameras when configured for live viewing only. Setup has three steps: connect and save cameras, choose detector presets and their cameras, then finish all checks together. The same camera editor handles first and additional cameras. Choose a discovered camera and enter its login, or choose **Enter camera manually** and paste a complete RTSP URL, including credentials when required. HTTP stream URLs are also supported. Manual entry has no separate address or login fields. Cameras without a detector provide live viewing only. Telegram alerts and advanced settings are optional.

The web process owns one detector process. It validates changed detector settings before replacing them, applies saved changes to enabled monitoring, exposes runtime failures, and drains detection when stopped. Automatic mode uses the bundled native detector. Docker is an explicit advanced option that checks a CUDA operation against the release's pinned image; it is not selected merely because the computer has an NVIDIA GPU. A spawned process is not proof of monitoring: readiness requires fresh frames and completed processing from the configured rules.

**Set up several cameras** discovers and connects cameras sharing a login, with two connection attempts at a time. Each queued camera uses the same inline preview and save flow as a single camera. Connecting automatically records 24 decoded frames at 12 fps, allowing time for the first keyframe, then checks the saved clip; the user does not need to play a test recording or tick a confirmation box. Failed connections can be retried without losing successes. The queue and its credentials stay in memory; keep that tab open until the cameras are saved. Then choose their detectors. **Finish setup** checks recording locations automatically and offers retries for failed checks. Connect phone alerts or choose **Skip for now**, then finish all cameras together.

Camera pictures start automatically, with detection boxes, confidence and optional temporary track IDs drawn directly over monitored cameras. Multiple detectors appear together in their preset colors, including in setup and camera selection. Video stays independent of inference, so boxes show the latest result and can briefly lag behind moving objects. Hidden or offscreen camera previews release their connections; at most four automatic previews run per browser tab. Detector editing starts with the preset and camera choices; **Advanced settings** exposes additional controls. Optional overlap (IoU) and tracker choices live under **Tracking and overlapping detections**; empty choices preserve Ultralytics defaults.

The executable defaults to `127.0.0.1:8765`, opens a localhost URL without depending on mDNS, and uses the user's application data directory. `HOST`, `PORT` and `OPEN_BROWSER=false` override serving behavior. `HOST=0.0.0.0` opts into LAN access and mDNS. There is no login system; use LAN mode only on a trusted network. A second launch verifies the running local instance and opens its dashboard. Closing a browser tab leaves monitoring active. **Pause monitoring** disables automatic resume; quitting the application preserves the enabled choice for its next launch. Desktop startup runs after login, not before it.

## Bring an existing installation into setup

Before adding a camera, choose **Use existing setup** on Setup. Close the old application, choose its folder containing `config.json`, review the camera/detector/recording counts, and import. Existing camera names, detector rules and notification assignments populate the normal setup steps. Review them and start monitoring in **Finish setup**; importing itself does not start monitoring or send alerts.

The default copies `config.json`, optional `app.json`, `detections/`, local `presets/`, and referenced local models/videos into the new data folder. It leaves the old files intact and updates relative model/video references. Standard missing model names remain managed by Ultralytics and are shown in the import notes. The unused legacy `yolo.strategy` setting is removed; other unsupported settings are reported instead of silently discarded. Custom absolute/nested disk destinations and linked archive folders need arranging into the standard `detections/<category>/...` layout before import.

**Recording storage → Keep recordings in their current folder** avoids copying a large archive. The new data folder links to that archive (a directory junction on Windows). Keep the old folder and its drive available: new recordings also go there, and approving/deleting recordings affects that shared archive. Back up both locations.

Imports refuse to replace an existing setup or data folder. Completed copies are staged under `.installation-import/`; reopen Setup to resume after interruption. The private manifest is deleted after success. Importing and the native folder chooser are available only from the local computer. **Enter folder path** is available if a native dialog cannot open.

## Export recordings and back up settings

Choose **Export recordings** on Recordings to download a ZIP of the selected category and stage across all pages. Optional **From date** and **To date** fields include both complete days, using the recording dates shown on screen. Leave either field empty for an open-ended range, or both for all dates. The dialog shows the number of matching events before downloading.

The ZIP preserves the `detections/<category>/<stage>/<timestamp>/` structure, original images (`clean.jpg` when available), annotated images, saved frames, videos and `metadata.json`. It does not include settings. These are model predictions, not reviewed training labels; review and annotate original images or video frames before training. Exports download locally and are not uploaded anywhere by the app.

On Settings, **Back up settings** downloads `config.json` and `app.json` together. This includes saved camera passwords and alert tokens, so keep the backup private. Recordings, model/video files, custom preset files and computer startup preferences are not included. To restore into a new installation, extract the ZIP and use **Use existing setup** to select that folder. Keep referenced local model/video files available at their configured paths, or update the paths before importing on another computer. Import never overwrites an existing setup.

## Development

Use Node 24 and pnpm 9.15.9:

```sh
pnpm install --frozen-lockfile
pnpm dev
pnpm quality
pnpm build
```

Run a built Node deployment with `pnpm start` (or `node node-server.mjs`). This entry point keeps the adapter's server and graceful shutdown, while correctly identifying direct HTTP requests on localhost and LAN addresses. `HOST` and `PORT` select the listening interface and port. Run `pnpm test:production` after building to check first-run setup, origin protection and shutdown against the actual server.

To exercise managed detection from source, point `AIDETECTOR_EXECUTABLE` to the detector executable and `AIDETECTOR_DATA_DIR` to a disposable data directory before starting the web server. `AIDETECTOR_DOCKER_IMAGE` optionally selects the exact matching image. With no detector executable configured, the web server remains a frontend for a separately managed detector.

Managed detection enables `--live-preview`. For a separately launched detector, pass that flag and share its data directory with the web server. The Compose examples already do this. Preview transport uses temporary files in `live/`, with a short viewer lease: publishing runs only while a viewer is connected. Visible cameras share one `/cameras/live?camera=<id>` SSE connection (repeat `camera` for multiple cameras). It delivers box metadata without JPEGs, leaving each independent video stream running at its own pace. Empty results, stopped detectors and expired frames clear the affected boxes. Preview results are not event recordings. See the [live preview protocol](../detector/LIVE_PREVIEW.md) for ownership, freshness and cleanup.

Settings are read without creating or rewriting files. The checked-in Python JSON schema validates every save, including separately managed installations. Web requests share a serialized configuration store. Changed detector settings and metadata are staged before replacement; a failed second replacement restores the previous metadata. This protects ordinary I/O failures within one writer, not crashes or power loss across two files. Once saved, runtime application failures appear in monitoring status without falsely rejecting the save. Metadata-only changes avoid detector restarts. See the [settings save boundary](ARCHITECTURE.md#settings-save-boundary) for failure and recovery details.

Malformed JSON remains an error. Detector presets are discovered directly from `../config/detector/*.json` and embedded in the build, so setup does not fetch them from GitHub. Filenames supply the displayed names. An installed application can use a local `presets/` folder; see the [preset guide](../config/README.md). Camera connections and the first model download still need network access.

`pnpm test` runs platform selection, process lifecycle, cancellation, restart, configuration failure, GPU check failure, credential redaction and data persistence tests. Process fixture tests run on POSIX; Windows shutdown is covered by the Python stdin-control tests and the complete bundle smoke in release CI. `pnpm check` fails on errors and warnings. See the [architecture and reading map](ARCHITECTURE.md) for the source boundaries, test map, complexity limits and generated dependency graph.

## Building executables

Set `AI_DETECTOR_WEB_TARGET` to `windows-x64-baseline`, `darwin-arm64` or `linux-x64-baseline` when running `pnpm build`. The complete [application workflow](../.github/workflows/application.yml) builds and packages the web executable, the native detector and FFmpeg together, then tests the result. The [container workflow](../.github/workflows/containers.yml) publishes the separate web image for Docker/Compose deployments; standalone web executables can still be built locally with `distribution/build.py web --standalone-web`.

The patched executable adapter binds the instance port before initialization, starts SvelteKit's server hook without waiting for a browser request, and awaits shutdown listeners before releasing the port. Its authenticated local `--quit` command waits for the owning process to exit. The manager uses a pipe to request graceful detector shutdown on every OS; it does not depend on Windows POSIX signal behavior. A 30-second detector stop deadline triggers forced termination and a visible warning if draining failed. Runtime output displayed in the browser is bounded and URL credentials are redacted. Native launchers, installers, login behavior and signing gates are documented in the [distribution guide](../distribution/README.md).

## Docker

Build from the repository root, since setup presets are shared with the detector:

```sh
docker build -f web/Dockerfile -t ai-detector-web .
```

The image serves port 3000 and reads configuration/recordings in `/data`. The existing Compose files expose port 80. This separately managed deployment intentionally has no Docker socket mount and cannot launch another detector from the web UI.

Direct HTTP works with the hostname or IP address used in the browser; no fixed `ORIGIN` is needed. Behind an HTTPS reverse proxy, set `ORIGIN` to the public origin, for example `https://detector.example.com`. The Node entry point always supplies its own HTTP transport header; it does not trust a browser's forwarded protocol header. SvelteKit's cross-origin request protection remains enabled.

Containers restart at boot when Docker starts, unless deliberately stopped. A web server inside Docker cannot open the host's desktop browser; the [Linux startup helper](../README.md#start-automatically-on-a-jetson-or-linux-desktop) installs a separate desktop-login launcher that waits for the web app and opens its home route.
