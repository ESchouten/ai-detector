"""Combine the two signed release feeds for the desktop channel preference.

Per-channel feeds remain available for older installed launchers and delta inputs.
New launchers read the combined feed; native updaters still own installation.
"""

import argparse
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from release_signatures import sign_feed, verify_feed
from updates import SPARKLE, fetch_feed, numeric_version


def sparkle_signature(sdk: Path, feed: Path, *, verify: bool = False) -> None:
    subprocess.run(
        [
            str(sdk / "bin/sign_update"),
            "--ed-key-file",
            "-",
            *(["--verify"] if verify else []),
            str(feed),
        ],
        input=os.environ["SPARKLE_PRIVATE_KEY"],
        text=True,
        check=True,
    )


def merge_macos(current: bytes, other: bytes | None, channel: str) -> bytes:
    tree = ET.fromstring(current)
    target = tree.find("channel")
    for item in target.findall("item"):
        if channel == "preview":
            ET.SubElement(item, f"{{{SPARKLE}}}channel").text = "preview"
    if other:
        for item in ET.fromstring(other).findall("./channel/item"):
            if channel == "stable":
                ET.SubElement(item, f"{{{SPARKLE}}}channel").text = "preview"
            target.append(item)
    ET.register_namespace("sparkle", SPARKLE)
    return ET.tostring(tree, encoding="utf-8", xml_declaration=True)


def merge_windows(current: bytes, other: bytes | None, channel: str) -> bytes:
    feed = json.loads(current)
    for asset in feed["Assets"]:
        asset["ReleaseChannel"] = channel
        asset.setdefault("BuildVersion", "0.0.0")
    if other:
        for asset in json.loads(other)["Assets"]:
            asset["ReleaseChannel"] = "preview" if channel == "stable" else "stable"
            asset.setdefault("BuildVersion", "0.0.0")
            feed["Assets"].append(asset)
    feed["Assets"] = [asset for asset in feed["Assets"] if asset["Type"] == "Full"]
    return json.dumps(feed).encode()


def publish(
    output: Path,
    platform: str,
    channel: str,
    feed_url: str,
    build_version: str,
    sdk: Path | None,
) -> None:
    name = "appcast.xml" if platform == "macos-arm64" else "releases.win.json"
    root_url = feed_url.rstrip("/").rsplit("/", 1)[0]
    other_tag = "app-preview-updates" if channel == "stable" else "app-updates"
    other = fetch_feed(f"{root_url}/{other_tag}/{name}")
    destination = output / "channel-updates"
    destination.mkdir(exist_ok=True)
    current = (output / name).read_bytes()
    if platform == "macos-arm64":
        # Verify before including the other channel's entries in a newly signed feed.
        if other:
            other_file = destination / "previous.xml"
            other_file.write_bytes(other)
            sparkle_signature(sdk, other_file, verify=True)
            other_file.unlink()
            versions = [
                item.findtext(f"{{{SPARKLE}}}version")
                for item in ET.fromstring(other).findall("./channel/item")
            ]
            if any(
                numeric_version(old) >= numeric_version(build_version)
                for old in versions
            ):
                raise ValueError(
                    "Build version must advance across both update channels"
                )
        (destination / name).write_bytes(merge_macos(current, other, channel))
        sparkle_signature(sdk, destination / name)
    else:
        public_key = os.environ["SPARKLE_PUBLIC_KEY"]
        current = verify_feed(current, public_key)
        other = verify_feed(other, public_key) if other else None
        if other and any(
            numeric_version(asset.get("BuildVersion", "0.0.0"))
            >= numeric_version(build_version)
            for asset in json.loads(other)["Assets"]
        ):
            raise ValueError("Build version must advance across both update channels")
        (destination / name).write_bytes(
            sign_feed(
                merge_windows(current, other, channel),
                os.environ["SPARKLE_PRIVATE_KEY"],
                public_key,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("application-dist"))
    parser.add_argument(
        "--platform", choices=["macos-arm64", "windows-x64"], required=True
    )
    parser.add_argument("--channel", choices=["stable", "preview"], required=True)
    parser.add_argument("--feed-url", required=True)
    parser.add_argument("--build-version", required=True)
    parser.add_argument("--sdk", type=Path)
    publish(**vars(parser.parse_args()))
