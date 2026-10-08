# AI Detector web application

The interface of AI Detector: setup, cameras, detectors, recordings and settings. In the [complete application](../README.md) it also starts and supervises the detector. This guide covers using it after setup, and working on it.

## Using the application

There are three main pages, **Recordings**, **Cameras** and **Detectors**; everything else is under **Settings**. The monitoring state is always visible and opens a status page.

### Monitoring

- A camera counts as monitored only when fresh pictures are being analysed by every detector assigned to it. A started program is not proof.
- Closing the browser leaves monitoring running. **Pause monitoring** also keeps it paused at the next launch.
- **Heartbeat** on the status page is an address the detector calls while it runs, so a service such as Healthchecks.io can warn you when the computer stops.
- Alert and Validator failures stay visible in the status until a later attempt succeeds.

### Cameras

Camera pictures show the latest detection boxes over live video; the boxes can lag behind moving objects. At most four live pictures run per browser tab, and hidden ones are released. A camera shows its first picture at its next keyframe, which can take a few seconds; after that the picture stays ready for twenty seconds.

**History** on the same page shows, per camera, when it was really watched over the last hour, day or week, with every recording as a mark on the same line; a mark opens the recording. A gap is time in which nothing would have been noticed, and it says why: the camera was offline, monitoring was paused, or AI Detector was not running. History is kept for thirty days from the day this version was installed, and a gap is known to within about ten seconds. With a separately managed detector only the recordings are shown.

### Detectors and presets

A detector made from a preset follows it. When a newer model is published for that preset, the detector takes it within a day or at the next start: monitoring restarts by itself and is interrupted while the model is downloaded and prepared. Cameras, alerts and Validator stay as you set them. For this the application asks GitHub once a day; without internet nothing changes.

**Update automatically** in a detector's settings switches this off for that detector: it then keeps the model it has until you switch it on again or choose the preset anew.

A detector whose detection settings you changed keeps them and is not updated. Choose the preset again to follow it.

### Recordings

- Selecting a recording opens a viewer; the arrow keys step through recordings.
- A recording shows the names of the cows that were recognised in it, when a [Cow Identity](#herd-experimental) detector watches the same camera. On a mounting recording that is the cow that mounts, and sometimes the one underneath or one standing close behind. No name means that no cow was recognised, not that it was an unknown one.
- The thumbs record your own verdict. Pressing your choice again removes it and restores the Validator's result.
- The chips filter by category and by result; pressing a chosen chip clears it.
- The bin in the viewer deletes that recording from the computer, after asking once.
- **Export** downloads a ZIP of the current filter, optionally between two dates, laid out as `detections/<category>/<stage>/<timestamp>/` with images, clips and `metadata.json`. In that file `review` is the person's decision and `validated` the Validator's. **Only the original photos** leaves out videos and pictures with boxes, for a small ZIP to share with the people who train the model. A confirmed event is not a checked bounding box: annotate the original images before training a model with them.

### Herd (experimental)

A detector made from the **Cow Identity** preset takes photographs of the cows it follows. On **Herd**, confirm a photograph with a name or tag number; the other photographs the camera took while it kept following that animal are confirmed with it unless you untick them. The detector then learns the herd, which takes ten minutes or more after every change, and shows a name on the live picture when it is sure. It needs hundreds of photographs of a cow, from several days, by day and by night, and most of the herd named. Even then it names only part of the animals: in the trial about seven in ten by day and five in ten at night. A wrong example can be moved to another cow or removed, and nothing is ever added to a cow's examples without your confirmation. See the [research record and its limits](../research/cow_identity/HERD_LEARNING.md).

### Telegram alerts

**Connect Telegram** opens inside the detector editor. Paste a BotFather token once, choose **My phone**, **A group** or **A channel**, and confirm the test alert in that chat. Recipients belong to detectors, so one bot can send different detectors' alerts to different chats.

- Alerts carry 👍 and 👎 buttons that save a review; the thumb you press stays coloured on that alert. The application must be running for this, and the bot must be used by this installation only.
- **Quiet hours** on a recipient make alerts between two times of day arrive without sound, for example at night. They still arrive.
- **Enter chat ID manually** is for a bot that another application also reads. Setup never removes another application's webhook.

### Validator

A **Validator** connection lets a vision language model confirm or reject each event. Under **Settings → Validator**, connect Google Gemini with a key from AI Studio; other providers are set under **Advanced → AI connections**.

A connection is saved once and used by any number of detectors, each with its own question. Turning the Validator off for a detector keeps its question and clears its keys. A connection in use cannot be removed.

### Other devices

The application listens on `0.0.0.0:80`, so other devices open `http://aidetector.local/` or `http://<computer-IP>/`. The computer it runs on is trusted; every other browser needs a one-use code from **Settings → Devices** (scan the QR code, then tap Connect). Codes expire after five minutes or ten wrong attempts. A connected browser is remembered for a year and can be removed there. A first start without a screen prints a code on the console.

An iPhone or iPad is offered once to put the application on its home screen, with the steps for that device; **Settings → Home screen** shows them again. It then opens like an app. An iPhone older than iOS 17.2 must connect once more from the icon.

Android makes a web page an app only over HTTPS. Over plain HTTP nothing is offered, and **Settings → Home screen shortcut** tells how to add a link that opens the dashboard in the browser.

Plain HTTP is not encrypted: use a trusted network, or an HTTPS reverse proxy with `ORIGIN` set.

### Bring an existing installation into setup

Before adding a camera, choose **Use existing setup**, close the old application, select its folder containing `config.json`, review the counts and import. Importing starts nothing and sends nothing, never replaces an existing setup, and resumes if it is interrupted. It works only on the computer the application runs on.

The import copies settings, `detections/`, local `presets/` and referenced local model and video files, and leaves the old files as they were. **Keep recordings in their current folder** links to the old archive instead: keep that drive available, because new recordings, reviews and deletions then happen there.

### Backup, recovery and storage

- **Settings → Back up** downloads `config.json`, `app.json` and the confirmed herd: cow names, their reference photos and where each was seen. It contains camera passwords and alert tokens, and no recordings, models, own presets, paired devices or unconfirmed cow photos. Restore it with **Use existing setup** in a new installation; an existing herd is never overwritten.
- When a settings file cannot be read, every page names the damaged file and offers **Recover settings**: the last valid settings are restored and the damaged files are kept beside them with an `.invalid` suffix.
- **Logs → Download diagnostics** bundles logs, system details and redacted settings, also when settings cannot be read. Review paths and camera addresses before sharing it.
- **Settings → Storage** shows free space and removes recordings older than a date you choose. Nothing deletes recordings automatically.

### Language

English, Nederlands, Deutsch and Français. An installation takes the language of the browser that sets it up, for every device and for its Telegram replies; change it under **Settings → Language**. Logs, the Advanced JSON editor's hints and the detector's own messages stay in English.

## Development

Use Node 24 and pnpm 9.15.9.

```sh
pnpm install --frozen-lockfile
pnpm dev
pnpm quality
pnpm build
pnpm test:production
```

`pnpm quality` runs the schema, formatting, lint, translation, type, dependency and unit checks. `pnpm test:production` exercises the built server over HTTP. The [architecture guide](ARCHITECTURE.md) maps the code and its rules. Interface text is written in English in the source and translated in `src/locales/*.po`; run `pnpm i18n` after changing it.

| Variable                       | Effect                                                                                                               |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| `AIDETECTOR_DATA_DIR`          | Folder with `config.json`, `app.json` and recordings. Development uses the working directory.                        |
| `AIDETECTOR_EXECUTABLE`        | Detector to start and supervise. Without it the server is only an interface to a detector that is managed elsewhere. |
| `AIDETECTOR_PRESETS`           | Folder of preset files, instead of `presets/` in the data folder or the bundled ones.                                |
| `AIDETECTOR_PRESETS_URL`       | Where newer presets are published, as a folder listing in GitHub's format. Empty switches following them off.        |
| `FFMPEG_PATH`                  | FFmpeg for camera checks and live pictures.                                                                          |
| `HOST`, `PORT`, `OPEN_BROWSER` | Listening address and port, and whether a browser opens. `HOST=127.0.0.1` also turns network discovery off.          |
| `ORIGIN`                       | The public address behind an HTTPS reverse proxy, such as `https://detector.example.com`.                            |

Missing settings files start an empty setup. A separately started detector needs `--live-preview` and the same data folder for detection boxes to appear.

### Executables and Docker

`AI_DETECTOR_WEB_TARGET` set to `windows-x64-baseline`, `darwin-arm64` or `linux-x64-baseline` makes `pnpm build` compile a single executable. The complete application is assembled and tested by [`distribution/build.py`](../distribution/README.md).

The container image is built from the [`Dockerfile`](../Dockerfile) in the repository root and holds this server together with the detector it starts:

```sh
docker build -t ai-detector .
```

It serves port 3000 unless `PORT` says otherwise, and reads `/data`. `pnpm start` runs the same server without a container. A container cannot open the host's browser; the [Linux startup helper](../README.md#start-automatically-on-a-jetson-or-linux-desktop) does that at login.
