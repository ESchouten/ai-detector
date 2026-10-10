"""Only this repository's own application builds may supply a reusable detector."""

import unittest

from tested_detector import find, trusted

REPOSITORY = "owner/app"


def run(identifier: int, **changes) -> dict:
    return {
        "id": identifier,
        "path": ".github/workflows/application.yml",
        "event": "push",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
        **changes,
    }


def artifact(run_id: int, created: str, expired: bool = False) -> dict:
    return {"expired": expired, "created_at": created, "workflow_run": {"id": run_id}}


class TestedDetectorTest(unittest.TestCase):
    def lookup(self, artifacts: list[dict], runs: dict[int, dict]) -> int | None:
        requests = []

        def fetch(path: str) -> dict:
            requests.append(path)
            if "/actions/artifacts?" in path:
                return {"artifacts": artifacts}
            return runs[int(path.rsplit("/", 1)[1])]

        result = find("detector-linux-x64-abc", REPOSITORY, fetch)
        self.assertIn("name=detector-linux-x64-abc", requests[0])
        return result

    def test_the_newest_build_of_this_repository_supplies_the_detector(self):
        self.assertEqual(
            self.lookup(
                [
                    artifact(1, "2026-10-01T10:00:00Z"),
                    artifact(2, "2026-10-03T10:00:00Z"),
                ],
                {1: run(1), 2: run(2, event="workflow_dispatch")},
            ),
            2,
        )
        self.assertIsNone(self.lookup([], {}))

    def test_artifacts_from_forks_other_workflows_and_expired_builds_are_ignored(self):
        untrusted = {
            "pull request": run(1, event="pull_request"),
            "fork": run(1, head_repository={"full_name": "someone/app"}),
            "deleted fork": run(1, head_repository=None),
            "other workflow": run(1, path=".github/workflows/web-tests.yml"),
        }
        for reason, candidate in untrusted.items():
            with self.subTest(reason=reason):
                self.assertFalse(
                    trusted(artifact(1, "2026-10-03T10:00:00Z"), candidate, REPOSITORY)
                )
                # An older trusted build is still found behind it.
                self.assertEqual(
                    self.lookup(
                        [
                            artifact(1, "2026-10-03T10:00:00Z"),
                            artifact(2, "2026-10-01T10:00:00Z"),
                        ],
                        {1: candidate, 2: run(2)},
                    ),
                    2,
                )
        self.assertIsNone(
            self.lookup(
                [artifact(1, "2026-10-03T10:00:00Z", expired=True)], {1: run(1)}
            )
        )


if __name__ == "__main__":
    unittest.main()
