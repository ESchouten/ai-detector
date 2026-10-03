"""Pinned startup assets for the explicitly selected continuous identity trial."""

from dataclasses import dataclass
from pathlib import Path

from aidetector.adapters.inference.cutie_runtime import (
    WEIGHTS_SHA256,
    require_cutie_runtime,
)
from aidetector.adapters.inference.model_assets import resolve_model_path
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status

CUTIE_URL = (
    "https://github.com/hkchengrex/Cutie/releases/download/v1.0/cutie-base-mega.pth"
)
SAM_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0/sam2.1_t.pt"
SAM_SHA256 = "3c1e81ca9b037dd39d70a014ddb9a813d6c4c4e12555420db7eaff31689bd4e3"


@dataclass(frozen=True)
class ContinuousModels:
    cutie: Path
    startup: Path


def prepare_continuous_models(
    directory: Path, report_status: ReportStatus = ignore_status
) -> ContinuousModels:
    """Optional dependency check precedes transfers; hashes precede model loads."""
    require_cutie_runtime()
    report_status(
        StatusEvent(
            "identity_preparing",
            message="Preparing experimental anonymous camera tracking models…",
        )
    )
    return ContinuousModels(
        Path(
            resolve_model_path(
                CUTIE_URL, directory, directory, report_status, sha256=WEIGHTS_SHA256
            )
        ),
        Path(
            resolve_model_path(
                SAM_URL, directory, directory, report_status, sha256=SAM_SHA256
            )
        ),
    )
