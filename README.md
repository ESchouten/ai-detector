# AI Detector

AI Detector watches your cameras on your own computer, records what a detector recognises, and shows it in your browser. Phone alerts through Telegram and a second check by an AI model are optional. Nothing runs on a server of ours.

## Install

Download the application for your computer from an **AI Detector app/** [release](https://github.com/ESchouten/ai-detector/releases).

| Computer | Download | Detection runs on |
| --- | --- | --- |
| Windows 10 22H2+ or Windows 11, x64 | `AI-Detector-VERSION-windows-x64-setup.zip` (extract, then run the setup) | A supported NVIDIA GPU when present, otherwise Windows ML |
| macOS 14+, Apple Silicon | `AI-Detector-VERSION-macos-arm64.dmg` (drag to Applications) | The Apple GPU |
| Ubuntu 22.04 or 24.04, amd64 | `AI-Detector-VERSION-linux-amd64.deb` | The CPU; for an NVIDIA GPU use [Docker](#docker) |

The downloads are not signed with an Apple or Windows publisher certificate, so the system may ask for approval. Intel Macs, Windows on ARM and Jetson have no installer; use [Docker](#docker) or run the [detector](detector/README.md) by itself.

## Set up

Open **AI Detector**. Setup opens in your browser, in English, Dutch, German or French. If no browser opens, go to [localhost](http://localhost/).

1. **Cameras.** The cameras found on your network are already ticked; a camera that needs its own login asks for it. Or paste an RTSP address. Check each picture and give the cameras a name.
2. **Detection.** Choose a preset, such as Cow Catcher, and the cameras it watches. Phone alerts and the Validator can be added here or later.
3. **Start.** Every camera is checked, and **Start monitoring** opens Recordings once the cameras are really being analysed.

Monitoring keeps running when you close the browser. Keep the computer awake while you need it. The [application guide](web/README.md) describes everything after setup.

## Good to know

- **Other devices.** Phones and computers on the same network open `http://aidetector.local/` or `http://<computer-IP>/` and connect with the code under **Settings → Devices**. A phone can keep the application on its home screen. The connection is not encrypted, so use a network you trust.
- **Starting at login.** Windows asks at first launch, macOS has **Open at login** in the menu-bar menu, and the Ubuntu package adds a login entry.
- **Updates.** Mac and Windows have **Check for Updates** in the AI Detector menu; Linux upgrades by installing the new package. A detector made from a preset gets newer models by itself.
- **Your data.** Settings, models and recordings live outside the program, and uninstalling leaves them in place. Back up the whole folder:
  - Windows: `%LOCALAPPDATA%\AI Detector`
  - macOS: `~/Library/Application Support/AI Detector`
  - Linux: `~/.local/share/ai-detector`
- **Something wrong?** **Logs → Download diagnostics** bundles what a bug report needs.
- **Coming from an older release?** Choose **Use existing setup** in the new installation and select the old folder.

## Docker

One image, `ghcr.io/eschouten/ai-detector`, holds the web application and the detector it starts and supervises, as the desktop application does. The [example Compose file](example/compose.yml) runs it on a Linux PC with an NVIDIA GPU and the NVIDIA Container Toolkit:

```sh
cd example
docker compose up -d
```

Open `http://<computer-IP>/`. Settings, models and recordings live in the folder beside the Compose file. The container uses the host's network so the cameras on it can be found; update with `docker compose pull && docker compose up -d`. Coming from the two separate images, read [Docker](detector/MIGRATION.md#docker) first.

| Host | Compose file |
| --- | --- |
| Linux PC with an NVIDIA GPU | [`example/compose.yml`](example/compose.yml) |
| Jetson Orin or Thor with JetPack 7.2 | [`example/compose.jetson.yml`](example/compose.jetson.yml); checked on an Orin Nano, not on a Thor, see [Jetson](detector/MIGRATION.md#jetson) |

### Start automatically on a Jetson or Linux desktop

For an existing Compose installation, run this once from the repository folder as the desktop's user:

```sh
python3 distribution/linux_startup.py install --compose example/compose.jetson.yml
```

It enables Docker at boot, starts the services and opens the application in the browser at login, so detection runs from boot. Use the Compose file your installation already uses, and add `--url http://localhost:YOUR_PORT/` if you changed the web port. `python3 distribution/linux_startup.py uninstall` removes the browser autostart and nothing else. The helper does not install Docker or GPU drivers.

## Where to read on

| You want to | Read |
| --- | --- |
| Use the application after setup | [web/README.md](web/README.md) |
| Run or configure the detector by itself | [detector/README.md](detector/README.md) |
| Write or publish a preset | [config/README.md](config/README.md) |
| See how the parts fit together | [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) |
| Change the code | [CONTRIBUTING.md](CONTRIBUTING.md), then the [web](web/ARCHITECTURE.md) and [detector](detector/ARCHITECTURE.md) architecture |
| Build installers or release | [distribution/README.md](distribution/README.md) |
