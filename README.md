# AI Detector

Watch cameras, detect configured events locally, and review recordings in your browser. Models, watched classes and event rules are configurable. Optional Telegram alerts and AI verification are available in the settings.

For a visual explanation of how the application works, see the [system overview and diagrams](SYSTEM_OVERVIEW.md) (Dutch), from the web app and detector to the event-processing flow and domain model.

## Install, open, set up

1. Download the complete application for your computer from an **AI Detector app/** [release](https://github.com/ESchouten/ai-detector/releases).
2. Run the Windows installer, drag the macOS app from its disk image into Applications, or install the Ubuntu `.deb` with the desktop package manager.
3. Open **AI Detector**. Its browser setup guides you through cameras, detectors and final checks, in English, Dutch, German or French: it follows your browser's language, and the menu at the top of setup changes it. Python, the web server and FFmpeg are included.
4. Setup has three steps. In **Cameras**, select the cameras found on your network and enter their login, or choose **Enter a stream URL instead** and paste a full RTSP URL. Connect, check each picture, name the cameras and add them; recording compatibility is checked automatically. In **Detection**, choose a preset and select its cameras using their live pictures. A camera can be used by several detectors. Phone alerts and the Validator are optional parts of the same form. In **Start**, every camera is checked, and **Start monitoring** opens Recordings once the cameras are really being analysed. Saved cameras and detectors remain available when you return to an earlier step.

Telegram setup opens BotFather with the creation command prepared. After pasting its token once, open the verified bot link or scan its QR code, choose Start in Telegram, and confirm a test alert. Other detectors reuse your saved recipients; changing a recipient's name or detectors does not require another connection test. Reopening the application before monitoring was started resumes setup where you left off.

Afterwards the app has three main pages: **Recordings**, **Cameras** and **Detectors**, with everything else under **Settings**. On a phone they are tabs along the bottom. The monitoring status is always visible and opens a page showing what each camera is doing; a banner appears on the main pages when cameras are not being watched.

Setup choices come directly from [preset JSON files](config/README.md). The filename supplies the name: `cow-catcher.json` appears as **Cow Catcher**. Add a file to add a choice; no separate list or descriptions are required. Installations can supply their own preset folder without rebuilding, and saved detectors retain their settings when preset files change.

Several cameras can be added at once. Select every discovered device that shares a login, then check, name and add them together. Connections and recording compatibility are checked automatically. Successful connections stay ready if another camera fails. Add more cameras later with **Add camera** on Cameras, and choose what each should watch for on **Detectors**.

Camera previews automatically show detection boxes, confidence and temporary tracking numbers when tracking is enabled. Every detector assigned to a camera can appear together, with colors matching its preset badge. Video runs independently of inference; boxes show the latest result and can briefly lag behind moving objects. Automatic previews pause outside the visible page, and at most four run per browser tab. Monitoring continues when previews are closed.

Closing the browser leaves monitoring active. Open **AI Detector** again to return to its dashboard; a verified second launch reuses the existing application. **Pause monitoring** keeps monitoring paused on future launches. Quitting the application stops it for the current session and preserves the enabled choice for next launch. Keep the computer awake while monitoring is needed.

| Packaging target                  | Normal installer                            | Automatic runtime                                                                                                   |
| --------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Windows 10 22H2+ / Windows 11 x64 | `AI-Detector-VERSION-windows-x64-setup.zip` | Automatic CUDA download, plus direct TensorRT on RTX 3000+ when preparation succeeds; Windows ML for other hardware |
| macOS 14+ Apple Silicon           | `AI-Detector-VERSION-macos-arm64.dmg`       | Native PyTorch MPS for `.pt` models; ONNX/Core ML and CPU fallback when unavailable                                 |
| Ubuntu 22.04/24.04 amd64          | `AI-Detector-VERSION-linux-amd64.deb`       | Bundled native CPU baseline                                                                                         |

The [Application download workflow](.github/workflows/application.yml) builds these formats for `app/v*` release tags and `app/test-*` preview tags. Release publication authenticates updates with our own Ed25519 signing key; no Apple developer account or Windows signing subscription is required. Downloads have no OS-trusted publisher signature or Apple notarization, so macOS/Windows may warn or block execution. See [packaging, update verification and installation limitations](distribution/README.md). Test tags and manual branch runs publish signed previews to a separate update channel. Install its first preview once; later previews arrive through **Check for Updates** on Mac and installed Windows applications. See [building a preview in GitHub Actions](distribution/README.md#github-actions-previews).

Windows offers to start AI Detector when you sign in during its first launch. The AI Detector icon beside the clock lets you open the dashboard, change **Start at login**, or quit. On macOS choose **Open at login** in the AI Detector menu-bar menu; macOS may require approval in System Settings. The Ubuntu package adds a login entry which can be disabled in Startup Applications. These options run under your desktop account **after login**. They do not promise unattended monitoring before login. Closing the browser does not change that preference.

Choose the single installer for your operating system from the release. On Windows, extract the ZIP and run the setup EXE inside. The `.nupkg` and `.delta` assets support automatic updates and do not need to be downloaded manually. If a browser does not open, the default dashboard is [localhost](http://localhost/). GPU availability depends on the operating system, driver and model. Docker is an explicit advanced runtime, not a prerequisite inferred from an NVIDIA card. Intel Macs, Windows ARM and Jetson do not yet have combined native installers; existing [detector installation options](detector/README.md) remain available.

## Your settings and recordings

Use **Export** on Recordings to share a ZIP, optionally limited by date and the current filters. **Back up** under Settings saves cameras, detectors and alerts separately; this backup includes passwords and tokens and should stay private. See the [export and backup guide](web/README.md#export-recordings-and-back-up-settings).

The monitoring status page shows the storage folder under **Technical details**:

- Windows: `%LOCALAPPDATA%\AI Detector`
- macOS: `~/Library/Application Support/AI Detector`
- Linux: `$XDG_DATA_HOME/ai-detector`, or `~/.local/share/ai-detector`

For troubleshooting, open `logs/detector.log` inside that folder. It keeps detector startup settings, model preparation, camera connections and errors across restarts; older logs rotate into `detector.log.1` through `.5`. These Python logs are more complete than the dashboard's short recent-log view. See [detector diagnostics](detector/README.md#runtime-and-health) for log levels and retained context.

Existing portable installations with `config.json` beside the executable continue using that directory. `AIDETECTOR_DATA_DIR` explicitly selects another location. Back up the whole data folder. Updater-enabled Mac and Windows installations offer **Check for Updates** in the AI Detector menu. Download while monitoring continues, then restart to install. The first updater-enabled version still needs a manual installation; see the [migration and update guide](distribution/README.md#installation-and-data). To move from an older portable release, choose **Use existing setup** in the new installation and select the old folder. Linux upgrades use the new package. Uninstalling a normal desktop package preserves settings and recordings.

The bundled web app is available on the same network at `http://ai-detector.local/` or `http://<computer-IP>/`, while the installed computer opens its own localhost URL. It listens on `0.0.0.0` by default. If the mDNS name is already in use, the discovery library automatically adds a number and logs the selected address. The operating system keeps its own computer hostname. Other devices connect using the pairing code or QR code in **Settings → Devices**. `HOST=127.0.0.1` restricts access to the installed computer. HTTP traffic is not encrypted, so use a trusted local network or an HTTPS reverse proxy.

## Existing Docker and source installations

The [example Compose file](example/compose.yml) remains available for an already configured NVIDIA container host:

```sh
cd example
docker compose up -d
```

That deployment uses separately managed containers; the browser cannot start or restart its detector. See [web development and distribution](web/README.md), [the detector guide](detector/README.md), and [how complete downloads are built and tested](distribution/README.md).

### Start automatically on a Jetson or Linux desktop

For an existing **JetPack 6** installation using its legacy detector image, with Docker Compose and the NVIDIA Container Runtime available, run this once from the repository folder, as the account used on the desktop:

```sh
python3 distribution/linux_startup.py install --compose example/compose.jetson.yml
```

The command requests the administrator password, enables Docker at boot, starts the services, and installs browser autostart for that desktop account. It opens the web app after it responds. On later boots, detection runs even before login; at desktop login the browser opens **Detections**, or **Setup** if no cameras are configured. For power-on without a login prompt, enable **Automatic Login** in the Linux desktop's user settings. The installer leaves that account setting to you.

Use the Compose file belonging to your existing installation so it keeps the same settings and recordings. On an ordinary NVIDIA Linux PC use `--compose example/compose.yml`. If you changed the published web port, also pass `--url http://localhost:YOUR_PORT/`. The Jetson example preserves legacy JetPack 6 installations; new releases no longer build that image. The generic ARM64 image is not yet qualified for Orin / JetPack 7.2. See [Jetson migration guidance](detector/MIGRATION.md#python-312-and-jetpack-6-retirement--2026-09-28) before changing the OS or detector image. This helper configures startup for an existing Docker installation; it does not install Docker or GPU drivers. Changes to detector settings still require `docker compose -f example/compose.jetson.yml restart aidetector`.

Both services use `restart: unless-stopped`. A deliberate `docker compose stop` keeps them stopped across reboots; run `docker compose up -d` with the same Compose file to resume them. Closing the browser does not stop either service.

Remove browser autostart with `python3 distribution/linux_startup.py uninstall`. This keeps Docker, services, settings and recordings. The helper copies its launcher into the user's data folder, so browser autostart does not depend on keeping a checkout of the installer; keep the installation's mounted data folder in place.

## Developing the system

See [the contributor guide](CONTRIBUTING.md) for the repository map, local setup and the **Repository: check** VS Code task. The [web architecture guide](web/ARCHITECTURE.md) explains request, configuration, process and archive boundaries; the [detector architecture](detector/ARCHITECTURE.md) explains event processing.
