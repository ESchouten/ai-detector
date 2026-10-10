"""Enable boot and desktop startup for an installed Linux Compose deployment."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


def startup_paths() -> tuple[Path, Path]:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return config / "autostart/ai-detector.desktop", data / "ai-detector/startup.py"


def desktop_argument(value: str) -> str:
    """Quote an Exec argument, then escape it as a Desktop Entry string."""
    value = value.replace("%", "%%")
    for character in ("\\", '"', "`", "$"):
        value = value.replace(character, "\\" + character)
    value = (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{value}"'


def install(compose: Path, url: str) -> None:
    for command in ("docker", "systemctl", "sudo", "xdg-open"):
        if shutil.which(command) is None:
            raise ValueError(f"Install {command} before enabling startup.")

    compose_command = [
        "sudo",
        "docker",
        "compose",
        "-f",
        str(compose.resolve(strict=True)),
    ]
    configuration = subprocess.run(
        [*compose_command, "config", "--format", "json"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    services = json.loads(configuration.stdout)["services"]
    if any(
        service.get("restart") not in ("always", "unless-stopped")
        for service in services.values()
    ):
        raise ValueError(
            "Set restart: unless-stopped on each Compose service before enabling startup."
        )

    subprocess.run(
        ["sudo", "systemctl", "enable", "--now", "docker.service"], check=True
    )
    subprocess.run([*compose_command, "up", "-d"], check=True)

    desktop, launcher = startup_paths()
    launcher.parent.mkdir(parents=True, exist_ok=True)
    if Path(__file__).resolve() != launcher.resolve():
        shutil.copyfile(__file__, launcher)
    command = " ".join(
        desktop_argument(argument)
        for argument in (sys.executable, str(launcher), "open", "--url", url)
    )
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(
        "[Desktop Entry]\nType=Application\nName=AI Detector\n"
        "Comment=Open the AI Detector dashboard when the desktop starts\n"
        f"Exec={command}\nTerminal=false\n",
        encoding="utf-8",
    )
    print(
        "Startup enabled. Detection starts at boot; the browser opens at desktop login."
    )
    print("New installations open Setup; configured installations open Detections.")
    print(
        "For unattended power-on, enable automatic login in the Linux desktop settings."
    )


def wait_for_webapp(url: str, timeout: float = 300) -> None:
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            with urlopen(url, timeout=min(5, remaining)):
                return
        except HTTPError as error:
            error.close()
        except OSError:
            pass
        # The desktop can start before Docker has finished starting the web service.
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise TimeoutError(
        f"AI Detector did not respond within {timeout:g} seconds. Check Docker and open {url}."
    )


def uninstall() -> None:
    desktop, launcher = startup_paths()
    desktop.unlink(missing_ok=True)
    launcher.unlink(missing_ok=True)
    print("Browser autostart removed. Docker services and your data are unchanged.")


def open_browser(url: str) -> None:
    wait_for_webapp(url)
    subprocess.run(["xdg-open", url], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    installer = commands.add_parser(
        "install", help="Enable Docker at boot and the browser at desktop login"
    )
    installer.add_argument(
        "--compose",
        type=Path,
        required=True,
        help="Existing Compose file for this installation",
    )
    installer.add_argument(
        "--url",
        default="http://localhost/",
        help="Web app URL, including its published port",
    )
    launcher = commands.add_parser(
        "open", help="Wait for the web app and open the browser"
    )
    launcher.add_argument("--url", default="http://localhost/")
    commands.add_parser(
        "uninstall", help="Remove browser autostart; keep Docker services and data"
    )
    arguments = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() == 0:
        parser.error(
            "Run this from the Linux desktop user's account, without sudo. Installation requests sudo itself."
        )

    try:
        if arguments.command == "install":
            install(arguments.compose, arguments.url)
            open_browser(arguments.url)
        elif arguments.command == "open":
            open_browser(arguments.url)
        else:
            uninstall()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(
            f"Could not {arguments.command} AI Detector startup: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
