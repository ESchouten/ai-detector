# AI Detector

Watch cameras, detect configured events locally, and review recordings in your browser. Models, watched classes and event rules are configurable. Optional Telegram alerts and AI verification are available in the settings.

For a visual explanation of how the application works, see the [system overview and diagrams](SYSTEM_OVERVIEW.md) (Dutch), from the web app and detector to the event-processing flow and domain model.

## Install, open, set up

1. Download the complete application for your computer from an **AI Detector app/** [release](https://github.com/ESchouten/ai-detector/releases).
2. Run the Windows installer, drag the macOS app from its disk image into Applications, or install the Ubuntu `.deb` with the desktop package manager.
3. Open **AI Detector**. Its browser setup helps you connect a camera and choose what to watch for. Python, the web server and FFmpeg are included.
4. Confirm the camera picture and choose what to watch for. Setup remembers your progress, checks the recording location and confirms current monitoring. Connect Telegram alerts or choose **No alerts for now**, then finish.

Telegram setup opens BotFather with the creation command prepared. After pasting its token once, open the verified bot link or scan its QR code, choose Start in Telegram, and confirm a test alert. Adding another camera offers your existing recipients; changing a recipient name or camera assignment does not require another connection test. **Finish setup** resumes an incomplete camera setup after reopening the application.

Setup choices come from a [configurable preset catalogue](config/README.md). The included general and cattle presets are examples; an installation can supply its own models, names, guidance and default without changing application code or rebuilding the executable. Existing cameras retain their saved settings when the catalogue changes.

For several cameras, choose **Set up several cameras** in Add camera. Select discovered devices that share a login, then check and save each picture and test recording. Successful connections stay ready if another camera fails. The next camera keeps your monitoring choice; each saved camera still has its own recording and alert checks.

On **Cameras**, **Show detections** displays the frame actually analysed, with boxes, confidence and temporary tracking numbers when tracking is enabled. Choose a rule when a camera has several. Previews pause outside the visible page, and at most four run per browser tab. Monitoring continues when previews are closed.

Closing the browser leaves monitoring active. Open **AI Detector** again to return to its dashboard; a verified second launch reuses the existing application. **Pause monitoring** keeps monitoring paused on future launches. Quitting the application stops it for the current session and preserves the enabled choice for next launch. Keep the computer awake while monitoring is needed.

| Packaging target         | Normal installer                            | Automatic runtime                                                               |
| ------------------------ | ------------------------------------------- | ------------------------------------------------------------------------------- |
| Windows 11 24H2+ x64     | `AI-Detector-VERSION-windows-x64-setup.exe` | Bundled native runtime, with available Windows ML acceleration and CPU fallback |
| macOS 14+ Apple Silicon  | `AI-Detector-VERSION-macos-arm64.dmg`       | Native PyTorch MPS for `.pt` models; ONNX/Core ML and CPU fallback when unavailable |
| Ubuntu 22.04/24.04 amd64 | `AI-Detector-VERSION-linux-amd64.deb`       | Bundled native CPU baseline                                                     |

The [Application download workflow](.github/workflows/application.yml) builds these formats for `app/v*` tags. Tagged publication now requires Windows signing and macOS signing/notarization credentials; older ZIP releases remain as originally published. Clean installation and hardware qualification are release gates, not outcomes established by source changes. See [packaging, signing requirements and verification](distribution/README.md). Manual workflow artifacts are unsigned developer previews.

Windows setup selects **Start AI Detector when I sign in** by default. The AI Detector icon beside the clock lets you open the dashboard, change **Start at login**, or quit. On macOS choose **Open at login** in the AI Detector menu-bar menu; macOS may require approval in System Settings. The Ubuntu package adds a login entry which can be disabled in Startup Applications. These options run under your desktop account **after login**. They do not promise unattended monitoring before login. Closing the browser does not change that preference.

Portable ZIPs remain available for technical users; extract them completely and keep their files together. If a browser does not open, the default dashboard is [localhost:8765](http://localhost:8765/). GPU availability depends on the operating system, driver and model. Docker is an explicit advanced runtime, not a prerequisite inferred from an NVIDIA card. Intel Macs, Windows ARM and Jetson do not yet have combined native installers; existing [detector installation options](detector/README.md) remain available.

## Your settings and recordings

The monitoring controls show the storage folder under **Advanced and troubleshooting**:

- Windows: `%LOCALAPPDATA%\AI Detector`
- macOS: `~/Library/Application Support/AI Detector`
- Linux: `$XDG_DATA_HOME/ai-detector`, or `~/.local/share/ai-detector`

Existing portable installations with `config.json` beside the executable continue using that directory. `AIDETECTOR_DATA_DIR` explicitly selects another location. Back up the whole data folder. When upgrading, use the new installer; on macOS quit AI Detector before replacing the app in Applications. Keep the data folder. For a portable ZIP, close the old application and replace its extracted application folder. Uninstalling a normal desktop package preserves settings and recordings.

The bundled web app listens on this computer only by default. Setting `HOST=0.0.0.0` deliberately enables LAN access; the web app does not provide authentication, so this is for a trusted network only.

## Existing Docker and source installations

The [example Compose file](example/compose.yml) remains available for an already configured NVIDIA container host:

```sh
cd example
docker compose up -d
```

That deployment uses separately managed containers; the browser cannot start or restart its detector. See [web development and distribution](web/README.md), [the detector guide](detector/README.md), and [how complete downloads are built and tested](distribution/README.md).

### Start automatically on a Jetson or Linux desktop

For an installed **JetPack 6** system with Docker Compose and the NVIDIA Container Runtime available, run this once from the repository folder, as the account used on the desktop:

```sh
python3 distribution/linux_startup.py install --compose example/compose.jetson.yml
```

The command requests the administrator password, enables Docker at boot, starts the services, and installs browser autostart for that desktop account. It opens the web app after it responds. On later boots, detection runs even before login; at desktop login the browser opens **Detections**, or **Setup** if no cameras are configured. For power-on without a login prompt, enable **Automatic Login** in the Linux desktop's user settings. The installer leaves that account setting to you.

Use the Compose file belonging to your existing installation so it keeps the same settings and recordings. On an ordinary NVIDIA Linux PC use `--compose example/compose.yml`. If you changed the published web port, also pass `--url http://localhost:YOUR_PORT/`. The Jetson example is specifically for JetPack 6; other JetPack versions need a matching detector image. This helper configures startup for an existing Docker installation; it does not install Docker or GPU drivers. Changes to detector settings still require `docker compose -f example/compose.jetson.yml restart aidetector`.

Both services use `restart: unless-stopped`. A deliberate `docker compose stop` keeps them stopped across reboots; run `docker compose up -d` with the same Compose file to resume them. Closing the browser does not stop either service.

Remove browser autostart with `python3 distribution/linux_startup.py uninstall`. This keeps Docker, services, settings and recordings. The helper copies its launcher into the user's data folder, so browser autostart does not depend on keeping a checkout of the installer; keep the installation's mounted data folder in place.

## Developing the system

See [the contributor guide](CONTRIBUTING.md) for the repository map, local setup and the **Repository: check** VS Code task. The [web architecture guide](web/ARCHITECTURE.md) explains request, configuration, process and archive boundaries; the [detector architecture](detector/ARCHITECTURE.md) explains event processing.
