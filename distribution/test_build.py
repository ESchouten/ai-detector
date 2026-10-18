"""Build staging and preflight operate on disposable files, never a real checkout."""

import argparse
import json
import os
import re
import subprocess
import tempfile
import tomllib
import unittest
import xml.etree.ElementTree as ET
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
        built = []
        for ref, channel in (
            ("v1.2.3", "stable"),
            ("v1.2.3-rc.0", "preview"),
            ("test-first", "preview"),
        ):
            args = argparse.Namespace(
                platform="linux-x64",
                skip_dependencies=True,
                version="1.2.3",
                ref=ref,
                channel=channel,
            )
            with patch.object(
                build,
                "run",
                side_effect=lambda *_a, **_k: built.append(self.version.read_text()),
            ):
                build.build_web(args)
        self.assertEqual(
            built,
            [
                'export const version = "1.2.3";\nexport const preview = false;\n',
                'export const version = "1.2.3-rc.0";\nexport const preview = true;\n',
                'export const version = "test-first";\nexport const preview = true;\n',
            ],
        )
        self.assertEqual(self.version.read_bytes(), b"original version\r\n")

    def test_failure_restores_source_metadata(self):
        args = argparse.Namespace(
            platform="linux-x64",
            skip_dependencies=True,
            version="1.2.3",
            ref="main",
            channel="stable",
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

    def test_preflight_names_missing_tools(self):
        args = argparse.Namespace(stage="web", version="1.2.3")
        with (
            patch.object(build, "native_platform", return_value="linux-x64"),
            patch.object(
                build.shutil,
                "which",
                side_effect=lambda tool: None if tool == "bun" else tool,
            ),
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
            path.write_text(f"TYPE = {kind}\nREF_NAME = 'test-1'\n")
        if os.name != "nt":
            # A Mac bundle reaches the same file through a symbolic link.
            (folder / "link").mkdir()
            (folder / "link/aidetector").symlink_to(
                frozen.parent, target_is_directory=True
            )

        build.stamp_detector(folder, "test-2")

        # Each copy keeps its own backend; only the reference changes.
        self.assertEqual(
            frozen.read_text(), "TYPE = 'windowsml'\nREF_NAME = 'test-2'\n"
        )
        self.assertEqual(nvidia.read_text(), "TYPE = 'cuda'\nREF_NAME = 'test-2'\n")

    def test_detector_dependency_selection_matches_the_platform(self):
        version = self.root / "detector/src/aidetector/version.py"
        version.parent.mkdir(parents=True)
        version.write_text("original version\n")
        (self.root / "detector/.python-version").write_text("3.12.14\n")
        args = build.parse_arguments(["detector"])
        args.platform = "linux-x64"
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


class BuildConfigurationTest(unittest.TestCase):
    """Contracts shared by separately executed build tools."""

    def test_velopack_cli_matches_the_runtime_package(self):
        tools = json.loads(
            (build.ROOT / "distribution/windows/dotnet-tools.json").read_text()
        )
        packages = ET.parse(
            build.ROOT / "distribution/windows/Directory.Packages.props"
        )
        runtime = packages.find(".//PackageVersion[@Include='Velopack']")
        self.assertEqual(tools["tools"]["vpk"]["version"], runtime.attrib["Version"])

    def test_bun_types_match_the_runtime_used_to_compile(self):
        tools = json.loads((build.ROOT / "distribution/toolchain.json").read_text())
        package = json.loads((build.ROOT / "web/package.json").read_text())
        self.assertEqual(package["devDependencies"]["@types/bun"], tools["bun"])

    def test_the_container_uses_the_pinned_uv_and_node(self):
        dockerfile = (build.ROOT / "Dockerfile").read_text()
        project = tomllib.loads((build.ROOT / "detector/pyproject.toml").read_text())
        uv = re.search(r"ghcr\.io/astral-sh/uv:([\d.]+)", dockerfile)
        self.assertIsNotNone(uv)
        self.assertEqual(f"=={uv[1]}", project["tool"]["uv"]["required-version"])
        tools = json.loads((build.ROOT / "distribution/toolchain.json").read_text())
        self.assertRegex(dockerfile, rf"FROM node:{tools['node']}-")
