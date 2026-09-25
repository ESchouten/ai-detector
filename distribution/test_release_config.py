"""Stable and preview builds publish to separate, immutable release locations."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from release_config import release_config
from updates import newer_than


class ReleaseConfigTest(unittest.TestCase):
    def config(self, ref, run_number=42, run_id=123456):
        return release_config(ref, "example/detector", run_number, run_id)

    def test_stable_releases_keep_the_existing_feed(self):
        release = self.config("refs/tags/app/v1.2.3")
        self.assertEqual(release["version"], "1.2.3")
        self.assertEqual(release["channel"], "stable")
        self.assertEqual(release["feed_tag"], "app-updates")
        self.assertEqual(
            release["release_url"],
            "https://github.com/example/detector/releases/download/app%2Fv1.2.3",
        )

    def test_preview_tags_have_increasing_versions_and_a_separate_feed(self):
        first = self.config("refs/tags/app/test-first")
        second = self.config("refs/tags/app/test-second", run_number=43)
        newer_than(second["version"], [first["version"]])
        with self.assertRaises(ValueError):
            newer_than(first["version"], [second["version"]])
        self.assertEqual(first["version"], "0.0.42")
        self.assertEqual(second["version"], "0.0.43")
        self.assertEqual(first["channel"], "preview")
        self.assertEqual(first["feed_tag"], "app-preview-updates")
        self.assertEqual(first["feed_url"], second["feed_url"])
        self.assertNotEqual(
            first["feed_url"], self.config("refs/tags/app/v1.2.3")["feed_url"]
        )
        self.assertTrue(first["release_url"].endswith("app%2Ftest-first"))

    def test_manual_branch_runs_use_an_immutable_preview_tag(self):
        release = self.config("refs/heads/rework-stars")
        self.assertEqual(release["tag"], "app/test-run-123456")
        self.assertEqual(release["channel"], "preview")
        self.assertEqual(release["version"], "0.0.42")
        self.assertTrue(release["release_url"].endswith("app%2Ftest-run-123456"))
        # Retrying a failed run keeps its identity rather than making another release.
        self.assertEqual(release, self.config("refs/heads/rework-stars"))

    def test_unrelated_refs_and_non_numeric_stable_versions_are_rejected(self):
        for ref in (
            "refs/tags/web/v1.0.0",
            "refs/pull/10/merge",
            "refs/tags/app/v1.2.3-rc.1",
        ):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.config(ref)

    def test_workflow_receives_the_same_configuration_as_the_packaging_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "outputs"
            subprocess.run(
                [sys.executable, str(Path(__file__).with_name("release_config.py"))],
                env={
                    **os.environ,
                    "GITHUB_REF": "refs/tags/app/test-first",
                    "GITHUB_REPOSITORY": "example/detector",
                    "GITHUB_RUN_NUMBER": "42",
                    "GITHUB_RUN_ID": "123456",
                    "GITHUB_OUTPUT": str(output),
                },
                check=True,
            )
            self.assertEqual(
                dict(line.split("=", 1) for line in output.read_text().splitlines()),
                self.config("refs/tags/app/test-first"),
            )
