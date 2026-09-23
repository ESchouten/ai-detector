"""Prepare delta inputs and publish framework-generated feeds to immutable release assets."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def stable_version(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("Application update releases require a stable X.Y.Z version")
    return tuple(map(int, value.split(".")))


def newer_than(version: str, previous: list[str]) -> None:
    current = stable_version(version)
    if any(current <= stable_version(old) for old in previous):
        raise ValueError("An update must be newer than every published stable version")


def fetch_feed(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        # The first release has no feed. Network/server errors must fail the build.
        if error.code != 404:
            raise
        error.close()
        return None


def download(url: str, destination: Path, sha256: str | None = None) -> None:
    with (
        urllib.request.urlopen(url, timeout=60) as response,
        destination.open("wb") as output,
    ):
        shutil.copyfileobj(response, output)
    if sha256:
        with destination.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual.lower() != sha256.lower():
            raise ValueError(f"Previous package checksum failed: {destination.name}")


def mac_items(feed: bytes) -> list[tuple[str, ET.Element]]:
    result = []
    for item in ET.fromstring(feed).findall("./channel/item"):
        enclosure = item.find("enclosure")
        version = item.findtext(f"{{{SPARKLE}}}version")
        if enclosure is not None:
            version = version or enclosure.get(f"{{{SPARKLE}}}version")
            result.append((version, enclosure))
    return sorted(result, key=lambda item: stable_version(item[0]), reverse=True)


def prepare(
    output: Path, platform: str, version: str, feed_url: str, public_key: str = ""
) -> None:
    stable_version(version)
    name = "appcast.xml" if platform == "macos-arm64" else "releases.win.json"
    feed = fetch_feed(feed_url.rstrip("/") + "/" + name)
    folder = output / (
        "macos-updates" if platform == "macos-arm64" else "windows-updates"
    )
    folder.mkdir(parents=True, exist_ok=True)
    if feed is None:
        return
    if platform == "macos-arm64":
        items = mac_items(feed)
        newer_than(version, [old for old, _ in items])
        (folder / "appcast.xml").write_bytes(feed)
        for _, enclosure in items[:2]:
            url = enclosure.attrib["url"]
            name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
            download(url, folder / name)
    else:
        from release_signatures import verify_feed

        feed = verify_feed(feed, public_key)
        assets = json.loads(feed)["Assets"]
        newer_than(version, [asset["Version"] for asset in assets])
        (output / "previous-windows-feed.json").write_bytes(feed)
        full = [asset for asset in assets if asset["Type"] == "Full"]
        if full:
            latest = max(full, key=lambda asset: stable_version(asset["Version"]))
            url = urllib.parse.urljoin(feed_url.rstrip("/") + "/", latest["FileName"])
            name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
            download(url, folder / name, latest["SHA256"])


def macos(output: Path, version: str, release_url: str, sparkle: Path) -> None:
    folder = output / "macos-updates"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output / f"AI-Detector-{version}-macos-arm64.dmg", folder)
    subprocess.run(
        [
            str(sparkle / "bin/generate_appcast"),
            "--ed-key-file",
            "-",
            "--versions",
            version,
            "--maximum-versions",
            "3",
            "--maximum-deltas",
            "2",
            "--download-url-prefix",
            release_url.rstrip("/") + "/",
            str(folder),
        ],
        input=os.environ["SPARKLE_PRIVATE_KEY"],
        text=True,
        check=True,
    )
    items = mac_items((folder / "appcast.xml").read_bytes())
    if (
        not items
        or items[0][0] != version
        or not items[0][1].get(f"{{{SPARKLE}}}edSignature")
    ):
        raise ValueError(
            "Sparkle did not produce a signed update for this version; check the public/private key pair"
        )
    shutil.copy2(folder / "appcast.xml", output)
    for delta in folder.glob("*.delta"):
        shutil.copy2(delta, output)


def windows(
    output: Path, version: str, release_url: str, private_key: str, public_key: str
) -> None:
    from release_signatures import sign_feed

    folder = output / "windows-updates"
    generated = json.loads((folder / "releases.win.json").read_text())
    previous = output / "previous-windows-feed.json"
    assets = json.loads(previous.read_text())["Assets"] if previous.exists() else []
    newer_than(version, [asset["Version"] for asset in assets])
    current = [
        asset
        for asset in generated["Assets"]
        if asset["Version"] == version and asset["Type"] in {"Full", "Delta"}
    ]
    if not any(asset["Type"] == "Full" for asset in current):
        raise ValueError("Velopack did not produce a full package for this version")
    for asset in current:
        name = asset["FileName"]
        shutil.copy2(folder / name, output / name)
        # SimpleWebSource supports absolute package URLs; feed hosting stays independent.
        asset["FileName"] = release_url.rstrip("/") + "/" + urllib.parse.quote(name)
    assets += current
    versions = sorted(
        {asset["Version"] for asset in assets}, key=stable_version, reverse=True
    )[:3]
    feed = {"Assets": [asset for asset in assets if asset["Version"] in versions]}
    for asset in feed["Assets"]:
        if (
            asset["PackageId"] != "AIDetector"
            or not re.fullmatch(r"[a-fA-F0-9]{64}", asset["SHA256"])
            or asset["Size"] <= 0
        ):
            raise ValueError(
                "Every signed package must have its identity, size and SHA256"
            )
    (output / "releases.win.json").write_bytes(
        sign_feed(json.dumps(feed).encode(), private_key, public_key)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "publish"])
    parser.add_argument(
        "--platform", choices=["macos-arm64", "windows-x64"], required=True
    )
    parser.add_argument("--output", type=Path, default=Path("application-dist"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--feed-url")
    parser.add_argument("--release-url")
    parser.add_argument("--sparkle", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(
            args.output,
            args.platform,
            args.version,
            args.feed_url,
            os.environ.get("SPARKLE_PUBLIC_KEY", ""),
        )
    elif args.platform == "macos-arm64":
        macos(args.output, args.version, args.release_url, args.sparkle)
    else:
        windows(
            args.output,
            args.version,
            args.release_url,
            os.environ["SPARKLE_PRIVATE_KEY"],
            os.environ["SPARKLE_PUBLIC_KEY"],
        )
