"""Compare source complexity and import coupling with an explicit Git baseline."""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from radon.complexity import cc_visit
from radon.visitors import Class, Function

PACKAGE = Path("detector/src/aidetector")
CONTROL_BLOCKS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.Match,
)
# Run Grimp in each snapshot's import root so package discovery cannot reuse the
# working tree or the other snapshot. Grimp owns import resolution, including
# relative imports and imports exposed through package __init__ modules.
GRAPH_SCRIPT = """
import json
import grimp
graph = grimp.build_graph('aidetector', exclude_type_checking_imports=True, cache_dir=None)
print(json.dumps(sorted(
    (source, target) for source in graph.modules
    for target in graph.find_modules_directly_imported_by(source)
)))
"""


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments], check=True, capture_output=True, text=True
    ).stdout


def history_touches(repo: Path) -> tuple[int, Counter]:
    history = git(
        repo,
        "log",
        "--no-merges",
        "-100",
        "--no-renames",
        "--format=COMMIT:%H",
        "--name-only",
        "-z",
        "--",
        f":(glob){PACKAGE.as_posix()}/**/*.py",
    )
    entries = [entry.lstrip("\n") for entry in history.split("\0") if entry]
    commits = sum(entry.startswith("COMMIT:") for entry in entries)
    return commits, Counter(
        entry for entry in entries if not entry.startswith("COMMIT:")
    )


def snapshot_base(repo: Path, base: str, target: Path) -> str | None:
    if base == "empty":
        return None
    revision = git(
        repo, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"
    ).strip()
    paths = git(
        repo, "ls-tree", "-r", "--name-only", "-z", revision, "--", PACKAGE.as_posix()
    )
    for name in filter(None, paths.split("\0")):
        path = Path(name)
        if path.suffix == ".py":
            destination = target / path.relative_to(PACKAGE.parent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                git(repo, "show", f"{revision}:{name}"), encoding="utf-8"
            )
    return revision


def snapshot_current(repo: Path, target: Path) -> None:
    for path in sorted((repo / PACKAGE).rglob("*.py")):
        destination = target / path.relative_to(repo / PACKAGE.parent)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)


def function_blocks(blocks):
    for block in blocks:
        if isinstance(block, Function):
            yield block
            yield from function_blocks(block.closures)
        elif isinstance(block, Class):
            yield from function_blocks((*block.methods, *block.inner_classes))


def nesting(node: ast.AST, depth: int = 0) -> int:
    """Maximum syntactic control-block depth; nested definitions stand alone."""
    if isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    ):
        return depth
    depth += isinstance(node, CONTROL_BLOCKS)
    deepest = depth
    for child in ast.iter_child_nodes(node):
        child_depth = depth
        # Python nests elif in the AST even though it stays at the same level.
        if (
            isinstance(node, ast.If)
            and isinstance(child, ast.If)
            and child.col_offset == node.col_offset
        ):
            child_depth -= 1
        deepest = max(deepest, nesting(child, child_depth))
    return deepest


def functions(source: str) -> dict[str, dict]:
    complexity = {
        block.lineno: block.complexity for block in function_blocks(cc_visit(source))
    }
    found = {}

    def visit(node: ast.AST, prefix: str = "") -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            prefix = f"{prefix}.{node.name}" if prefix else node.name
            if not isinstance(node, ast.ClassDef):
                found[prefix] = {
                    "line": node.lineno,
                    "complexity": complexity[node.lineno],
                    "nesting": max(nesting(child) for child in node.body),
                }
        for child in ast.iter_child_nodes(node):
            visit(child, prefix)

    visit(ast.parse(source))
    return found


def measure(root: Path) -> tuple[dict, list[list[str]], bool]:
    package = root / "aidetector"
    if not package.exists():
        return {}, [], False
    paths = sorted(package.rglob("*.py"))
    # Grimp skips namespace directories nested in a regular package. Empty
    # initializers make those legacy directories visible in this isolated copy;
    # remove them before comparing files, and never count them as source modules.
    initializers = sorted(
        {
            parent / "__init__.py"
            for path in paths
            for parent in path.parents
            if parent.is_relative_to(package) and not (parent / "__init__.py").exists()
        }
    )
    try:
        for initializer in initializers:
            initializer.touch()
        edges = json.loads(
            subprocess.run(
                [sys.executable, "-c", GRAPH_SCRIPT],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(root)},
            ).stdout
        )
    finally:
        for initializer in initializers:
            initializer.unlink(missing_ok=True)
    modules = {}
    for path in paths:
        relative = path.relative_to(root)
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        name = ".".join(parts)
        modules[(PACKAGE.parent / relative).as_posix()] = {
            "name": name,
            "fan_in": sum(target == name for _, target in edges),
            "fan_out": sum(source == name for source, _ in edges),
            "functions": functions(path.read_text(encoding="utf-8")),
        }
    return modules, edges, bool(initializers)


def changed_files(before: Path, after: Path) -> dict[str, dict]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--no-index",
            "--no-ext-diff",
            "--no-textconv",
            "--name-status",
            "-z",
            "--find-renames",
            str(before),
            str(after),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip())
    records = (
        iter(result.stdout.rstrip("\0").split("\0")) if result.stdout else iter(())
    )
    changes = {}
    for status in records:
        old_path = next(records)
        new_path = next(records) if status.startswith("R") else old_path
        root = after if status.startswith(("A", "R")) else before
        path = (PACKAGE.parent / Path(new_path).relative_to(root)).as_posix()
        changes[path] = {
            "status": {"A": "added", "D": "removed", "M": "modified", "R": "renamed"}[
                status[0]
            ],
            "previous_path": (
                PACKAGE.parent / Path(old_path).relative_to(before)
            ).as_posix()
            if status.startswith("R")
            else path,
        }
    return changes


def metric_delta(before: dict | None, after: dict | None, name: str) -> int | None:
    return (
        after[name] - before[name] if before is not None and after is not None else None
    )


def compare_modules(before: dict, after: dict, changes: dict) -> tuple[list, list]:
    module_rows, function_rows = [], []
    renamed = {
        item["previous_path"]
        for item in changes.values()
        if item["status"] == "renamed"
    }
    for path in sorted((before.keys() | after.keys()) - renamed):
        change = changes.get(path, {"status": "unchanged", "previous_path": path})
        old, new = before.get(change["previous_path"]), after.get(path)
        module = (after[path] if path in after else before[change["previous_path"]])[
            "name"
        ]
        module_rows.append(
            {
                "path": path,
                **change,
                "module": module,
                "before": {key: old[key] for key in ("fan_in", "fan_out")}
                if old
                else None,
                "after": {key: new[key] for key in ("fan_in", "fan_out")}
                if new
                else None,
                "fan_in_delta": metric_delta(old, new, "fan_in"),
                "fan_out_delta": metric_delta(old, new, "fan_out"),
            }
        )
        old_functions, new_functions = (
            (old or {}).get("functions", {}),
            (new or {}).get("functions", {}),
        )
        for name in sorted(old_functions.keys() | new_functions.keys()):
            previous, current = old_functions.get(name), new_functions.get(name)
            status = (
                "added"
                if previous is None
                else "removed"
                if current is None
                else "existing"
            )
            function_rows.append(
                {
                    "path": path,
                    "module": module,
                    "name": name,
                    "status": status,
                    "before": previous,
                    "after": current,
                    "complexity_delta": metric_delta(previous, current, "complexity"),
                    "nesting_delta": metric_delta(previous, current, "nesting"),
                }
            )
    return module_rows, function_rows


def generate_report(repo: Path, base: str) -> dict:
    repo = Path(git(repo, "rev-parse", "--show-toplevel").strip())
    with tempfile.TemporaryDirectory(prefix="aidetector-quality-") as temporary:
        before, after = Path(temporary) / "before", Path(temporary) / "after"
        before.mkdir()
        after.mkdir()
        revision = snapshot_base(repo, base, before)
        snapshot_current(repo, after)
        old, old_edges, old_namespaces = measure(before)
        new, new_edges, new_namespaces = measure(after)
        modules, function_rows = compare_modules(old, new, changed_files(before, after))
    previous_edges, current_edges = (
        set(map(tuple, old_edges)),
        set(map(tuple, new_edges)),
    )
    commits, touches = history_touches(repo)
    for module in modules:
        module["committed_touches"] = touches[module["path"]]
    report = {
        "scope": PACKAGE.as_posix(),
        "baseline": {
            "requested": base,
            "revision": revision,
            "package_present": bool(old),
            "namespace_scaffolding": old_namespaces,
        },
        "current": {
            "revision": git(repo, "rev-parse", "HEAD").strip(),
            "includes_untracked": True,
            "namespace_scaffolding": new_namespaces,
        },
        "history": {
            "limit": 100,
            "commits_examined": commits,
            "definition": "Last 100 non-merge commits touching detector Python files; exact paths, no rename following; uncommitted changes excluded.",
        },
        "modules": modules,
        "functions": function_rows,
        "dependencies": {
            "added": sorted(current_edges - previous_edges),
            "removed": sorted(previous_edges - current_edges),
        },
        "notes": [
            "Cyclomatic complexity is measured by Radon; no composite quality score is calculated.",
            "Nesting is maximum control-block depth with flat elif chains, not cognitive complexity.",
            "Callable counts group definitions by qualified name and keep the last definition; overload declarations use their implementation metrics.",
            "Coupling counts direct internal imports resolved by Grimp; TYPE_CHECKING imports are excluded.",
            "New/removed functions have no numeric delta; renames use Git similarity detection.",
            "Metrics guide review; low scores do not prove correctness, readability or good architecture.",
        ],
    }
    if old_namespaces or new_namespaces:
        report["notes"].append(
            "Temporary empty initializers let Grimp inspect legacy namespace directories; repository source is untouched."
        )
    return report


def render_markdown(report: dict) -> str:
    current = [item for item in report["functions"] if item["after"] is not None]
    changed = [item for item in report["modules"] if item["status"] != "unchanged"]
    baseline = report["baseline"]
    lines = [
        "## Python code-quality changes\n",
        f"Baseline: `{baseline['requested']}` ({baseline['revision'] or 'explicitly empty'}).",
        f"{len(changed)} changed modules; {len(current)} current functions. Working tree includes untracked source.\n",
        f"History: {report['history']['commits_examined']}/100 non-merge commits touching Python; exact-path counts exclude uncommitted changes.\n",
    ]
    if not baseline["package_present"]:
        lines.append(
            "The baseline has no detector package; current modules/functions are reported as added.\n"
        )
    deltas = sorted(
        (item for item in current if item["complexity_delta"] not in (None, 0)),
        key=lambda item: (-item["complexity_delta"], item["path"], item["name"]),
    )
    hotspots = sorted(
        current,
        key=lambda item: (-item["after"]["complexity"], item["path"], item["name"]),
    )
    for title, items in (
        ("Complexity changes", deltas),
        ("Current complexity hotspots", hotspots),
    ):
        lines.append(
            f"### {title}\n\n| Function | Complexity | Change | Nesting |\n| --- | ---: | ---: | ---: |"
        )
        for item in items[:10]:
            metrics = item["after"]
            delta = (
                f"{item['complexity_delta']:+d}"
                if item["complexity_delta"] is not None
                else "new"
            )
            lines.append(
                f"| `{item['module']}.{item['name']}` (L{metrics['line']}) | {metrics['complexity']} | {delta} | {metrics['nesting']} |"
            )
        if not items:
            lines.append("| None | — | — | — |")
        lines.append("")
    lines.append(
        "### Current import coupling\n\n| Module | Imported by | Imports | Committed touches |\n| --- | ---: | ---: | ---: |"
    )
    coupled = sorted(
        (item for item in report["modules"] if item["after"]),
        key=lambda item: (-sum(item["after"].values()), item["module"]),
    )
    for item in coupled[:10]:
        lines.append(
            f"| `{item['module']}` | {item['after']['fan_in']} | {item['after']['fan_out']} | {item['committed_touches']} |"
        )
    lines.append("\n### Changed modules\n")
    for item in changed[:20]:
        old = (
            f" (from `{item['previous_path']}`)" if item["status"] == "renamed" else ""
        )
        lines.append(f"- {item['status']}: `{item['path']}`{old}")
    if not changed:
        lines.append("No source files changed.")
    edges = report["dependencies"]
    lines.append(
        f"\nDependencies: **{len(edges['added'])} added**, **{len(edges['removed'])} removed**.\n"
    )
    for status in ("added", "removed"):
        for source, target in edges[status][:10]:
            lines.append(f"- {status}: `{source}` → `{target}`")
    lines.append(
        "\nTables show at most 10 hotspots/edges and 20 changed modules; JSON contains all entries.\n"
    )
    lines.extend(report["notes"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        required=True,
        help="Git revision to compare, or 'empty' for an explicit empty baseline",
    )
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".reports/quality"),
        help="Output prefix for .json and .md artifacts",
    )
    args = parser.parse_args()
    try:
        report = generate_report(args.repo, args.base)
        markdown = render_markdown(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.with_suffix(".json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        args.output.with_suffix(".md").write_text(markdown, encoding="utf-8")
    except (
        OSError,
        ValueError,
        SyntaxError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as error:
        detail = (
            error.stderr.strip()
            if isinstance(error, subprocess.CalledProcessError) and error.stderr
            else str(error)
        )
        print(f"Quality report failed: {detail}", file=sys.stderr)
        return 1
    print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
