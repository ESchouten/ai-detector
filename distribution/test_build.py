"""Build staging and preflight operate on disposable files, never a real checkout."""

import argparse
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
        self.assets = self.root / "web/static/_internal"
        self.encoder = self.root / "ffmpeg"
        self.encoder.write_bytes(b"encoder")
        self.enterContext(patch.object(build, "ffmpeg_path", return_value=self.encoder))

    def test_standalone_assets_do_not_leak_into_the_next_build(self):
        args = argparse.Namespace(
            platform="linux-x64",
            standalone_web=True,
            skip_dependencies=True,
            version="1.2.3",
        )

        def compile_stage(*_args, **_kwargs):
            self.assertEqual(self.assets.exists(), args.standalone_web)
            if args.standalone_web:
                self.assertEqual((self.assets / "ffmpeg").read_bytes(), b"encoder")

        with patch.object(build, "run", side_effect=compile_stage):
            build.build_web(args)
            self.assertFalse(self.assets.exists())
            args.standalone_web = False
            build.build_web(args)
        self.assertEqual(self.version.read_bytes(), b"original version\r\n")

    def test_failure_restores_existing_assets_and_source_metadata(self):
        self.assets.mkdir(parents=True)
        original = self.assets / "ffmpeg"
        original.write_bytes(b"previous developer asset")
        args = argparse.Namespace(
            platform="linux-x64",
            standalone_web=True,
            skip_dependencies=True,
            version="1.2.3",
        )
        with patch.object(
            build, "run", side_effect=subprocess.CalledProcessError(1, "pnpm build")
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                build.build_web(args)
        self.assertEqual(original.read_bytes(), b"previous developer asset")
        self.assertEqual(self.version.read_bytes(), b"original version\r\n")
        with build.staged_ffmpeg(False, ""):
            self.assertFalse(
                self.assets.exists(),
                "A combined build must exclude stale standalone assets",
            )
        self.assertEqual(original.read_bytes(), b"previous developer asset")

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

    def test_detector_rejects_incompatible_or_unprepared_backends(self):
        for arguments, message in (
            (["--type", "cuda"], "prepared GPU dependency environment"),
            (["--type", "tensorrt"], "prepared GPU dependency environment"),
            (["--type", "windowsml"], "Windows ML requires a Windows"),
            (["--name", "../outside"], "filename, not a path"),
            (["--name", "nested\\outside"], "filename, not a path"),
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(build, "native_platform", return_value="linux-x64"),
            ):
                args = build.parse_arguments(["detector", *arguments])
                with self.assertRaisesRegex(ValueError, message):
                    build.preflight(args)
        with (
            patch.object(build, "native_platform", return_value="linux-x64"),
            patch.object(build.shutil, "which", side_effect=lambda tool: tool),
        ):
            build.preflight(
                build.parse_arguments(
                    ["detector", "--type", "cuda", "--skip-dependencies"]
                )
            )

    def test_detector_dependency_selection_matches_the_requested_backend(self):
        version = self.root / "detector/src/aidetector/version.py"
        version.parent.mkdir(parents=True)
        version.write_text("original version\n")
        toolchain = self.root / "distribution/toolchain.json"
        toolchain.parent.mkdir()
        toolchain.write_text('{"python": "3.11"}')
        args = build.parse_arguments(
            ["detector", "--platform", "windows-x64", "--type", "default"]
        )
        with patch.object(build, "run") as run:
            result = build.build_detector(args)
        install, freeze = (call.args for call in run.call_args_list)
        self.assertEqual(install[install.index("--extra") + 1], "default")
        self.assertEqual(
            freeze[freeze.index("--specpath") + 1], self.root / "detector/build"
        )
        self.assertEqual(result, self.root / "detector/dist/aidetector")
        self.assertEqual(version.read_text(), "original version\n")
