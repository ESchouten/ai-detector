"""Child-process import probe, not a security sandbox for hostile/native code."""

import _thread
import importlib
import logging
import os
import sys
import threading
from pathlib import Path

READ_ROOTS = tuple(Path(path).resolve() for path in sys.path if path)
CODE_SUFFIXES = {".py", ".pyc", ".so", ".pyd", ".dll"}
METADATA_FILES = {"METADATA", "PKG-INFO", "entry_points.txt", "top_level.txt"}
# Python's platform.mac_ver(), used by package metadata, reads this OS descriptor.
PLATFORM_METADATA = Path("/System/Library/CoreServices/SystemVersion.plist")
MUTATIONS = {
    "os.mkdir",
    "os.remove",
    "os.rmdir",
    "os.rename",
    "os.link",
    "os.symlink",
    "os.chmod",
    "os.chown",
    "os.truncate",
    "os.utime",
    "os.chdir",
    "os.putenv",
    "os.unsetenv",
}
PROCESSES = {"os.system", "os.fork", "os.forkpty", "os.posix_spawn", "os.exec"}
INFERENCE_MODULES = {"torch", "numpy", "cv2", "ultralytics", "litellm", "onnxruntime"}
violations: list[str] = []


def reject(operation: str) -> None:
    message = f"Import side effect: {operation}"
    violations.append(message)
    raise RuntimeError(message)


def audit(event: str, args: tuple) -> None:
    if event.startswith(("socket.", "subprocess.")) or event in PROCESSES | MUTATIONS:
        reject(event)
    if event != "open":
        return
    filename, mode, flags = args
    if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        reject("filesystem write")
    if not isinstance(filename, (str, bytes)):
        reject("file descriptor read")
    path = Path(os.fsdecode(filename)).resolve()
    if path == PLATFORM_METADATA or (path.suffix == ".zip" and path in READ_ROOTS):
        return
    normal_import = path.suffix in CODE_SUFFIXES or (
        path.name in METADATA_FILES
        and path.parent.suffix in {".dist-info", ".egg-info"}
    )
    if not normal_import or not any(path.is_relative_to(root) for root in READ_ROOTS):
        reject(f"file read ({path.name})")


def start_thread(*args, **kwargs):
    reject("thread start")


def configure_logging(*args, **kwargs):
    reject("logging configuration")


def logging_state(logger: logging.Logger) -> tuple:
    return (
        logger.level,
        logger.disabled,
        logger.propagate,
        tuple(logger.handlers),
        tuple(logger.filters),
    )


def logger_states() -> dict[logging.Logger, tuple]:
    return {
        logging.root: logging_state(logging.root),
        **{
            logger: logging_state(logger)
            for logger in logging.Logger.manager.loggerDict.values()
            if isinstance(logger, logging.Logger)
        },
    }


def main() -> int:
    baseline = logger_states()
    disabled = logging.root.manager.disable
    sys.addaudithook(audit)
    threading.Thread.start = start_thread
    _thread.start_new_thread = start_thread
    logging.basicConfig = configure_logging
    for method in (
        "setLevel",
        "addHandler",
        "removeHandler",
        "addFilter",
        "removeFilter",
    ):
        setattr(logging.Logger, method, configure_logging)
    failed = False
    try:
        for module in sys.argv[1:]:
            importlib.import_module(module)
    except Exception as error:
        print(f"Import failed: {error}", file=sys.stderr)
        failed = True
    if logging.root.manager.disable != disabled or any(
        state != baseline.get(logger, (logging.NOTSET, False, True, (), ()))
        for logger, state in logger_states().items()
    ):
        violations.append("Import side effect: logging state changed")
    for name in INFERENCE_MODULES.intersection(sys.modules):
        violations.append(f"Import loaded inference module: {name}")
    if violations:
        # Retained evidence makes even a swallowed guard exception fail the probe.
        print("\n".join(violations), file=sys.stderr)
    return int(failed or bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
