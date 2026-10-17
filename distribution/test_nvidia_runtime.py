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
        project = tomllib.loads((ROOT / "detector/pyproject.toml").read_text())
        pinned = project["tool"]["uv"]["required-version"].removeprefix("==")
        version = subprocess.check_output([uv, "--version"], text=True)
        if version.split()[1] != pinned:
            self.skipTest(f"Requires uv {pinned}, matching the shipped bootstrap")
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
            self.assertFalse(
                list(folder.rglob("*.dll")), "GPU DLLs must stay out of the installer"
            )
            for cuda, local, onnxruntime in (
                # ONNX Runtime is built with CUDA 13 from 1.27 on. From 1.21 on, its
                # CUDA 12 builds need 12.8, more than PyTorch's CUDA 12.6 brings.
                (13, "+cu132", lambda version: version >= (1, 27)),
                (12, "+cu126", lambda version: version[:2] == (1, 20)),
            ):
                with self.subTest(cuda=cuda):
                    self.assert_windows_wheels(
                        folder, temporary, python, abi, cuda, local, onnxruntime
                    )
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

    def assert_windows_wheels(
        self, folder, temporary, python, abi, cuda, local, onnxruntime
    ):
        uv = shutil.which("uv")
        lock = folder / f"pylock.cuda{cuda}.toml"
        packages = tomllib.loads(lock.read_text())["packages"]
        torch = next(item for item in packages if item["version"].endswith(local))
        self.assertEqual(torch["name"], "torch")
        wheels = [
            item for item in torch["wheels"] if f"{abi}-{abi}-win_amd64" in item["url"]
        ]
        self.assertEqual(len(wheels), 1)
        self.assertEqual(len(wheels[0]["hashes"]["sha256"]), 64)
        runtime = next(item for item in packages if item["name"] == "onnxruntime-gpu")
        self.assertTrue(onnxruntime(tuple(map(int, runtime["version"].split(".")))))
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
                str(Path(temporary) / f"environment-{cuda}"),
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
        self.assertIn(f"torch=={torch['version']}", result.stderr)
        self.assertIn(f"onnxruntime-gpu=={runtime['version']}", result.stderr)
        tensor_rt = f"tensorrt-cu{cuda}"
        tensor_rt_lock = folder / f"pylock.tensorrt-cuda{cuda}.toml"
        tensor_rt_packages = tomllib.loads(tensor_rt_lock.read_text())["packages"]
        self.assertEqual(
            {package["name"] for package in tensor_rt_packages},
            {tensor_rt, f"{tensor_rt}-bindings", f"{tensor_rt}-libs"},
        )
        self.assertTrue(
            all(package["version"] == "10.16.1.11" for package in tensor_rt_packages)
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
                str(Path(temporary) / f"environment-{cuda}"),
                "--only-binary",
                ":all:",
                "--no-binary",
                tensor_rt,
                "--require-hashes",
                "-r",
                str(tensor_rt_lock),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"{tensor_rt}-libs==10.16.1.11", result.stderr)
