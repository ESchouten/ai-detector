import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

PROBE = Path(__file__).parent / "support" / "import_safety.py"
SOURCE = Path(__file__).resolve().parents[1] / "src"
PACKAGE_PATHS = (sysconfig.get_path("purelib"), sysconfig.get_path("platlib"))


@pytest.mark.parametrize(
    "statement, diagnostic",
    [
        ("Path('config.json').read_text()", "file read (config.json)"),
        ("outside.read_text()", "file read (outside.txt)"),
        ("outside.write_text('changed')", "filesystem write"),
        ("outside.unlink()", "os.remove"),
        ("outside.rename(outside.with_name('renamed.txt'))", "os.rename"),
        ("outside.with_name('created').mkdir()", "os.mkdir"),
        (
            "import socket; socket.create_connection(('127.0.0.1', 9), timeout=0.1)",
            "socket.",
        ),
        (
            "import socket; socket.getaddrinfo('example.invalid', 443)",
            "socket.getaddrinfo",
        ),
        (
            "import subprocess; subprocess.run([sys.executable, '-c', 'pass'])",
            "subprocess.Popen",
        ),
        (
            "import threading; threading.Thread(target=lambda: None).start()",
            "thread start",
        ),
        ("import _thread; _thread.start_new_thread(lambda: None, ())", "thread start"),
        (
            "import logging; logging.basicConfig(level=logging.INFO)",
            "logging configuration",
        ),
        (
            "import logging; logging.getLogger().setLevel(logging.DEBUG)",
            "logging configuration",
        ),
        (
            "import logging; logging.getLogger('new').addHandler(logging.NullHandler())",
            "logging configuration",
        ),
        # The probe keeps what it rejected, so catching its error hides nothing.
        (
            "try:\n    outside.write_text('changed')\nexcept Exception:\n    pass",
            "filesystem write",
        ),
    ],
)
def test_import_probe_rejects_side_effects(tmp_path, statement, diagnostic):
    working = tmp_path / "working"
    working.mkdir()
    (working / "config.json").write_text("{}")
    outside = tmp_path / "outside.txt"
    outside.write_text("unchanged")
    (tmp_path / "unsafe_import.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        f"outside = Path({str(outside)!r})\n{statement}\n"
    )

    process = subprocess.run(
        [sys.executable, "-S", "-B", str(PROBE), "unsafe_import"],
        cwd=working,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(tmp_path), *PACKAGE_PATHS)),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert process.returncode == 1, process.stdout + process.stderr
    assert diagnostic in process.stderr
    assert outside.read_text() == "unchanged"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "outside.txt",
        "unsafe_import.py",
        "working",
    ]


def test_import_probe_allows_normal_imports_and_distribution_metadata(tmp_path):
    (tmp_path / "ordinary_import.py").write_text(
        "from importlib.metadata import version\n"
        "from pathlib import Path\n"
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "assert version('pydantic')\n"
    )
    process = subprocess.run(
        [sys.executable, "-S", "-B", str(PROBE), "ordinary_import"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(tmp_path), *PACKAGE_PATHS)),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stdout + process.stderr


def test_domain_imports_without_any_third_party_packages(tmp_path):
    process = subprocess.run(
        [
            sys.executable,
            "-S",
            "-B",
            str(PROBE),
            "aidetector.domain.events",
            "aidetector.domain.policy",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(SOURCE)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert list(tmp_path.iterdir()) == []


def test_core_and_cli_imports_have_no_observed_side_effects(tmp_path):
    # -S excludes coverage/site startup hooks; packages remain importable through
    # explicit paths. The probe must not make exceptions for instrumentation I/O.
    process = subprocess.run(
        [
            sys.executable,
            "-S",
            "-B",
            str(PROBE),
            "aidetector.configuration",
            "aidetector.application.pipeline",
            "aidetector.application.delivery",
            "aidetector.runtime",
            "aidetector.cli",
            "aidetector.schema",
            "aidetector.adapters.inference.model_assets",
            "aidetector.adapters.inference.windows_ml",
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(SOURCE), *PACKAGE_PATHS)),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert list(tmp_path.iterdir()) == []
