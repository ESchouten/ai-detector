# AI Detector web application

The interface of AI Detector: setup, cameras, detectors, recordings and settings. In the [complete application](../README.md) it also starts and supervises the detector. This guide covers using it after setup; the [architecture guide](ARCHITECTURE.md) covers working on it.

## Using the application

There are three main pages, **Recordings**, **Cameras** and **Detectors**; everything else is under **Settings**. The monitoring state is always visible and opens a status page.

### Monitoring

- A camera counts as monitored only when fresh pictures are being analysed by every detector assigned to it. A started program is not proof.
- Closing the browser leaves monitoring running. **Pause monitoring** also keeps it paused at the next launch.
- **Camera offline** under **Settings → Alerts** appears once a phone alarm is connected, and is off by default. When enabled, a camera that has not been watched for five minutes is reported to the phone alarm of the detectors that watch it, as a normal notification without the alarm sound, and reported again once it has been watched for a minute. Time in which the computer slept or AI Detector was not running counts, and is reported when the cameras are back. Pausing monitoring is not reported. A notice that cannot be sent is tried again every minute for a day. Switching the setting off cancels queued notices. This needs the complete application, which starts the detector itself.
- **Heartbeat** on the status page is an address the detector calls while it runs, so a service such as Healthchecks.io can warn you when the computer stops. It is the only warning that works while the computer is off or has no internet.
- A detector that stops is started again by itself. From the fifth failure in a row until a detector has started properly, every page shows that monitoring has stopped, and Recordings, Cameras, Detectors, the status page and setup say why; for a stop without a known cause they also say what to do. The attempts continue meanwhile.
- Alert and AI check failures stay visible in the status until a later attempt succeeds.

### Cameras

Camera pictures show the latest detection boxes over live video; the boxes can lag behind moving objects. At most four live pictures run per browser tab, and hidden ones are released. A camera shows its first picture at its next keyframe, which can take a few seconds; after that the picture stays ready for twenty seconds.

**History** on the same page shows, per camera, when it was really watched over the last hour, day or week, with every recording as a mark on the same line; a mark opens the recording. A gap is time in which nothing would have been noticed, and it says why: the camera was offline, monitoring was paused, or AI Detector was not running. History is kept for thirty days, and a gap is known to within about ten seconds. With a separately managed detector only the recordings are shown.

A camera whose network address changes, as happens when the router hands out addresses by itself, is found again. After two minutes without pictures the application searches the network, and once it finds the camera at exactly one other address it watches it there. With **Camera offline** switched on, the phone alarm reports the new address. A fixed address in the router (a DHCP reservation) avoids the interruption.

### Detectors and presets

A detector made from a preset follows it. When a newer model is published for that preset, the detector takes it within a day or at the next start: monitoring restarts by itself and is interrupted while the model is downloaded and prepared. Cameras, alerts and the AI check stay as you set them. For this the application asks GitHub once a day; without internet nothing changes.

**Update automatically** in a detector's settings switches this off for that detector: it then keeps the model it has until you switch it on again or choose the preset anew.

A preset can come in more than one mode, chosen under the preset in a detector's settings. **Default** is the preset's own settings. Calving Catcher also has **Low Power**, which looks less often: it asks less of the computer and can notice an event later. A detector follows the mode it is in.

A detector whose detection settings you changed keeps them and is not updated. Choose the preset again to follow it.

A detector watches the whole picture of each of its cameras. **Whole picture** on a chosen camera in the detector's settings limits it to a part: tap the corners of the area to watch, and a detection counts only when the middle of its box is inside it.

### Recordings

- Selecting a recording opens a viewer; the arrow keys step through recordings.
- The thumbs record your own verdict. Pressing your choice again removes it and restores the AI check's result.
- The chips filter by category and by result; pressing a chosen chip clears it.
- The bin in the viewer deletes that recording from the computer, after asking once.
- **Export** downloads a ZIP of the current filter, optionally between two dates, laid out as `detections/<category>/<stage>/<timestamp>/` with images, clips and `metadata.json`. In that file `review` is the person's decision and `validated` the AI check's. **Only the original photos** leaves out videos and pictures with boxes, for a small ZIP to share with the people who train the model. A confirmed event is not a checked bounding box: annotate the original images before training a model with them.

### Telegram alerts

**Connect Telegram** opens inside the detector editor. Paste a BotFather token once, choose **My phone**, **A group** or **A channel**, and confirm the test alert in that chat. Recipients belong to detectors, so one bot can send different detectors' alerts to different chats.

- Alerts carry 👍 and 👎 buttons that save a review; the thumb you press stays coloured on that alert. The application must be running for this, and the bot must be used by this installation only.
- **Quiet hours** on a recipient make alerts between two times of day arrive without sound, for example at night. They still arrive.
- **Enter chat ID manually** is for a bot that another application also reads. Setup never removes another application's webhook.

### Phone alarm

**Connect ntfy** under **Settings → Alerts**, or in the detector editor, makes a detection ring your phone loudly, also at night, with a picture of what the detector saw. It uses the free ntfy app and needs no account: install ntfy, subscribe to the name the application shows, confirm the test alarm and choose the detectors that ring it. It works beside Telegram alerts or without them.

- There is one alarm per installation. Every phone subscribed to its name rings, so keep the name to yourself.
- On Android the alarm can ring through Do Not Disturb and keep ringing until you look; the steps are shown while connecting. An iPhone shows the alarm but stays silent in silent mode.
- The alarm travels through the ntfy.sh service, so it needs internet.
- **Camera offline** on the same page reports a camera that is no longer watched, as [Monitoring](#monitoring) describes.

### AI check

An **AI check** connection lets a vision language model confirm or reject each event. Under **Settings → AI check**, connect Google Gemini with a key from AI Studio; other providers are set under **Advanced → AI connections**.

A connection is saved once and used by any number of detectors, each with its own question. Turning the AI check off for a detector keeps its question and clears its keys. A connection in use cannot be removed.

### Other devices

The application listens on port 80 of every network address, so other devices open `http://aidetector.local/` or `http://<computer-IP>/`. When another program has that port, it takes the first free one from 8080 to 8089 and keeps it. The computer it runs on is trusted; every other browser needs a one-use code from **Settings → Devices** (scan the QR code, then tap Connect). Codes expire after five minutes or ten wrong attempts. A connected browser is remembered for a year and can be removed there. A first start without a screen prints a code on the console.

An iPhone or iPad is offered once to put the application on its home screen, with the steps for that device; **Settings → Home screen** shows them again. It then opens like an app. An iPhone older than iOS 17.2 must connect once more from the icon.

Android makes a web page an app only over HTTPS. Over plain HTTP nothing is offered, and **Settings → Home screen shortcut** tells how to add a link that opens the dashboard in the browser.

Plain HTTP is not encrypted: use a trusted network, or an HTTPS reverse proxy with `ORIGIN` set.

### Bring an existing installation into setup

Before adding a camera, choose **Use existing setup**, close the old application, select its folder containing `config.json`, review the counts and import. Importing starts nothing and sends nothing, never replaces an existing setup, and resumes if it is interrupted. It works only on the computer the application runs on.

Import fills in missing or empty names and treats empty optional settings in the old `app.json` as unset, with a note before copying. Optional lists may be empty, and a setup may have no detectors; an existing detector still needs at least one camera source. Old paired devices and camera verification are not imported. Camera sources, detector rules and alert credentials still have to be valid. Invalid app metadata is reported with its file and field instead of a raw validator message. The original settings files stay unchanged.

The import copies settings, `detections/`, local `presets/` and referenced local model and video files, and leaves the old files as they were. **Keep recordings in their current folder** links to the old archive instead: keep that drive available, because new recordings, reviews and deletions then happen there.

### Backup, recovery and storage

- **Settings → Back up** downloads `config.json` and `app.json`. It contains camera passwords and alert tokens, and no recordings, models, own presets or paired devices. Restore it with **Use existing setup** in a new installation.
- When a settings file cannot be read, every page names the damaged file and offers **Recover settings**: the last valid settings are restored and the damaged files are kept beside them with an `.invalid` suffix.
- **Logs → Download diagnostics** bundles logs, system details and redacted settings, also when settings cannot be read. Review paths and camera addresses before sharing it.
- **Settings → Storage** shows free space and removes recordings older than a date you choose. Nothing deletes recordings automatically.

### Language

English, Nederlands, Deutsch, Français, Español, Português, Polski, Türkçe and 简体中文. An installation takes the language of the browser that sets it up, for every device and for its Telegram replies; change it under **Settings → Language**. Logs, the Advanced JSON editor's hints and the detector's own messages stay in English; the logs repeat a status or error message in the language it was shown in.
