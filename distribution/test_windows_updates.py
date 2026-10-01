"""Build real Velopack full updates; never install them on the runner."""

import os
import shutil
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
    def test_full_update_preserves_the_runtime_and_replaces_changed_files(self):
        self.check_update("1.0.0", "1.0.1")

    def test_preview_publishes_the_next_full_build(self):
        self.check_update("0.0.41", "0.0.42")

    def check_update(self, previous: str, current: str):
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
            target = next(updates.glob(f"*{current}*-full.nupkg"))
            self.assertEqual(list(updates.glob("*-delta.nupkg")), [])
            with zipfile.ZipFile(target) as package:
                for name in ("runtime.bin", "web.txt"):
                    entry = next(
                        entry
                        for entry in package.namelist()
                        if entry.endswith(f"/{name}")
                    )
                    self.assertEqual(package.read(entry), (payload / name).read_bytes())
