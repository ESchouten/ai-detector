"""Check the real exported GPU dependency contract without downloading GPU binaries."""

import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from nvidia_runtime import stage_nvidia_runtime

ROOT = Path(__file__).resolve().parent.parent


class NvidiaRuntimeTest(unittest.TestCase):
    def test_staged_runtime_contains_current_code_and_resolves_hashed_windows_wheels(
        self,
    ):
        uv = shutil.which("uv")
        if uv is None:
            self.skipTest("Requires the repository's pinned uv executable")
        version = subprocess.check_output([uv, "--version"], text=True)
        if version.split()[1] != "0.12.19":
            self.skipTest("Requires uv 0.12.19, matching the shipped bootstrap")
        python = (ROOT / "detector/.python-version").read_text().strip()
        abi = "cp" + "".join(python.split(".")[:2])
        with tempfile.TemporaryDirectory(prefix="nvidia stage ") as temporary:
            folder = Path(temporary) / "payload"
            stage_nvidia_runtime(ROOT, folder, "test-nvidia")
            self.assertEqual((folder / "uv.exe").read_bytes(), Path(uv).read_bytes())
            self.assertTrue((folder / "uv-LICENSE-MIT").is_file())
            self.assertTrue((folder / "uv-LICENSE-APACHE").is_file())
            self.assertEqual(
                json.loads((folder / "runtime.json").read_text())["python"], python
            )
            source = ROOT / "detector/src/aidetector"
            for file in source.rglob("*.py"):
                copied = folder / "app/aidetector" / file.relative_to(source)
                if file.name != "version.py":
                    self.assertEqual(file.read_bytes(), copied.read_bytes())
            self.assertIn(
                "TYPE = 'cuda'", (folder / "app/aidetector/version.py").read_text()
            )
            lock = folder / "pylock.toml"
            packages = tomllib.loads(lock.read_text())["packages"]
            self.assertNotIn("cutie", {package["name"] for package in packages})
            torch = next(item for item in packages if item["version"] == "2.11.0+cu128")
            self.assertEqual(torch["name"], "torch")
            wheels = [
                item
                for item in torch["wheels"]
                if f"{abi}-{abi}-win_amd64" in item["url"]
            ]
            self.assertEqual(len(wheels), 1)
            self.assertEqual(len(wheels[0]["hashes"]["sha256"]), 64)
            self.assertFalse(
                list(folder.rglob("*.dll")), "GPU DLLs must stay out of the installer"
            )
            result = subprocess.run(
                [
                    uv,
                    "pip",
                    "sync",
                    "--dry-run",
                    "--python-version",
                    python,
                    "--python-platform",
                    "x86_64-pc-windows-msvc",
                    "--target",
                    str(Path(temporary) / "environment"),
                    "--only-binary",
                    ":all:",
                    "--require-hashes",
                    str(lock),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("torch==2.11.0+cu128", result.stderr)
            self.assertIn("onnxruntime-gpu==1.26.", result.stderr)
            tensor_rt_lock = folder / "pylock.tensorrt.toml"
            tensor_rt_packages = tomllib.loads(tensor_rt_lock.read_text())["packages"]
            self.assertEqual(
                {package["name"] for package in tensor_rt_packages},
                {"tensorrt-cu12", "tensorrt-cu12-bindings", "tensorrt-cu12-libs"},
            )
            self.assertTrue(
                all(
                    package["version"] == "10.16.1.11" for package in tensor_rt_packages
                )
            )
            result = subprocess.run(
                [
                    uv,
                    "pip",
                    "install",
                    "--dry-run",
                    "--python-version",
                    python,
                    "--python-platform",
                    "x86_64-pc-windows-msvc",
                    "--target",
                    str(Path(temporary) / "environment"),
                    "--only-binary",
                    ":all:",
                    "--no-binary",
                    "tensorrt-cu12",
                    "--require-hashes",
                    "-r",
                    str(tensor_rt_lock),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("tensorrt-cu12-libs==10.16.1.11", result.stderr)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "compileall",
                    "-q",
                    str(folder / "app"),
                    str(folder / "run.py"),
                ],
                check=True,
            )
