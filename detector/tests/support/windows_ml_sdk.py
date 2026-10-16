"""Offline Windows SDK packages for exercising the real preparation subprocess."""

from pathlib import Path
from textwrap import dedent


def write_windows_ml_sdk(directory: Path, providers: list[tuple[str, str]]) -> Path:
    trace = directory / "sdk-events.jsonl"
    implementation = f"PROVIDERS = {providers!r}\nTRACE = {str(trace)!r}\n" + dedent("""
        import ctypes
        import json
        import logging
        import os
        import sys
        from contextlib import contextmanager
        from pathlib import Path
        from threading import Event
        from types import SimpleNamespace

        import winrt.runtime

        assert "onnxruntime" not in sys.modules, "The helper must not load ONNX Runtime"
        assert "torch" not in sys.modules, "The helper must not load Torch"

        def record(event):
            with Path(TRACE).open("a", encoding="utf-8") as output:
                output.write(json.dumps([os.getpid(), event]) + "\\n")

        @contextmanager
        def initialize(*, options):
            assert options == 0, "Background startup must not open an SDK dialog"
            record("initialize")
            try:
                yield
            finally:
                record("close")

        class Provider:
            def __init__(self, name, behavior):
                self.name = name
                self.behavior = behavior
                self.ready_state = "ready" if behavior in {"ready", "missing_library", "relative_ready"} else "pending"
                self.library_path = "" if behavior == "missing_library" else str(Path(TRACE).parent / (name + ".dll"))
                self.package_id = SimpleNamespace(full_name=name + "_1.0.0.0_x64__test")
                if behavior.startswith("relative_"):
                    self.library_path = name + ".dll"
                    library = package_directory(name) / self.library_path
                else:
                    library = Path(self.library_path)
                if self.library_path and behavior not in {"relative_missing", "missing_file"}:
                    library.parent.mkdir(parents=True, exist_ok=True)
                    library.touch()

            def ensure_ready_async(self):
                record("prepare:" + self.name)
                return self

            def wait(self, timeout):
                assert timeout == 120
                record("wait:" + self.name)
                if self.behavior == "hang":
                    logging.warning("Simulated native call blocked")
                    Event().wait()
                return "started" if self.behavior == "timeout" else "completed"

            def cancel(self):
                record("cancel:" + self.name)

            def get_results(self):
                assert self.behavior != "timeout", "A timed-out operation has no result"
                record("results:" + self.name)
                if self.behavior == "error":
                    raise OSError("Provider download failed")
                return SimpleNamespace(
                    status="failure" if self.behavior == "failed" else "success",
                    diagnostic_text="Provider download failed",
                )

        def package_directory(name):
            return Path(TRACE).parent / "Installed packages é" / name

        class GetPackagePathByFullName:
            def __call__(self, full_name, size, output):
                name = full_name.removesuffix("_1.0.0.0_x64__test")
                behavior = dict(PROVIDERS)[name]
                record(("package-size:" if output is None else "package-path:") + name)
                if behavior == "relative_package_error":
                    return 1168
                path = str(package_directory(name))
                length = ctypes.cast(size, ctypes.POINTER(ctypes.c_uint32))
                if output is None:
                    length[0] = len(path) + 1
                    return 122
                if behavior == "relative_package_disappeared":
                    return 1168
                assert length[0] == len(path) + 1
                output.value = path
                return 0

        def load_kernel32(name, *, use_last_error):
            assert name == "kernel32"
            assert use_last_error
            return SimpleNamespace(GetPackagePathByFullName=GetPackagePathByFullName())

        ctypes.WinDLL = load_kernel32
        ctypes.WinError = lambda code: OSError(code, "Package lookup failed")
        if any(behavior.startswith("relative_") for _, behavior in PROVIDERS):
            sys.platform = "win32"

        ExecutionProviderCatalog = SimpleNamespace(
            get_default=lambda: SimpleNamespace(
                find_all_providers=lambda: [Provider(*item) for item in PROVIDERS]
            )
        )
    """)
    modules = {
        "_test_windows_ml.py": implementation,
        "winrt/runtime.py": "",
        "winrt/windows/foundation/__init__.py": (
            "from types import SimpleNamespace\n"
            'AsyncStatus = SimpleNamespace(STARTED="started")\n'
        ),
        "winui3/microsoft/windows/applicationmodel/dynamicdependency/bootstrap/__init__.py": (
            "from _test_windows_ml import initialize\n"
            "from types import SimpleNamespace\n"
            "InitializeOptions = SimpleNamespace(NONE=0, ON_NO_MATCH_SHOW_UI=1)\n"
        ),
        "winui3/microsoft/windows/ai/machinelearning/__init__.py": (
            "from _test_windows_ml import ExecutionProviderCatalog\n"
            "from types import SimpleNamespace\n"
            'ExecutionProviderReadyState = SimpleNamespace(READY="ready")\n'
            'ExecutionProviderReadyResultState = SimpleNamespace(SUCCESS="success")\n'
        ),
    }
    for relative, source in modules.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        for parent in target.relative_to(directory).parents:
            if parent != Path("."):
                (directory / parent / "__init__.py").touch()
        target.write_text(source, encoding="utf-8")
    return trace
