"""Build staging and preflight operate on disposable files, never a real checkout."""

import argparse
import os
import subprocess
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

import build


class BuildTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ai-build-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(patch.object(build, "ROOT", self.root))
        self.version = self.root / "web/src/lib/version.ts"
        self.version.parent.mkdir(parents=True)
        self.version.write_bytes(b"original version\r\n")

    def test_the_web_build_knows_its_version_and_whether_it_is_a_test_build(self):
        args = argparse.Namespace(
            platform="linux-x64",
            skip_dependencies=True,
            version="1.2.3",
        )
        built = []
        for channel in ("stable", "preview"):
            with (
                patch.dict(
                    os.environ,
                    {"GITHUB_REF_NAME": "app/v1.2.3", "UPDATE_CHANNEL": channel},
                ),
                patch.object(
                    build,
                    "run",
                    side_effect=lambda *_a, **_k: built.append(
                        self.version.read_text()
                    ),
                ),
            ):
                build.build_web(args)
        self.assertEqual(
            built,
            [
                'export const version = "app/v1.2.3";\nexport const preview = false;\n',
                'export const version = "app/v1.2.3";\nexport const preview = true;\n',
            ],
        )
        self.assertEqual(self.version.read_bytes(), b"original version\r\n")

    def test_failure_restores_source_metadata(self):
        args = argparse.Namespace(
            platform="linux-x64",
            skip_dependencies=True,
            version="1.2.3",
        )
        with patch.object(
            build, "run", side_effect=subprocess.CalledProcessError(1, "pnpm build")
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                build.build_web(args)
        self.assertEqual(self.version.read_bytes(), b"original version\r\n")

    def test_platform_selection_checks_the_machine_architecture(self):
        for system, machine, expected in (
            ("Darwin", "arm64", "macos-arm64"),
            ("Windows", "AMD64", "windows-x64"),
            ("Linux", "x86_64", "linux-x64"),
        ):
            with (
                self.subTest(system=system),
                patch.object(build.host, "system", return_value=system),
                patch.object(build.host, "machine", return_value=machine),
            ):
                self.assertEqual(build.native_platform(), expected)
        for system, machine in (
            ("Darwin", "x86_64"),
            ("Linux", "aarch64"),
            ("Windows", "ARM64"),
        ):
            with (
                self.subTest(system=system),
                patch.object(build.host, "system", return_value=system),
                patch.object(build.host, "machine", return_value=machine),
            ):
                with self.assertRaisesRegex(ValueError, "Unsupported build machine"):
                    build.native_platform()

    def test_preflight_rejects_cross_builds_and_names_missing_tools(self):
        args = argparse.Namespace(stage="web", platform="windows-x64", version="1.2.3")
        with patch.object(build, "native_platform", return_value="linux-x64"):
            with self.assertRaisesRegex(ValueError, "matching machine"):
                build.preflight(args)
            args.platform = None
            with patch.object(
                build.shutil,
                "which",
                side_effect=lambda tool: None if tool == "bun" else tool,
            ):
                with self.assertRaisesRegex(
                    ValueError, "Install these build tools first: bun"
                ):
                    build.preflight(args)

    def test_preview_rejects_occupied_output_and_missing_detector(self):
        output = self.root / "output"
        output.mkdir()
        existing = output / "previous.zip"
        existing.write_bytes(b"previous build")
        args = argparse.Namespace(output=output, detector=None, platform="linux-x64")
        with self.assertRaisesRegex(ValueError, "fresh output directory"):
            build.validate_preview(args)
        self.assertEqual(existing.read_bytes(), b"previous build")
        args.output = self.root / "fresh"
        args.detector = self.root / "missing-detector"
        with self.assertRaisesRegex(ValueError, "frozen detector is missing"):
            build.validate_preview(args)
        self.assertFalse(args.output.exists())

    def test_relative_build_paths_keep_the_callers_directory(self):
        detector = self.root / "frozen detector"
        detector.mkdir()
        (detector / "aidetector").touch()
        with (
            chdir(self.root),
            patch.object(build, "native_platform", return_value="linux-x64"),
            patch.object(build.shutil, "which", side_effect=lambda tool: tool),
        ):
            args = build.parse_arguments(
                ["all", "--output", "local preview", "--detector", "frozen detector"]
            )
            build.preflight(args)
            self.assertEqual(args.output, self.root.resolve() / "local preview")
            self.assertEqual(args.detector, detector.resolve())
            launcher = build.parse_arguments(["launcher", "--output", "local launcher"])
            build.preflight(launcher)
            self.assertEqual(launcher.output, self.root.resolve() / "local launcher")
        self.assertFalse(args.output.exists(), "Preflight must not create the output")

    def test_a_reused_detector_takes_the_reference_of_the_new_build(self):
        folder = self.root / "aidetector"
        frozen = folder / "_internal/aidetector/version.py"
        nvidia = folder / "nvidia-runtime/app/aidetector/version.py"
        for path, kind in ((frozen, "'windowsml'"), (nvidia, "'cuda'")):
            path.parent.mkdir(parents=True)
            path.write_text(f"TYPE = {kind}\nREF_NAME = 'app/test-1'\n")
        if os.name != "nt":
            # A Mac bundle reaches the same file through a symbolic link.
            (folder / "link").mkdir()
            (folder / "link/aidetector").symlink_to(
                frozen.parent, target_is_directory=True
            )

        build.stamp_detector(folder, "app/test-2")

        # Each copy keeps its own backend; only the reference changes.
        self.assertEqual(
            frozen.read_text(), "TYPE = 'windowsml'\nREF_NAME = 'app/test-2'\n"
        )
        self.assertEqual(nvidia.read_text(), "TYPE = 'cuda'\nREF_NAME = 'app/test-2'\n")
        scope: dict = {}
        exec(frozen.read_text(), scope)
        self.assertEqual(scope["REF_NAME"], "app/test-2")

        frozen.write_text("TYPE = 'default'\n")
        with self.assertRaisesRegex(ValueError, "Unexpected version file"):
            build.stamp_detector(folder, "app/test-3")
        with self.assertRaisesRegex(ValueError, "no version file"):
            build.stamp_detector(self.root / "missing", "app/test-3")

    def test_freezing_keeps_the_build_reference_outside_the_archive(self):
        hook = (build.HOOKS / "hook-aidetector.py").read_text()
        scope: dict = {}
        exec(hook, scope)
        self.assertEqual(scope["module_collection_mode"], {"aidetector.version": "py"})

    def test_detector_dependency_selection_matches_the_platform(self):
        version = self.root / "detector/src/aidetector/version.py"
        version.parent.mkdir(parents=True)
        version.write_text("original version\n")
        (self.root / "detector/.python-version").write_text("3.12.14\n")
        args = build.parse_arguments(["detector", "--platform", "linux-x64"])
        with patch.object(build, "run") as run:
            result = build.build_detector(args)
        install, freeze = (call.args for call in run.call_args_list)
        self.assertEqual(install[install.index("--python") + 1], "3.12.14")
        self.assertEqual(install[install.index("--extra") + 1], "default")
        self.assertEqual(
            freeze[freeze.index("--specpath") + 1], self.root / "detector/build"
        )
        self.assertEqual(result, self.root / "detector/dist/aidetector")
        self.assertEqual(version.read_text(), "original version\n")
