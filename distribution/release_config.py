"""Resolve one application version and update channel for every release job."""

import os
import re
from pathlib import Path
from urllib.parse import quote

from updates import numeric_version

CANDIDATE = re.compile(r"v((0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-[0-9A-Za-z.-]+)")


def release_config(
    ref: str, repository: str, run_number: int, run_id: int
) -> dict[str, str]:
    tag = ref.removeprefix("refs/tags/")
    if tag.startswith("v") and "-" not in tag:
        version = name = tag.removeprefix("v")
        channel = "stable"
        feed_tag = "app-updates"
    else:
        version = name = f"0.0.{run_number}"
        if tag.startswith("v"):
            # A release candidate, such as v1.0.0-rc.0, is a preview under its own name.
            candidate = CANDIDATE.fullmatch(tag)
            if not candidate:
                raise ValueError("Name a release candidate like v1.0.0-rc.0")
            name = candidate[1]
        elif ref.startswith("refs/heads/"):
            tag = f"test-run-{run_id}"
        elif not tag.startswith("test-"):
            raise ValueError("Use a v* tag, a test-* tag or a branch run")
        channel = "preview"
        feed_tag = "app-preview-updates"
    numeric_version(version)
    downloads = f"https://github.com/{repository}/releases/download/"
    return {
        "version": version,
        # What people read on the release page and in the application.
        "name": name,
        # One sequence across both channels; display versions remain independent.
        "build_version": f"{run_number}.0.0",
        "tag": tag,
        "channel": channel,
        "feed_tag": feed_tag,
        "feed_url": downloads + quote(feed_tag, safe=""),
        "channels_url": downloads + "app-update-channels",
        "release_url": downloads + quote(tag, safe=""),
    }


if __name__ == "__main__":
    config = release_config(
        os.environ["GITHUB_REF"],
        os.environ["GITHUB_REPOSITORY"],
        int(os.environ["GITHUB_RUN_NUMBER"]),
        int(os.environ["GITHUB_RUN_ID"]),
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.writelines(f"{key}={value}\n" for key, value in config.items())
