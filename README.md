# AI Detector

Watch cameras, detect configured events on your own computer, and review the recordings in your browser. Telegram alerts and AI verification are optional.

The [system overview](SYSTEM_OVERVIEW.md) explains with diagrams how the application works.

## Install, open, set up

1. Download the application for your computer from an **AI Detector app/** [release](https://github.com/ESchouten/ai-detector/releases).
2. Run the Windows installer (extract the ZIP first), drag the macOS app from its disk image into Applications, or install the Ubuntu `.deb`.
3. Open **AI Detector**. Setup opens in your browser, in English, Dutch, German or French: it follows the browser's language, and the menu at the top changes it.

Setup has three steps:

- **Cameras**: select the cameras found on your network and enter their login, or choose **Enter a stream URL instead** and paste a full RTSP URL. Connect, check each picture, name the cameras and add them. Several cameras that share a login can be added together; a camera that fails does not undo the others.
- **Detection**: choose a preset and the cameras it should watch. A camera can be watched by several detectors. Phone alerts and the Validator are optional parts of the same form.
- **Start**: every camera is checked, and **Start monitoring** opens Recordings once the cameras are really being analysed.

Reopening the application before monitoring was started resumes setup where you left it.

Afterwards there are three main pages, **Recordings**, **Cameras** and **Detectors**, and everything else is under **Settings**; on a phone they are tabs along the bottom. The monitoring status is always visible, and a banner appears when cameras are not being watched.

Closing the browser leaves monitoring running. **Pause monitoring** keeps it paused on later launches too. Quitting the application stops it and remembers the choice for next time. Keep the computer awake while monitoring is needed.

Presets come from [JSON files](config/README.md); `cow-catcher.json` appears as **Cow Catcher**. An installation can add its own.

| Computer | Installer | Detection runs on |
| --- | --- | --- |
| Windows 10 22H2+ / Windows 11 x64 | `AI-Detector-VERSION-windows-x64-setup.zip` | A supported NVIDIA GPU when present (its software is downloaded once), otherwise Windows ML |
| macOS 14+ Apple Silicon | `AI-Detector-VERSION-macos-arm64.dmg` | The Apple GPU when available |
| Ubuntu 22.04/24.04 amd64 | `AI-Detector-VERSION-linux-amd64.deb` | The CPU |

Intel Macs, Windows on ARM and Jetson have no combined installer; the [detector](detector/README.md) can still be run separately there.

The downloads are not signed by an Apple or Windows publisher certificate, so macOS and Windows may warn or ask for approval. Updates are verified with the project's own signing key; see [installers and updates](distribution/README.md). If no browser opens, the dashboard is at [localhost](http://localhost/).

**Starting at login.** Windows offers it at first launch and in the icon beside the clock; on macOS choose **Open at login** in the menu-bar menu; the Ubuntu package adds a login entry. All of these start after you sign in, not before.

**Other devices.** Phones and computers on the same network open `http://ai-detector.local/` or `http://<computer-IP>/` and connect with the code or QR code under **Settings → Devices**. The connection is not encrypted, so use it on a network you trust.

**Updates.** Mac and Windows offer **Check for Updates** in the AI Detector menu: the download runs while monitoring continues, and a restart installs it. Linux upgrades by installing the new package.

## Your settings and recordings

**Export** on Recordings downloads a ZIP, optionally limited by date and filters. **Back up** under Settings saves cameras, detectors and alerts; it contains passwords and tokens, so keep it private. See [export and backup](web/README.md#export-recordings-and-back-up-settings).

Settings, models and recordings are kept outside the program, in the folder shown on the monitoring status page under **Technical details**:

- Windows: `%LOCALAPPDATA%\AI Detector`
- macOS: `~/Library/Application Support/AI Detector`
- Linux: `~/.local/share/ai-detector`

Back up that whole folder. Uninstalling the application leaves it in place. For troubleshooting, `logs/detector.log` in that folder keeps startup settings, camera connections and errors across restarts; **Logs → Download diagnostics** in the application bundles everything needed for a report.

To move from an older portable release, choose **Use existing setup** in the new installation and select the old folder; see [moving from an older installation](distribution/README.md#installation-and-data).

## Docker and source installations

The [example Compose file](example/compose.yml) is for an already configured NVIDIA container host:

```sh
cd example
docker compose up -d
```

There the containers are managed separately: the browser cannot start or restart the detector, and a change to detector settings needs `docker compose restart aidetector`. See the [web](web/README.md), [detector](detector/README.md) and [distribution](distribution/README.md) guides.

### Start automatically on a Jetson or Linux desktop

For an existing Docker Compose installation, run this once from the repository folder, as the desktop's user:

```sh
python3 distribution/linux_startup.py install --compose example/compose.jetson.yml
```

It asks for the administrator password, enables Docker at boot, starts the services and makes the browser open the application at login. Detection then runs from boot, even before anyone logs in. Use the Compose file your installation already uses, so that it keeps its settings and recordings: `example/compose.yml` on an ordinary NVIDIA Linux PC. Add `--url http://localhost:YOUR_PORT/` if you changed the web port. For power-on without a login prompt, enable **Automatic Login** in the desktop's user settings yourself.

The helper does not install Docker or GPU drivers. `python3 distribution/linux_startup.py uninstall` removes the browser autostart and nothing else. `docker compose stop` keeps the services stopped across reboots until `docker compose up -d`.

The Jetson example serves existing JetPack 6 installations; new images are not built for it, and JetPack 7.2 is not yet qualified. Read [Jetson](detector/MIGRATION.md#jetson) before changing the system or the image.

## Developing

Start with the [contributor guide](CONTRIBUTING.md). The [web architecture](web/ARCHITECTURE.md) covers requests, settings, the detector process and recordings; the [detector architecture](detector/ARCHITECTURE.md) covers event processing.
