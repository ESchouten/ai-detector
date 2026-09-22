import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.quality_report import PACKAGE, functions, generate_report, render_markdown


def git(repo, *arguments):
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def write(repo, name, text):
    path = repo / PACKAGE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def commit(repo):
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Quality Test",
        "-c",
        "user.email=quality@example.test",
        "commit",
        "-qm",
        "Fixture baseline",
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "README.md").write_text("Fixture repository\n")
    return tmp_path


def test_changed_source_includes_untracked_renamed_and_deleted_modules(repo):
    write(repo, "__init__.py", "from . import original\n")
    original = write(
        repo, "original.py", "def original():\n    return 'unique original content'\n"
    )
    obsolete = write(
        repo,
        "obsolete.py",
        "def obsolete():\n    return 'different obsolete behavior'\n",
    )
    write(repo, "rules.py", "def decide(value):\n    return value\n")
    revision = commit(repo)
    original.rename(original.with_name("renamed.py"))
    obsolete.unlink()
    write(repo, "__init__.py", "from . import renamed\n")
    write(
        repo,
        "rules.py",
        "def decide(value):\n    if value:\n        if value > 1:\n            return True\n    return False\n",
    )
    write(
        repo,
        "new.py",
        "from .renamed import original\n\ndef call():\n    return original()\n",
    )

    report = generate_report(repo, revision)

    assert report["scope"] == "detector/src/aidetector"
    assert {item["path"] for item in report["modules"]} == {
        "detector/src/aidetector/__init__.py",
        "detector/src/aidetector/renamed.py",
        "detector/src/aidetector/obsolete.py",
        "detector/src/aidetector/rules.py",
        "detector/src/aidetector/new.py",
    }
    assert all("\\" not in item["path"] for item in report["functions"])
    modules = {Path(item["path"]).name: item for item in report["modules"]}
    assert modules["renamed.py"]["status"] == "renamed"
    assert (
        modules["renamed.py"]["previous_path"] == "detector/src/aidetector/original.py"
    )
    assert "original.py" not in modules
    assert modules["obsolete.py"]["status"] == "removed"
    assert modules["obsolete.py"]["after"] is None
    assert modules["new.py"]["status"] == "added"
    assert modules["new.py"]["before"] is None
    decide = next(item for item in report["functions"] if item["name"] == "decide")
    assert decide["complexity_delta"] == 2
    assert decide["after"]["nesting"] == 2
    new = next(item for item in report["functions"] if item["name"] == "call")
    assert new["status"] == "added"
    assert new["complexity_delta"] is None
    assert ("aidetector", "aidetector.original") in report["dependencies"]["removed"]
    assert ("aidetector", "aidetector.renamed") in report["dependencies"]["added"]
    assert report["baseline"]["revision"] == revision
    assert report == generate_report(repo, revision)
    assert "renamed" in render_markdown(report)
    assert (
        git(repo, "status", "--porcelain").find("?? detector/src/aidetector/new.py")
        >= 0
    )


def test_grimp_resolves_package_and_relative_imports_without_importing_source(repo):
    write(repo, "__init__.py", "raise RuntimeError('Do not execute analyzed code')\n")
    write(repo, "feature/__init__.py", "from . import implementation\n")
    write(repo, "feature/implementation.py", "VALUE = 1\n")
    write(
        repo,
        "consumer.py",
        "from .feature import implementation\nfrom typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from . import annotations\n",
    )
    write(repo, "annotations.py", "VALUE = 2\n")
    commit(repo)

    report = generate_report(repo, "empty")

    edges = set(map(tuple, report["dependencies"]["added"]))
    assert ("aidetector.consumer", "aidetector.feature.implementation") in edges
    assert ("aidetector.feature", "aidetector.feature.implementation") in edges
    assert ("aidetector.consumer", "aidetector.annotations") not in edges
    implementation = next(
        item
        for item in report["modules"]
        if item["module"] == "aidetector.feature.implementation"
    )
    assert implementation["after"] == {"fan_in": 2, "fan_out": 0}


@pytest.mark.parametrize("base", ["empty", "HEAD"])
def test_absent_baseline_package_reports_new_code_without_zero_deltas(repo, base):
    commit(repo)
    write(repo, "__init__.py", "")
    write(repo, "new.py", "def new():\n    return True\n")

    report = generate_report(repo, base)

    assert report["baseline"]["package_present"] is False
    assert all(item["status"] == "added" for item in report["modules"])
    assert report["functions"][0]["before"] is None
    assert report["functions"][0]["complexity_delta"] is None
    assert "baseline has no detector package" in render_markdown(report)


def test_removed_entire_package_reports_deleted_code(repo):
    path = write(repo, "__init__.py", "def previous():\n    return 1\n")
    commit(repo)
    path.unlink()
    path.parent.rmdir()

    report = generate_report(repo, "HEAD")

    assert report["modules"][0]["status"] == "removed"
    assert report["functions"][0]["status"] == "removed"
    assert report["functions"][0]["after"] is None


def test_legacy_namespace_directories_keep_their_real_baseline_dependencies(repo):
    write(repo, "__init__.py", "from aidetector.legacy.worker import run\n")
    worker = write(
        repo,
        "legacy/worker.py",
        "from aidetector.legacy.policy import allowed\n\ndef run():\n    return allowed()\n",
    )
    write(repo, "legacy/policy.py", "def allowed():\n    return True\n")
    commit(repo)
    worker.write_text("def run():\n    return True\n")

    report = generate_report(repo, "HEAD")

    assert ("aidetector.legacy.worker", "aidetector.legacy.policy") in report[
        "dependencies"
    ]["removed"]
    policy = next(
        item
        for item in report["modules"]
        if item["module"] == "aidetector.legacy.policy"
    )
    assert policy["before"]["fan_in"] == 1
    assert policy["after"]["fan_in"] == 0
    assert not any(
        item["path"].endswith("legacy/__init__.py") for item in report["modules"]
    )
    assert not (repo / PACKAGE / "legacy/__init__.py").exists()


def test_nested_functions_and_methods_have_distinct_metrics():
    metrics = functions(
        "class Rules:\n    def choose(self):\n        def nested(value):\n            if value:\n                return True\n        return nested(1)\n"
    )
    assert set(metrics) == {"Rules.choose", "Rules.choose.nested"}
    assert metrics["Rules.choose"]["complexity"] == 1
    assert metrics["Rules.choose"]["nesting"] == 0
    assert metrics["Rules.choose.nested"]["complexity"] == 2
    assert metrics["Rules.choose.nested"]["nesting"] == 1


def test_flat_elif_chains_do_not_inflate_actual_nesting():
    metrics = functions("""
def flat(value):
    if value == 1:
        return 1
    elif value == 2:
        return 2
    elif value == 3:
        return 3
    return 0

def nested(value):
    if value:
        if value > 1:
            return 1
    else:
        if value is None:
            return 0
""")
    assert metrics["flat"]["nesting"] == 1
    assert metrics["flat"]["complexity"] == 4
    assert metrics["nested"]["nesting"] == 2


def test_overload_signatures_use_the_implementation_metrics_once():
    metrics = functions("""
from typing import overload

@overload
def convert(value: str) -> str: ...

@overload
def convert(value: int) -> int: ...

def convert(value):
    if isinstance(value, str):
        return value.strip()
    return value
""")
    assert list(metrics) == ["convert"]
    assert metrics["convert"] == {"line": 10, "complexity": 2, "nesting": 1}


def test_history_counts_committed_touches_without_counting_working_changes(repo):
    write(repo, "__init__.py", "")
    write(repo, "often.py", "def evaluate():\n    return 1\n")
    commit(repo)
    write(repo, "often.py", "def evaluate():\n    return 2\n")
    commit(repo)
    write(repo, "often.py", "def evaluate():\n    return 3\n")
    write(repo, "untracked.py", "def new():\n    return 1\n")

    report = generate_report(repo, "HEAD")

    modules = {item["module"]: item for item in report["modules"]}
    assert modules["aidetector.often"]["committed_touches"] == 2
    assert modules["aidetector"]["committed_touches"] == 1
    assert modules["aidetector.untracked"]["committed_touches"] == 0
    assert report["history"]["commits_examined"] == 2
    assert report["history"]["limit"] == 100
    assert "Committed touches" in render_markdown(report)


def test_cli_writes_full_json_and_markdown_and_rejects_invalid_base(repo, tmp_path):
    write(repo, "__init__.py", "")
    commit(repo)
    command = [
        sys.executable,
        str(Path(__file__).parents[1] / "tools/quality_report.py"),
        "--repo",
        str(repo),
        "--output",
        str(tmp_path / "reports/quality"),
    ]
    success = subprocess.run(
        [*command, "--base", "HEAD"], capture_output=True, text=True
    )
    assert success.returncode == 0, success.stderr
    report = json.loads((tmp_path / "reports/quality.json").read_text())
    assert report["baseline"]["revision"] == git(repo, "rev-parse", "HEAD")
    assert (tmp_path / "reports/quality.md").read_text() == success.stdout
    invalid = subprocess.run(
        [*command, "--base", "missing-revision"], capture_output=True, text=True
    )
    assert invalid.returncode == 1
    assert "Quality report failed" in invalid.stderr
    assert "Python code-quality changes" not in invalid.stdout


def test_invalid_current_source_fails_instead_of_reporting_partial_metrics(repo):
    write(repo, "__init__.py", "")
    commit(repo)
    write(repo, "broken.py", "def unfinished(\n")
    with pytest.raises((SyntaxError, subprocess.CalledProcessError)):
        generate_report(repo, "HEAD")
