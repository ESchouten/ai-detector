"""Run the installed detector source with its separately cached GPU dependencies."""

import os
import sys
from pathlib import Path


def check_cuda() -> None:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError(
            "NVIDIA acceleration is unavailable. Update the NVIDIA driver."
        )
    # Exercise a real kernel: discovery alone does not prove wheel/driver compatibility.
    values = torch.ones((32, 32), device="cuda")
    (values @ values).sum().item()
    print(
        f"NVIDIA acceleration ready: {torch.cuda.get_device_name(0)}; CUDA {torch.version.cuda}"
    )


def main() -> int:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    if sys.argv[1:] == ["--check-cuda"]:
        check_cuda()
        return 0
    sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))
    from aidetector.cli import main as detector_main

    return detector_main()


if __name__ == "__main__":
    raise SystemExit(main())
