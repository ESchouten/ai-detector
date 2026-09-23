"""Contracts shared by separately executed build tools."""

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class BuildConfigurationTest(unittest.TestCase):
    def test_velopack_cli_matches_the_runtime_package(self):
        tools = json.loads((ROOT / ".config/dotnet-tools.json").read_text())
        packages = ET.parse(ROOT / "distribution/windows/Directory.Packages.props")
        runtime = packages.find(".//PackageVersion[@Include='Velopack']")
        self.assertEqual(tools["tools"]["vpk"]["version"], runtime.attrib["Version"])

    def test_bun_types_match_the_runtime_used_to_compile(self):
        tools = json.loads((ROOT / "distribution/toolchain.json").read_text())
        package = json.loads((ROOT / "web/package.json").read_text())
        self.assertEqual(package["devDependencies"]["@types/bun"], tools["bun"])
