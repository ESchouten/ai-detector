# AI Detector web application

The SvelteKit application is the interface of AI Detector: guided setup, cameras, detectors, recordings and settings. In the [complete application](../README.md) it also starts and supervises the detector. Installing and first setup are described there; this guide covers what the application does afterwards, and how to work on it.

## Using the application

After setup there are three main pages, **Recordings**, **Cameras** and **Detectors**, and everything else is under **Settings**. The monitoring state is always visible and opens a status page with each camera's state, **Pause monitoring**, and the optional **Heartbeat**: an address the detector calls while it runs, so a service such as Healthchecks.io can warn you when the computer stops.

The web process owns one detector process. A started process is not proof of monitoring: a camera counts as monitored only when fresh frames are being processed by every detector assigned to it. Closing the browser leaves monitoring running. **Pause monitoring** also keeps it paused at the next launch; quitting the application keeps the choice it had.

Camera pictures show the latest detection boxes over live video. The video runs independently of inference, so boxes can lag behind moving objects. At most four previews run per browser tab, and hidden ones are released.

### Presets and new models

A detector made from a preset follows it. When an update of AI Detector brings a newer model for that preset, the detector takes it at the next start, before monitoring begins; the first start downloads the model and may take longer. Its cameras, alerts and Validator stay as you set them. A detector whose detection settings you changed keeps them and is not updated; choose the preset again to follow it.

### Other devices on the network

The application listens on `0.0.0.0:80`, so other devices can open `http://ai-detector.local/` or `http://<computer-IP>/`. The computer it runs on is trusted; every other browser needs a one-use pairing code from **Settings → Devices** (scan the QR code, then tap Connect). Codes expire after five minutes or ten wrong attempts; a connected browser is remembered for a year and can be removed there. A headless first start prints a code on the console.

`HOST`, `PORT` and `OPEN_BROWSER=false` change how it serves; `HOST=127.0.0.1` restricts it to this computer and turns network discovery off. Plain HTTP is not encrypted: use a trusted network or an HTTPS reverse proxy.

### Language

The interface is available in English, Nederlands, Deutsch and Français. An installation takes the language of the browser that sets it up and keeps it for every device and for its Telegram replies. Change it in the menu at the top of setup or under **Settings → Language**. Logs, the hints in the Advanced JSON editor, messages reported by the detector itself and the desktop launcher's menus stay in English.

### Telegram alerts

**Connect Telegram** opens inside the detector editor and keeps unsaved changes. Paste a BotFather token once, choose **My phone**, **A group** or **A channel**, follow Telegram's own selection, and confirm the test alert in that chat. Later recipients reuse the saved bot. Recipients belong to detectors, so one bot can send different detectors' alerts to different chats.

**Enter chat ID manually** is for a bot that another application polls or that has a webhook; it sends a test and asks you to confirm receipt. Setup never removes another application's webhook.

Alerts carry 👍 and 👎 buttons that save a review, and the thumb you press stays coloured on that alert. For that the application must be running (monitoring may be paused) and the bot must be dedicated to this installation. The colour shows what was pressed on that message: a review changed in the web interface, or on a copy of the alert in another chat, does not recolour it.

### Validator

A **Validator** connection lets a vision language model confirm or reject each event. Under **Settings → Validator**, connect Google Gemini with an API key from AI Studio; in the complete application the key is tested with a generated image before it is saved. Other providers are configured under **Advanced → AI connections** with a base URL, model names, and a key or headers.

A connection is saved once and used by any number of detectors; each detector keeps its own question. Saving a connection also switches on saved detectors whose preset question was still waiting for one, and a new detector suggests the connection when it is the only one. Turning the Validator off for a detector keeps its question and models but clears every key, including those of fallback entries added in Advanced. Choosing the connection again restores only the first entry; fallback keys must be entered again. A connection in use cannot be removed.

### Bring an existing installation into setup

Before adding a camera, choose **Use existing setup**, close the old application, select its folder containing `config.json`, review the counts and import. Cameras, detectors and alert assignments fill the normal setup steps; importing starts nothing and sends nothing.

The import copies `config.json`, `app.json` when present, `detections/`, local `presets/` and referenced local model and video files into the new data folder, and leaves the old files as they were. **Keep recordings in their current folder** links to the old archive instead of copying it. Keep that folder and its drive available: new recordings go there too, and reviewing or deleting a recording changes that original archive. Back up both folders.

An import never replaces an existing setup. Copies are staged, so reopening Setup resumes an interrupted import. Importing is available only on the computer the application runs on.

### Export recordings and back up settings

Selecting a recording opens a viewer; the arrow keys step through recordings. The thumbs record your own verdict, and pressing your choice again removes it and restores the Validator's result. Recordings filter by category and by result.

**Export** downloads a ZIP of the selected category and result, optionally between two dates. It keeps the `detections/<category>/<stage>/<timestamp>/` layout with images, clips and `metadata.json`, grouped by the reviewed result. In `metadata.json`, `review` is the person's decision and `validated` the Validator's. A confirmed event is not a checked bounding box: annotate the original images before training a model with them.

**Settings → Back up** downloads `config.json` and `app.json`. The backup contains camera passwords and alert tokens; keep it private. It does not contain recordings, models, custom presets or paired devices. To restore, extract it and use **Use existing setup** in a new installation.

### Recovery and storage

- **Logs → Download diagnostics** bundles the detector and application logs, system details and redacted settings. It works even when settings cannot be read. Review paths and camera addresses before sharing it.
- When a settings file cannot be read, every page names the damaged file and offers **Recover settings**: the last valid settings are restored and the current files are kept beside them with an `.invalid` suffix.
- **Settings → Storage** shows free space on the recordings drive and removes recordings older than a date you choose, after showing the count. Nothing deletes recordings automatically. Clearing the model cache requires paused monitoring.
- Alert and Validator failures stay visible in the monitoring status until a later attempt succeeds.

## Development

Use Node 24 and pnpm 9.15.9.

```sh
pnpm install --frozen-lockfile
pnpm dev
pnpm quality
pnpm build
pnpm test:production
```

`pnpm quality` runs the schema, formatting, lint, translation, type, dependency and unit checks; `pnpm test:production` exercises the built server over HTTP. The [architecture guide](ARCHITECTURE.md) maps the code and its rules.

| Variable                       | Effect                                                                                                                   |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `AIDETECTOR_DATA_DIR`          | Folder holding `config.json`, `app.json` and recordings. Development defaults to the working directory.                  |
| `AIDETECTOR_EXECUTABLE`        | Detector to start and supervise. Without it, a development server is only an interface to a separately managed detector. |
| `AIDETECTOR_DOCKER_IMAGE`      | Image used by the optional Docker engine.                                                                                |
| `AIDETECTOR_PRESETS`           | Folder of preset files, instead of `presets/` in the data folder or the bundled ones.                                    |
| `FFMPEG_PATH`                  | FFmpeg executable for camera checks and previews.                                                                        |
| `HOST`, `PORT`, `OPEN_BROWSER` | Listening interface and port, and whether a browser opens.                                                               |
| `ORIGIN`                       | The public origin behind an HTTPS reverse proxy, for example `https://detector.example.com`.                             |

Missing settings files start an empty setup. A separately started detector needs `--live-preview` and the same data folder for detection boxes to appear.

### Executables and Docker

Set `AI_DETECTOR_WEB_TARGET` to `windows-x64-baseline`, `darwin-arm64` or `linux-x64-baseline` for `pnpm build` to compile a single executable. The complete application is assembled and tested by [`distribution/build.py`](../distribution/README.md).

Build the container from the repository root, because the presets are shared with the detector:

```sh
docker build -f web/Dockerfile -t ai-detector-web .
```

The image serves port 3000 and reads `/data`. It has no Docker socket and cannot start a detector; run `pnpm start` (`node node-server.mjs`) for the same server without a container. Direct HTTP works with whatever hostname or address the browser used. A web server in a container cannot open the host's browser; the [Linux startup helper](../README.md#start-automatically-on-a-jetson-or-linux-desktop) does that at login.
