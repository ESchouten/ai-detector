# AI Detector web application

The SvelteKit application provides first-run camera setup, detector controls, camera previews, and saved detections. Most users should use the [complete application download](../README.md).

## Complete application

Install and open **AI Detector** using the [platform package](../distribution/README.md#platform-packages). It opens `http://localhost:8765/`: incomplete installations go to Setup; completed installations go to Recordings, or Cameras when configured for live viewing only. Setup has three steps: connect and save cameras, choose detector presets and their cameras, then finish all checks together. **Settings** is the only place to add or edit cameras and detectors. The Cameras page is for live viewing; its Add and Edit shortcuts open the relevant Settings step. Discovery starts immediately for the first camera, and the first detector form opens directly in step two. Later visits show saved cameras and detectors, with their existing forms embedded in the same steps. Old editor links redirect to Settings. Choose a discovered camera and enter its login, or choose **Enter camera manually** and paste a complete RTSP URL, including credentials when required. HTTP stream URLs are also supported. Manual entry has no separate address or login fields. Cameras without a detector provide live viewing only. Telegram alerts and advanced settings are optional.

The web process owns one detector process. It validates changed detector settings before replacing them, applies saved changes to enabled monitoring, exposes runtime failures, and drains detection when stopped. Automatic mode uses the bundled native detector. Docker is an explicit advanced option that checks a CUDA operation against the release's pinned image; it is not selected merely because the computer has an NVIDIA GPU. A spawned process is not proof of monitoring: readiness requires fresh frames and completed processing from the configured rules.

**Set up several cameras** discovers and connects cameras sharing a login, with two connection attempts at a time. Connected pictures appear together in a grid. Name the cameras and choose **Add selected cameras** once; successful saves survive partial failures. Each camera uses the same recording check as single-camera setup. Connecting automatically records 24 decoded frames at 12 fps, allowing time for the first keyframe, then checks the saved clip; the user does not need to play a test recording or tick a confirmation box. Failed connections can be retried without losing successes. The queue and its credentials stay in memory; keep that tab open until the cameras are saved. Then choose their detectors. **Finish setup** checks recording locations automatically and offers retries for failed checks. Connect phone alerts or choose **Skip for now**, then choose **Start monitoring**. Once all cameras are processing and their recording checks pass, setup finishes and opens Recordings automatically. A failed check stays on this page for retry.

Camera pictures start automatically, with detection boxes, confidence and optional temporary track IDs drawn directly over monitored cameras. Multiple detectors appear together in their preset colors, including in setup and camera selection. Video stays independent of inference, so boxes show the latest result and can briefly lag behind moving objects. Hidden or offscreen camera previews release their connections; at most four automatic previews run per browser tab. Detector editing shows presets, cameras, AI connections and phone recipients. The **Advanced** tab contains the schema-backed JSON editor for model thresholds, tracking, prompts, delivery options, shared AI connections and the detection engine. These settings use the preset/defaults unless explicitly changed in JSON.

The executable defaults to `127.0.0.1:8765`, opens a localhost URL without depending on mDNS, and uses the user's application data directory. `HOST`, `PORT` and `OPEN_BROWSER=false` override serving behavior. `HOST=0.0.0.0` opts into LAN access and mDNS. There is no login system; use LAN mode only on a trusted network. A second launch verifies the running local instance and opens its dashboard. Closing a browser tab leaves monitoring active. **Pause monitoring** disables automatic resume; quitting the application preserves the enabled choice for its next launch. Desktop startup runs after login, not before it.

## Telegram alerts

**Connect Telegram** opens inside the detector editor, retaining unsaved changes. New recipients automatically reuse a saved bot; when several bots are saved, choose one by its existing recipient name. **Use another bot** reveals BotFather token entry. Choose **My phone**, **A group**, or **A channel**, open Telegram and follow its selection flow. Groups must already include the bot; Telegram requests posting permission for channels. Confirm the test alert in the destination chat. The app detects confirmation and fills the recipient name; save the recipient, then save the detector when ready. The same bot can send different detectors’ alerts to different chats.

**Enter chat ID manually** remains available for bots polled by another application or using a webhook. That path sends a test and asks for receipt confirmation in the app. Setup never deletes another application's webhook. Automatic pairing expires after five minutes and accepts confirmation only from the initiating Telegram user in the selected chat.

Optional token-free bot creation needs the separately hosted [Telegram manager](telegram-manager/README.md). Set `AI_DETECTOR_TELEGRAM_MANAGER_URL` only after deploying and checking that service. With no configured service, the app uses saved bots and BotFather.

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

### Validator

Google Gemini defaults to its connection name and model: open AI Studio, copy or create a key, then choose **Connect**. In the desktop app this tests a generated image and saves only after the test succeeds. A failed test keeps the form intact for retry. Separately managed detector installations can save the settings without a local test.

Under **Validator** (`/validator`), connect Google Gemini. Configure other providers in **Advanced → AI connections**. The Gemini shortcut opens Google AI Studio for sign-in and API-key creation; paste the key into the app. Free-tier availability and quota depend on Google's model and project settings. Custom connections accept an API base URL, model, optional Bearer key and additional authentication headers. The connection test sends only a generated image and checks the same structured answer contract as the detector. It does not test video support and requires the desktop detector executable.

Select the connection under **AI verification** in a detector. The Cow Catcher and Calving Catcher presets supply the question automatically and leave verification disabled until a connection is selected. The normal setup only chooses a connection; editing the question or media choice uses **Advanced → Detector configuration**. Custom detectors without a preset question ask you to choose a preset or supply a question in **Advanced → Detector configuration**. Each detector retains its own question and media choice. **Add AI connection** opens a dialog without saving or applying the detector draft. Saving the connection selects it in that draft; **Save detector** applies the completed detector once. Existing preset-based detectors receive the preset question only when they have no verification settings; custom questions and detection settings are retained. Turning verification off pauses the whole fallback list without changing its entries. Changing a shared connection updates its assigned detectors without replacing their questions. A connection in use must be unassigned before removal. Advanced JSON keeps existing standalone verifiers and fallback lists available. **Advanced → AI connections** contains model overrides, URLs and authentication headers. The normal form asks only for the API key and, for existing connections, their name.

`app.json` stores `llms` and each detector's `llmConnection` reference. The configuration store materializes the selected connection in `config.json` on save, leaving Python independent of web metadata. Settings backups include both files and their credentials. `tests/llm.test.ts` covers shared updates and preservation of detector questions; `tests/runtime.test.ts` covers connection-check failure/cancellation and removal of temporary credentials.

### Running locally

Use Node 24 and pnpm 9.15.9:

```sh
pnpm install --frozen-lockfile
pnpm dev
pnpm quality
pnpm build
```

Local development reads `config.json` and `app.json` from the working directory (`web/` when running the commands above), unless `AIDETECTOR_DATA_DIR` is set. Missing files start an empty setup. Existing files must match the current schema; validation errors identify the file and unsupported options.

Run a built Node deployment with `pnpm start` (or `node node-server.mjs`). This entry point keeps the adapter's server and graceful shutdown, while correctly identifying direct HTTP requests on localhost and LAN addresses. `HOST` and `PORT` select the listening interface and port. Run `pnpm test:production` after building to check first-run setup, origin protection and shutdown against the actual server.

To exercise managed detection from source, point `AIDETECTOR_EXECUTABLE` to the detector executable and `AIDETECTOR_DATA_DIR` to a disposable data directory before starting the web server. `AIDETECTOR_DOCKER_IMAGE` optionally selects the exact matching image. With no detector executable configured, the web server remains a frontend for a separately managed detector.

Managed detection enables `--live-preview`. For a separately launched detector, pass that flag and share its data directory with the web server. The Compose examples already do this. Preview transport uses temporary files in `live/`, with a short viewer lease: publishing runs only while a viewer is connected. Visible cameras share one `/cameras/live?camera=<id>` SSE connection (repeat `camera` for multiple cameras). It delivers box metadata without JPEGs, leaving each independent video stream running at its own pace. Empty results, stopped detectors and expired frames clear the affected boxes. Preview results are not event recordings. See the [live preview protocol](../detector/LIVE_PREVIEW.md) for ownership, freshness and cleanup.

Settings are read without creating or rewriting files. The checked-in Python JSON schema validates every save, including separately managed installations. Web requests share a serialized configuration store. Changed detector settings and metadata are staged before replacement; a failed second replacement restores the previous metadata. This protects ordinary I/O failures within one writer, not crashes or power loss across two files. Once saved, runtime application failures appear in monitoring status without falsely rejecting the save. Metadata-only changes avoid detector restarts. See the [settings save boundary](ARCHITECTURE.md#settings-save-boundary) for failure and recovery details.

The Advanced editor uses the bundled schema offline for suggestions, inline errors and immediate validation. Saving also validates on the server; a stale draft is rejected instead of overwriting changes made elsewhere. Detector JSON changes preserve camera names and clear preset identity when detection settings are customized. Editing a shared AI connection updates its assigned detectors while retaining their questions. Runtime mode changes require paused monitoring and take effect at the next start.

Malformed JSON remains an error. Detector presets are discovered directly from `../config/detector/*.json` and embedded in the build, so setup does not fetch them from GitHub. Filenames supply the displayed names. An installed application can use a local `presets/` folder; see the [preset guide](../config/README.md). Camera connections and the first model download still need network access.

`pnpm test` runs platform selection, process lifecycle, cancellation, restart, configuration failure, GPU check failure, credential redaction and data persistence tests. `runtime-recovery.test.ts` covers bounded MPS recovery with real child processes, preserved logs, fresh readiness and pause/quit cancellation. Process fixture tests run on POSIX; Windows shutdown is covered by the Python stdin-control tests and the complete bundle smoke in release CI. `pnpm check` fails on errors and warnings. See the [architecture and reading map](ARCHITECTURE.md) for the source boundaries, test map, complexity limits and generated dependency graph.

## Building executables

On older Windows systems, `nvidia-runtime.ts` prepares the optional CUDA runtime through uv. `nvidia-runtime.test.ts` checks discovery, cache reuse, download failures, retry and cancellation; `nvidia-runtime-installed.test.ts` installs the real packages in Windows application CI. See the [distribution guide](../distribution/README.md) for supported GPUs and the dependency cache layout.

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
