"""Print a release summary from GitHub's job and artifact responses."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path


def summarize(jobs: list[dict], artifacts: list[dict]) -> str:
    rows = ["| Job | Result | Duration |", "| --- | --- | ---: |"]
    for job in jobs:
        if not job.get("completed_at"):
            continue
        duration = "—"
        if job["conclusion"] != "skipped" and job.get("started_at"):
            elapsed = datetime.fromisoformat(
                job["completed_at"]
            ) - datetime.fromisoformat(job["started_at"])
            seconds = max(0, int(elapsed.total_seconds()))
            duration = f"{seconds // 60}m {seconds % 60:02d}s"
        rows.append(
            f"| [{job['name']}]({job['html_url']}) | {job['conclusion']} | {duration} |"
        )
    rows += ["", "| Installer artifact | Size |", "| --- | ---: |"]
    for artifact in artifacts:
        if artifact["name"].startswith("AI-Detector-"):
            rows.append(
                f"| {artifact['name']} | {artifact['size_in_bytes'] / 2**20:.1f} MiB |"
            )
    return "\n".join(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", type=Path)
    parser.add_argument("artifacts", type=Path)
    args = parser.parse_args()
    print(
        f"AI Detector **{os.environ['APP_VERSION']}** · "
        f"{os.environ['UPDATE_CHANNEL']} · build {os.environ['APP_BUILD_VERSION']}\n"
    )
    print(f"Commit: `{os.environ['GITHUB_SHA']}`\n")
    print(
        summarize(
            json.loads(args.jobs.read_text())["jobs"],
            json.loads(args.artifacts.read_text())["artifacts"],
        )
    )
