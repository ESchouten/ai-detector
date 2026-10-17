import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[1]
SOURCE = DIRECTORY / "src" / "aidetector"


def test_coverage_measures_real_cli_children_without_temporary_package_copies(tmp_path):
    snapshot = tmp_path / "snapshot"
    package = snapshot / "aidetector"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("SNAPSHOT = True\n")
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, '-c', "
        "'import aidetector; assert aidetector.SNAPSHOT'], "
        "cwd=sys.argv[1], check=True)\n"
        "subprocess.run([sys.executable, '-m', 'aidetector', '--version'], "
        "cwd=sys.argv[2], check=True)\n"
    )
    data_file = str(tmp_path / ".coverage")

    def coverage(command, *arguments):
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "coverage",
                command,
                "--rcfile",
                str(DIRECTORY / "pyproject.toml"),
                "--data-file",
                data_file,
                *map(str, arguments),
            ],
            cwd=DIRECTORY,
            env={**os.environ, "PYTHONPATH": str(SOURCE.parent)},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        return process

    assert "default" in coverage("run", driver, snapshot, tmp_path).stdout
    shutil.rmtree(snapshot)
    coverage("combine")
    report = tmp_path / "coverage.json"
    coverage("json", "-o", report)

    files = {
        (DIRECTORY / filename).resolve(): details
        for filename, details in json.loads(report.read_text())["files"].items()
    }
    assert all(path.is_relative_to(SOURCE) for path in files)
    assert files[SOURCE / "cli.py"]["executed_lines"]
