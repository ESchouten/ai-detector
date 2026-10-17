"""Find a detector that an earlier application build froze and tested from the same sources."""

import argparse
import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable

WORKFLOW = ".github/workflows/application.yml"


def trusted(artifact: dict, run: dict, repository: str) -> bool:
    """Accept a detector only from this repository's own application builds.

    Artifacts are found by name, and a pull request from a fork can upload one with any
    name. Tag pushes and manual runs need write access; those are the builds that
    freeze, smoke-test and upload the detector.
    """
    return (
        not artifact["expired"]
        and run["path"] == WORKFLOW
        and run["event"] in {"push", "workflow_dispatch"}
        and run["repository"]["full_name"] == repository
        and (run["head_repository"] or {}).get("full_name") == repository
    )


def find(name: str, repository: str, fetch: Callable[[str], dict]) -> int | None:
    """The newest trusted run that uploaded this artifact, if any."""
    query = urllib.parse.urlencode({"name": name, "per_page": 20})
    artifacts = fetch(f"repos/{repository}/actions/artifacts?{query}")["artifacts"]
    for artifact in sorted(
        artifacts, key=lambda item: item["created_at"], reverse=True
    ):
        run = fetch(f"repos/{repository}/actions/runs/{artifact['workflow_run']['id']}")
        if trusted(artifact, run, repository):
            return run["id"]
    return None


def github(path: str) -> dict:
    request = urllib.request.Request(
        os.environ.get("GITHUB_API_URL", "https://api.github.com") + "/" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", help="Artifact name, including the source hash")
    args = parser.parse_args()
    run = find(args.artifact, os.environ["GITHUB_REPOSITORY"], github)
    # Printed in the form a workflow step appends to its outputs.
    print(f"run-id={run or ''}")
