"""Resolve one application version and update channel for every release job."""

import os
from pathlib import Path
from urllib.parse import quote

from updates import numeric_version


def release_config(
    ref: str, repository: str, run_number: int, run_id: int
) -> dict[str, str]:
    if ref.startswith("refs/tags/app/v"):
        tag = ref.removeprefix("refs/tags/")
        version = tag.removeprefix("app/v")
        channel = "stable"
        feed_tag = "app-updates"
    else:
        if ref.startswith("refs/tags/app/test-"):
            tag = ref.removeprefix("refs/tags/")
        elif ref.startswith("refs/heads/"):
            tag = f"app/test-run-{run_id}"
        else:
            raise ValueError("Use an app/v* tag, an app/test-* tag or a branch run")
        version = f"0.0.{run_number}"
        channel = "preview"
        feed_tag = "app-preview-updates"
    numeric_version(version)
    downloads = f"https://github.com/{repository}/releases/download/"
    return {
        "version": version,
        "tag": tag,
        "channel": channel,
        "feed_tag": feed_tag,
        "feed_url": downloads + quote(feed_tag, safe=""),
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
