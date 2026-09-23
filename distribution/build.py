"""Build a desktop preview locally, or run the same individual stages in CI."""

import argparse
import json
import os
import platform as host
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from package import PackageInputs, archive, assemble_package, version_number

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Target:
    bun: str
    extra: str
    suffix: str = ""


TARGETS = {
    "macos-arm64": Target("darwin-arm64", "default"),
    "windows-x64": Target("windows-x64-baseline", "windowsml", ".exe"),
    "linux-x64": Target("linux-x64-baseline", "default"),
}
COLLECT = ("ultralytics", "litellm", "imageio_ffmpeg", "onnxruntime", "onnx")


def run(*arguments: str | Path, cwd: Path = ROOT, env: dict | None = None) -> None:
    command = [str(argument) for argument in arguments]
    # Windows package managers are .cmd entrypoints; resolve them before Popen.
    command[0] = shutil.which(command[0]) or command[0]
    subprocess.run(command, cwd=cwd, env=env, check=True)


@contextmanager
def build_metadata(path: Path, content: str):
    original = path.read_bytes()
    path.write_text(content, encoding="utf-8")
    try:
        yield
    finally:
        path.write_bytes(original)


def build_detector(args) -> Path:
    target = TARGETS[args.platform]
    kind = args.type or target.extra
    if not args.skip_dependencies:
        run(
            "uv",
            "sync",
            "--locked",
            "--python",
            json.loads((ROOT / "distribution/toolchain.json").read_text())["python"],
            "--extra",
            kind,
            cwd=ROOT / "detector",
        )
    flags = ["--onefile" if args.onefile else "--onedir"]
    for module in COLLECT:
        flags += ["--collect-all", module]
    if kind == "windowsml":
        flags += ["--collect-all", "winui3", "--collect-all", "winrt"]
    if args.platform == "macos-arm64" and not args.onefile:
        flags += [
            "--windowed",
            "--osx-bundle-identifier",
            "io.github.eschouten.ai-detector.detector",
        ]
    name = args.name or "aidetector"
    reference = os.environ.get("GITHUB_REF_NAME", args.version)
    metadata = f"TYPE = {kind!r}\nREF_NAME = {reference!r}\n"
    with build_metadata(ROOT / "detector/src/aidetector/version.py", metadata):
        run(
            "uv",
            "run",
            "--no-sync",
            "pyinstaller",
            "src/aidetector/__main__.py",
            "--name",
            name,
            *flags,
            "--hidden-import=tiktoken_ext.openai_public",
            "--hidden-import=tiktoken_ext",
            "--paths",
            "src",
            "--specpath",
            ROOT / "detector/build",
            "--clean",
            "--noconfirm",
            cwd=ROOT / "detector",
        )
    artifact = name + (
        target.suffix
        if args.onefile
        else ".app"
        if args.platform == "macos-arm64"
        else ""
    )
    return ROOT / "detector/dist" / artifact


@contextmanager
def staged_ffmpeg(standalone: bool, suffix: str):
    """Keep build-only assets out of the next build, including after a failure."""
    destination = ROOT / "web/static/_internal"
    with tempfile.TemporaryDirectory(prefix="ai-web-assets-") as temporary:
        original = Path(temporary) / "original"
        if destination.exists():
            shutil.move(destination, original)
        try:
            if standalone:
                destination.mkdir(parents=True)
                shutil.copy2(ffmpeg_path(), destination / f"ffmpeg{suffix}")
            yield
        finally:
            if destination.exists():
                shutil.rmtree(destination)
            if original.exists():
                shutil.move(original, destination)


def warm_windows_compiler() -> None:
    # Bun needs its compile cache populated on the system drive before CI's D: checkout.
    with tempfile.TemporaryDirectory(
        prefix="ai-bun-", dir=os.environ["LOCALAPPDATA"]
    ) as temporary:
        folder = Path(temporary)
        (folder / "warmup.ts").write_text("console.log('warmup');\n")
        run(
            "bun",
            "build",
            "--compile",
            "--target=bun-windows-x64-baseline",
            "warmup.ts",
            "--outfile",
            "warmup.exe",
            cwd=folder,
        )


def build_web(args) -> Path:
    target = TARGETS[args.platform]
    if not args.skip_dependencies:
        run("pnpm", "install", "--frozen-lockfile", cwd=ROOT / "web")
    if args.platform == "windows-x64":
        warm_windows_compiler()
    env = {
        **os.environ,
        "AI_DETECTOR_WEB_TARGET": target.bun,
        "APP_VERSION": args.version,
    }
    with (
        staged_ffmpeg(args.standalone_web, target.suffix),
        build_metadata(
            ROOT / "web/src/lib/version.ts",
            f"export const version = {json.dumps(os.environ.get('GITHUB_REF_NAME', args.version))};\n",
        ),
    ):
        run("pnpm", "build", cwd=ROOT / "web", env=env)
    return ROOT / "web/dist" / f"ai-detector-web{target.suffix}"


def ffmpeg_path() -> Path:
    result = subprocess.run(
        ["node", "-p", 'require("ffmpeg-static")'],
        cwd=ROOT / "web",
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def build_launcher(platform: str, output: Path, version: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if platform == "macos-arm64":
        sdk, launcher = output / "sparkle", output / "mac-launcher"
        run("bash", ROOT / "distribution/macos/build-launcher.sh", sdk, launcher)
        return {"sparkle": sdk, "mac_launcher": launcher}
    if platform == "windows-x64":
        launcher = output / "windows-launcher"
        run("dotnet", "tool", "restore")
        project = ROOT / "distribution/windows/launcher/Launcher.csproj"
        run("dotnet", "restore", project, "--locked-mode")
        run(
            "dotnet",
            "build",
            project,
            "--no-restore",
            "--configuration",
            "Release",
            f"-p:Version={version}",
            "--output",
            launcher,
            "--warnaserror",
        )
        return {"windows_launcher": launcher}
    return {}


def build_application(args) -> None:
    from installers import build_installer
    from sign_macos import sign_app
    from smoke import smoke

    detector = args.detector or build_detector(args)
    web = build_web(args)
    args.output.mkdir(parents=True, exist_ok=True)
    launcher = build_launcher(args.platform, args.output, args.version)
    folder = assemble_package(
        PackageInputs(
            detector,
            web,
            ffmpeg_path(),
            args.output,
            args.platform,
            version=args.version,
            **launcher,
        )
    )
    if args.platform == "macos-arm64":
        sign_app(folder / "AI Detector.app")
    smoke(folder)
    print(build_installer(folder, args.platform, args.version))
    print(archive(folder))


def native_platform() -> str:
    system, machine = host.system(), host.machine().lower()
    targets = {
        ("Darwin", "arm64"): "macos-arm64",
        ("Windows", "amd64"): "windows-x64",
        ("Windows", "x86_64"): "windows-x64",
        ("Linux", "x86_64"): "linux-x64",
        ("Linux", "amd64"): "linux-x64",
    }
    if (system, machine) not in targets:
        raise ValueError(
            f"Unsupported build machine: {system} {machine}. Use an Apple Silicon Mac, Windows x64 or Linux x64."
        )
    return targets[system, machine]


def required_tools(args) -> set[str]:
    tools = set()
    if args.stage in {"web", "all"}:
        tools.update(("node", "pnpm", "bun"))
    if args.stage == "detector" or (args.stage == "all" and not args.detector):
        tools.add("uv")
        if args.platform == "macos-arm64":
            tools.update(("xcrun", "codesign"))
    if args.stage in {"launcher", "all"}:
        tools.update(
            {
                "macos-arm64": ("bash", "curl", "shasum", "tar", "xcrun"),
                "windows-x64": ("dotnet",),
                "linux-x64": (),
            }[args.platform]
        )
    if args.stage == "all":
        tools.update(
            {
                "macos-arm64": ("codesign", "hdiutil"),
                "windows-x64": (),
                "linux-x64": ("desktop-file-validate", "dpkg-deb"),
            }[args.platform]
        )
    return tools


def preflight(args) -> None:
    native = native_platform()
    args.platform = args.platform or native
    if args.platform != native:
        raise ValueError(
            f"Build {args.platform} on its matching machine; this machine builds {native}."
        )
    if args.stage in {"launcher", "all"}:
        args.output = args.output.resolve()
    if args.stage == "all" and args.detector:
        args.detector = args.detector.resolve()
    if args.stage == "detector":
        validate_detector_build(args)
    missing = sorted(
        tool for tool in required_tools(args) if shutil.which(tool) is None
    )
    if missing:
        raise ValueError(
            f"Install these build tools first: {', '.join(missing)}. See distribution/README.md."
        )
    if args.stage in {"web", "launcher", "all"}:
        args.version = version_number(args.version)
    if args.stage == "all":
        validate_preview(args)
        if args.platform == "macos-arm64" and find_spec("dmgbuild") is None:
            raise ValueError(
                "Install distribution/requirements.txt in this Python environment before building the Mac installer."
            )


def validate_detector_build(args) -> None:
    if args.name and (
        "/" in args.name or "\\" in args.name or args.name in {".", ".."}
    ):
        raise ValueError("--name must be a filename, not a path.")
    if args.type == "windowsml" and args.platform != "windows-x64":
        raise ValueError("Windows ML requires a Windows x64 build machine.")
    if args.type in {"cuda", "tensorrt"} and not args.skip_dependencies:
        raise ValueError(
            "CUDA and TensorRT builds require a prepared GPU dependency environment. "
            "Install the matching dependencies first, then use --skip-dependencies."
        )


def validate_preview(args) -> None:
    if args.output.exists() and (
        not args.output.is_dir() or any(args.output.iterdir())
    ):
        raise ValueError(
            f"Choose a fresh output directory with --output: {args.output} already exists and is not empty."
        )
    parent = args.output.resolve()
    while not parent.exists():
        parent = parent.parent
    if not parent.is_dir() or not os.access(parent, os.W_OK):
        raise ValueError(f"Build output is not writable: {args.output}")
    if args.detector:
        binary = args.detector / (
            "Contents/MacOS/aidetector"
            if args.platform == "macos-arm64"
            else f"aidetector{TARGETS[args.platform].suffix}"
        )
        if not binary.is_file():
            raise ValueError(f"The frozen detector is missing: {binary}")


def parse_arguments(argv: list[str] | None = None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--platform", choices=TARGETS)
    common.add_argument("--version", default="0.0.0")
    dependencies = argparse.ArgumentParser(add_help=False)
    dependencies.add_argument(
        "--skip-dependencies",
        action="store_true",
        help="Dependencies are already installed",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    full = stages.add_parser(
        "all",
        parents=[common, dependencies],
        help="Build and smoke-test a complete preview installer",
    )
    full.add_argument("--output", type=Path, default=ROOT / "application-dist")
    full.add_argument("--detector", type=Path, help="Reuse an already frozen detector")
    full.set_defaults(onefile=False, name=None, type=None, standalone_web=False)
    detector = stages.add_parser(
        "detector",
        parents=[common, dependencies],
        help="Freeze the detector using the shared hooks",
    )
    detector.add_argument("--onefile", action="store_true")
    detector.add_argument("--name", help="Standalone detector artifact name")
    detector.add_argument(
        "--type",
        choices=("default", "windowsml", "cuda", "tensorrt"),
        help="Inference backend; CUDA and TensorRT require --skip-dependencies",
    )
    web = stages.add_parser(
        "web", parents=[common, dependencies], help="Compile the desktop web executable"
    )
    web.add_argument(
        "--standalone-web",
        action="store_true",
        help="Embed FFmpeg for standalone web downloads",
    )
    launcher = stages.add_parser(
        "launcher", parents=[common], help="Compile the native desktop launcher"
    )
    launcher.add_argument("--output", type=Path, required=True)
    packed = stages.add_parser(
        "archive", help="Archive a validated, assembled application"
    )
    packed.add_argument("folder", type=Path)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_arguments()
    if args.stage == "archive":
        print(archive(args.folder))
        raise SystemExit(0)
    try:
        preflight(args)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if args.stage == "all":
        build_application(args)
    elif args.stage == "detector":
        build_detector(args)
    elif args.stage == "web":
        build_web(args)
    else:
        build_launcher(args.platform, args.output, args.version)
