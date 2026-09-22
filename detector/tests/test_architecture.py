import logging
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import grimp
import pytest

DIRECTORY = Path(__file__).resolve().parents[1]
PACKAGE = DIRECTORY / "src" / "aidetector"
CONTRACTS = DIRECTORY / ".importlinter"
PROBE = DIRECTORY / "tests" / "support" / "import_safety.py"


@pytest.fixture(scope="module")
def import_graph():
    return grimp.build_graph(
        "aidetector",
        include_external_packages=True,
        exclude_type_checking_imports=False,
        cache_dir=None,
    )


def run_contracts(source_root, working_directory):
    # Import Linter configures logging. Its CLI must not change the test process.
    return subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from importlinter.cli import lint_imports; "
            "import sys; "
            "raise SystemExit(lint_imports(sys.argv[1], no_cache=True, no_logo=True))",
            str(CONTRACTS),
        ],
        cwd=working_directory,
        env={**os.environ, "PYTHONPATH": str(source_root)},
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_declared_architecture_contracts_preserve_parent_logging(tmp_path, caplog):
    logger = logging.getLogger("aidetector.architecture-check")
    logger.warning("Before architecture check")
    process = run_contracts(PACKAGE.parent, tmp_path)
    logger.warning("After architecture check")

    assert process.returncode == 0, process.stdout + process.stderr
    assert caplog.messages == ["Before architecture check", "After architecture check"]


def assert_all_source_modules_discovered(import_graph, package):
    source_modules = set()
    for path in package.rglob("*.py"):
        parts = path.relative_to(package).with_suffix("").parts
        if path.name == "__init__.py":
            parts = parts[:-1]
        source_modules.add(".".join((package.name, *parts)))
    discovered = {
        module
        for module in import_graph.modules
        if module == package.name or module.startswith(package.name + ".")
    }
    assert source_modules == discovered, (
        "Architecture graph must cover every source module. "
        f"Missing: {sorted(source_modules - discovered)}; "
        f"unexpected: {sorted(discovered - source_modules)}. "
        "Check that each package directory contains __init__.py."
    )


def test_architecture_graph_covers_every_source_module(import_graph):
    assert_all_source_modules_discovered(import_graph, PACKAGE)


def test_missing_package_initializer_cannot_hide_a_boundary_violation(tmp_path):
    copy = tmp_path / "aidetector"
    shutil.copytree(PACKAGE, copy, ignore=shutil.ignore_patterns("__pycache__"))
    new_package = copy / "domain" / "new_rules"
    new_package.mkdir()
    (new_package / "rule.py").write_text(
        "from aidetector.adapters.exporters.disk import DiskExporter\n"
    )

    def check_discovery():
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "import grimp, runpy, sys; from pathlib import Path; "
                "checks = runpy.run_path(sys.argv[1]); "
                "graph = grimp.build_graph('aidetector', "
                "include_external_packages=True, "
                "exclude_type_checking_imports=False, cache_dir=None); "
                "checks['assert_all_source_modules_discovered']"
                "(graph, Path(sys.argv[2]))",
                str(Path(__file__).resolve()),
                str(copy),
            ],
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": str(tmp_path)},
            capture_output=True,
            text=True,
            timeout=20,
        )

    process = check_discovery()
    assert process.returncode == 1, process.stdout + process.stderr
    assert "Missing: ['aidetector.domain.new_rules.rule']" in process.stderr

    (new_package / "__init__.py").touch()
    process = check_discovery()
    assert process.returncode == 0, process.stdout + process.stderr
    process = run_contracts(tmp_path, tmp_path)
    assert process.returncode == 1, process.stdout + process.stderr
    assert (
        "Dependencies point toward use cases and domain rules BROKEN" in process.stdout
    )


def assert_core_dependencies(import_graph):
    allowed = {
        "domain": {
            "__future__",
            "dataclasses",
            "datetime",
            "enum",
            "typing",
            "collections",
            "aidetector.domain",
        },
        "application": {
            "__future__",
            "dataclasses",
            "datetime",
            "typing",
            "collections",
            "logging",
            "aidetector.domain",
            "aidetector.application",
        },
    }
    for layer, roots in allowed.items():
        for module in import_graph.modules:
            if module == f"aidetector.{layer}" or module.startswith(
                f"aidetector.{layer}."
            ):
                for dependency in import_graph.find_modules_directly_imported_by(
                    module
                ):
                    # Image annotations deliberately retain this one static
                    # representation dependency. The -S probe forbids loading it.
                    if module == "aidetector.domain.models" and dependency == "numpy":
                        continue
                    assert any(
                        dependency == root or dependency.startswith(root + ".")
                        for root in roots
                    ), f"{module} must not import {dependency}"


def assert_no_internal_cycles(import_graph):
    # Import Linter checks sibling packages. Reverse chains also catch a package
    # initializer and its descendant importing each other.
    for module in import_graph.modules:
        if module == "aidetector" or module.startswith("aidetector."):
            for dependency in import_graph.find_modules_directly_imported_by(module):
                if dependency != module and dependency.startswith("aidetector"):
                    reverse = import_graph.find_shortest_chain(dependency, module)
                    assert reverse is None, (module, *reverse)


def test_domain_and_application_have_only_their_explicit_dependencies(import_graph):
    assert_core_dependencies(import_graph)


def test_internal_cycles_including_package_initializers(import_graph):
    assert_no_internal_cycles(import_graph)


@pytest.mark.parametrize(
    "module, dependency",
    [("aidetector.domain.models", "torch"), ("aidetector.application.ports", "socket")],
)
def test_core_dependency_guard_rejects_external_frameworks_and_io(module, dependency):
    graph = grimp.ImportGraph()
    graph.add_module(module)
    graph.add_module(dependency)
    graph.add_import(importer=module, imported=dependency)
    with pytest.raises(AssertionError, match=f"must not import {dependency}"):
        assert_core_dependencies(graph)


def test_cycle_guard_also_rejects_a_package_importing_its_child_and_back():
    graph = grimp.ImportGraph()
    graph.add_module("aidetector.domain")
    graph.add_module("aidetector.domain.models")
    graph.add_import(importer="aidetector.domain", imported="aidetector.domain.models")
    assert_no_internal_cycles(graph)
    graph.add_import(importer="aidetector.domain.models", imported="aidetector.domain")
    with pytest.raises(AssertionError):
        assert_no_internal_cycles(graph)


@pytest.mark.parametrize(
    "module, statement, contract",
    [
        (
            "domain/models.py",
            "def deferred():\n    import aidetector.adapters.exporters.disk\n",
            "Dependencies point",
        ),
        (
            "application/pipeline.py",
            "from aidetector import configuration\n",
            "Use cases and runtime",
        ),
        (
            "runtime.py",
            "from aidetector.adapters.sources import files\n",
            "Dependencies point",
        ),
        (
            "configuration.py",
            "from aidetector.domain import models\n",
            "Dependencies point",
        ),
        (
            "adapters/http.py",
            "from aidetector import bootstrap\n",
            "Dependencies point",
        ),
        (
            "adapters/http.py",
            "from aidetector import version\n",
            "Adapters receive build settings",
        ),
        (
            "domain/models.py",
            "from aidetector.domain import events\n",
            "Packages and their descendants",
        ),
        (
            "domain/models.py",
            "if TYPE_CHECKING:\n"
            "    from aidetector.adapters.exporters.disk import DiskExporter\n",
            "Dependencies point",
        ),
        (
            "application/pipeline.py",
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n    from aidetector.configuration import Config\n",
            "Use cases and runtime",
        ),
        (
            "domain/models.py",
            "if TYPE_CHECKING:\n    from aidetector.domain.events import EventAssembler\n",
            "Packages and their descendants",
        ),
        (
            "adapters/exporters/disk.py",
            "from aidetector.adapters.sources import files\n",
            "Source, inference and exporter adapters",
        ),
        (
            "adapters/exporters/webhook.py",
            "def deferred():\n"
            "    from aidetector.adapters.inference.yolo import YoloDetector\n",
            "Source, inference and exporter adapters",
        ),
        (
            "adapters/sources/files.py",
            "from aidetector.adapters.exporters.disk import DiskExporter\n",
            "Source, inference and exporter adapters",
        ),
        (
            "adapters/sources/streams.py",
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from aidetector.adapters.inference.yolo import YoloDetector\n",
            "Source, inference and exporter adapters",
        ),
        (
            "adapters/inference/yolo.py",
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from aidetector.adapters.exporters.telegram import TelegramExporter\n",
            "Source, inference and exporter adapters",
        ),
        (
            "adapters/inference/onnx.py",
            "def deferred():\n    import aidetector.adapters.sources.streams\n",
            "Source, inference and exporter adapters",
        ),
        (
            "adapters/media/images.py",
            "from aidetector.adapters.inference import yolo\n",
            "Source, inference and exporter adapters",
        ),
    ],
)
def test_contracts_reject_real_boundary_violations(
    tmp_path, module, statement, contract
):
    copy = tmp_path / "aidetector"
    shutil.copytree(PACKAGE, copy, ignore=shutil.ignore_patterns("__pycache__"))
    with (copy / module).open("a") as output:
        output.write("\n" + statement)
    process = run_contracts(tmp_path, tmp_path)
    assert process.returncode == 1, process.stdout + process.stderr
    assert any(
        line.startswith(contract) and line.endswith("BROKEN")
        for line in process.stdout.splitlines()
    ), process.stdout


@pytest.mark.parametrize(
    "module, dependency",
    [
        ("domain/models.py", "torch"),
        ("application/ports.py", "cv2"),
        ("domain/policy.py", "numpy"),
    ],
)
def test_core_dependencies_include_real_annotation_imports(
    tmp_path, module, dependency
):
    copy = tmp_path / "aidetector"
    shutil.copytree(PACKAGE, copy, ignore=shutil.ignore_patterns("__pycache__"))
    with (copy / module).open("a") as output:
        output.write(
            f"\nfrom typing import TYPE_CHECKING\n"
            f"if TYPE_CHECKING:\n    import {dependency}\n"
        )
    # Inspect the temporary package without importing its application code or
    # reusing modules already loaded by pytest in this process.
    process = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import grimp, runpy, sys; "
            "checks = runpy.run_path(sys.argv[1]); "
            "graph = grimp.build_graph('aidetector', include_external_packages=True, "
            "exclude_type_checking_imports=False, cache_dir=None); "
            "checks['assert_core_dependencies'](graph)",
            str(Path(__file__).resolve()),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 1, process.stdout + process.stderr
    assert f"must not import {dependency}" in process.stderr


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
        env={**os.environ, "PYTHONPATH": str(PACKAGE.parent)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert list(tmp_path.iterdir()) == []


def test_core_and_cli_imports_have_no_observed_side_effects(tmp_path):
    # -S excludes coverage/site startup hooks; packages remain importable through
    # explicit paths. The probe must not make exceptions for instrumentation I/O.
    pythonpath = os.pathsep.join(
        (
            str(PACKAGE.parent),
            sysconfig.get_path("purelib"),
            sysconfig.get_path("platlib"),
        )
    )
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
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": pythonpath},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert list(tmp_path.iterdir()) == []
