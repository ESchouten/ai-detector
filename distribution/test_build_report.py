"""Release reports reflect executed and skipped GitHub jobs."""

import unittest

from build_report import summarize


class BuildReportTest(unittest.TestCase):
    def test_skipped_job_with_reversed_timestamps_has_no_duration(self):
        report = summarize(
            [
                {
                    "name": "Domain mutation testing",
                    "conclusion": "skipped",
                    "started_at": "2026-10-01T09:27:29Z",
                    "completed_at": "2026-10-01T09:27:28Z",
                    "html_url": "https://example.test/jobs/1",
                }
            ],
            [],
        )
        self.assertIn("| skipped | — |", report)

    def test_completed_job_reports_duration_and_only_installer_artifacts(self):
        report = summarize(
            [
                {
                    "name": "Linux installer",
                    "conclusion": "success",
                    "started_at": "2026-10-01T09:27:29Z",
                    "completed_at": "2026-10-01T09:28:31Z",
                    "html_url": "https://example.test/jobs/2",
                }
            ],
            [
                {"name": "AI-Detector-linux-x64", "size_in_bytes": 2**20},
                {"name": "native-build-linux-x64", "size_in_bytes": 2**30},
            ],
        )
        self.assertIn("| success | 1m 02s |", report)
        self.assertIn("| AI-Detector-linux-x64 | 1.0 MiB |", report)
        self.assertNotIn("native-build", report)
