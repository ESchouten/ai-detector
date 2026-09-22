# AI Detector

Watch farm cameras, detect events locally, and review recordings in your browser. Optional Telegram alerts and AI verification are available in the settings.

For a visual explanation of how the application works, see the [system overview and diagrams](SYSTEM_OVERVIEW.md) (Dutch), from the web app and detector to the event-processing flow and domain model.

## Download, open, set up

1. Download the **complete application ZIP** for your computer from an **AI Detector app/** [release](https://github.com/ESchouten/ai-detector/releases). Extract the entire ZIP.
2. Open **AI Detector**. Keep the accompanying `detector` and `bin` folders beside it. Python, Node and FFmpeg do not need to be installed separately.
3. On first launch, your browser opens the setup page. Give your camera a name, enter its stream address and choose a detection preset. Later launches open **Detections**.
4. Save the camera and select **Start detection**. Add Telegram alerts later if needed.

If the browser does not open, visit [localhost:8765](http://localhost:8765/). Keep the application open and the computer awake while monitoring is needed. Closing the browser tab does not stop detection. The application remembers whether detection was enabled and resumes it at the next launch; **Stop detection** disables that automatic resume.

The combined downloads are produced by the new [Application download workflow](.github/workflows/application.yml) on `app/v*` tags. Older `detector/v*` and `web/v*` releases contain separate components and do not provide this combined setup. These builds are not yet signed or notarized; the operating system may require permission to open a downloaded executable.

| Computer | Complete download | Automatic detection runtime |
| --- | --- | --- |
| Windows x64 | `AI-Detector-windows-x64.zip` | NVIDIA Docker when an NVIDIA driver reports a GPU; otherwise native Windows ML |
| Apple Silicon Mac | `AI-Detector-macos-arm64.zip` | Native detector with available ONNX/Core ML providers |
| Linux x64, glibc 2.35+ | `AI-Detector-linux-x64.zip` | NVIDIA Docker when a GPU is detected; otherwise native CPU runtime |

GPU availability depends on the installed driver and model. Windows Docker GPU support requires its [WSL 2 backend](https://docs.docker.com/desktop/features/gpu/). Linux NVIDIA containers need the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Setup checks a real CUDA operation before starting the Docker detector, gives instructions when a prerequisite is missing, and lets you choose **On this computer** instead. It does not silently install drivers or Docker, or request administrator access.

Intel Macs, Windows ARM and Jetson do not yet have combined downloads. The existing JetPack image and [detector installation options](detector/README.md) remain available.

## Your settings and recordings

The setup page shows the storage folder under **Details for troubleshooting**:

- Windows: `%LOCALAPPDATA%\AI Detector`
- macOS: `~/Library/Application Support/AI Detector`
- Linux: `$XDG_DATA_HOME/ai-detector`, or `~/.local/share/ai-detector`

Existing portable installations with `config.json` beside the executable continue using that directory. `AIDETECTOR_DATA_DIR` explicitly selects another location. Back up the whole data folder. When upgrading, close the old application and replace the extracted application folder; keep the data folder.

The bundled web app listens on this computer only by default. Setting `HOST=0.0.0.0` deliberately enables LAN access; the web app does not provide authentication, so this is for a trusted network only.

## Existing Docker and source installations

The [example Compose file](example/compose.yml) remains available for an already configured NVIDIA container host:

```sh
cd example
docker compose up -d
```

That deployment uses separately managed containers; the browser cannot start or restart its detector. See [web development and distribution](web/README.md), [the detector guide](detector/README.md), and [how complete downloads are built and tested](distribution/README.md).

### Start automatically on a Jetson or Linux desktop

For an installed **JetPack 6** system with Docker Compose and the NVIDIA Container Runtime available, run this once from the repository folder, as the account the farmer uses on the desktop:

```sh
python3 distribution/linux_startup.py install --compose example/compose.jetson.yml
```

The command requests the administrator password, enables Docker at boot, starts the services, and installs browser autostart for that desktop account. It opens the web app after it responds. On later boots, detection runs even before login; at desktop login the browser opens **Detections**, or **Setup** if no cameras are configured. For power-on without a login prompt, enable **Automatic Login** in the Linux desktop's user settings. The installer leaves that account setting to you.

Use the Compose file belonging to your existing installation so it keeps the same settings and recordings. On an ordinary NVIDIA Linux PC use `--compose example/compose.yml`. If you changed the published web port, also pass `--url http://localhost:YOUR_PORT/`. The Jetson example is specifically for JetPack 6; other JetPack versions need a matching detector image. This helper configures startup for an existing Docker installation; it does not install Docker or GPU drivers. Changes to detector settings still require `docker compose -f example/compose.jetson.yml restart aidetector`.

Both services use `restart: unless-stopped`. A deliberate `docker compose stop` keeps them stopped across reboots; run `docker compose up -d` with the same Compose file to resume them. Closing the browser does not stop either service.

Remove browser autostart with `python3 distribution/linux_startup.py uninstall`. This keeps Docker, services, settings and recordings. The helper copies its launcher into the user's data folder, so browser autostart does not depend on keeping a checkout of the installer; keep the installation's mounted data folder in place.
