"""Build and reconstruct real Velopack packages; never install them on the runner."""

import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from installers import windows


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("WINDOWS_LAUNCHER"),
    "Requires the Windows launcher and pinned vpk tool",
)
class VelopackTest(unittest.TestCase):
    def test_delta_preserves_the_runtime_and_replaces_changed_files(self):
        self.check_delta("1.0.0", "1.0.1")

    def test_preview_delta_reconstructs_the_next_build(self):
        self.check_delta("0.0.41", "0.0.42")

    def check_delta(self, previous: str, current: str):
        with tempfile.TemporaryDirectory(prefix="ai-detector-velopack-") as temporary:
            root = Path(temporary)
            payload = root / "payload"
            shutil.copytree(os.environ["WINDOWS_LAUNCHER"], payload)
            (payload / "application.json").write_text("{}")
            (payload / "runtime.bin").write_bytes(os.urandom(2 * 1024 * 1024))
            (payload / "web.txt").write_text("old dashboard")
            windows(payload, previous)
            (payload / "web.txt").write_text("new dashboard")
            windows(payload, current)
            updates = root / "windows-updates"
            base = next(updates.glob(f"*{previous}*-full.nupkg"))
            target = next(updates.glob(f"*{current}*-full.nupkg"))
            delta = next(updates.glob(f"*{current}*-delta.nupkg"))
            self.assertLess(delta.stat().st_size, target.stat().st_size)
            reconstructed = root / "reconstructed.nupkg"
            subprocess.run(
                [
                    "dotnet",
                    "tool",
                    "run",
                    "vpk",
                    "--",
                    "delta",
                    "patch",
                    "--base",
                    str(base),
                    "--patch",
                    str(delta),
                    "--output",
                    str(reconstructed),
                ],
                check=True,
            )
            with (
                zipfile.ZipFile(target) as expected,
                zipfile.ZipFile(reconstructed) as actual,
            ):
                self.assertEqual(set(actual.namelist()), set(expected.namelist()))
                for name in expected.namelist():
                    self.assertEqual(actual.read(name), expected.read(name), name)
