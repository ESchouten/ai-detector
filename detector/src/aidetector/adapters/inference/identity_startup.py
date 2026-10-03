"""Same-frame foreground initialization for the optional continuous tracker."""

import logging
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from aidetector.adapters.inference.identity_masks import (
    SeedSelection,
    select_startup_masks,
)
from aidetector.domain.models import BoundingBox

logger = logging.getLogger(__name__)


def segment_startup(
    weights: Path,
    image: NDArray[np.uint8],
    proposals: tuple[BoundingBox, ...],
) -> SeedSelection:
    """Segment all raw proposals on these exact pixels, then resolve overlaps.

    SAM runs once on CPU in FP32 and is released when initialization returns.
    Stable object IDs, capacity and any human names belong to the camera owner.
    The caller supplies an already resolved local SAM2.1 checkpoint; this
    boundary does not download weights or silently replace a missing model.
    """
    if not proposals:
        return select_startup_masks(np.empty((0, *image.shape[:2]), bool), ())
    if not weights.is_file():
        raise FileNotFoundError(f"Startup segmentation model not found: {weights}")

    from ultralytics import SAM

    logger.info("Preparing anonymous camera tracks from %d proposals", len(proposals))
    model = SAM(str(weights))
    result = model.predict(
        image,
        bboxes=[[box.x1, box.y1, box.x2, box.y2] for box in proposals],
        device="cpu",
        imgsz=1024,
        quantize=32,
        verbose=False,
    )[0]
    if result.masks is None:
        raise RuntimeError("Startup segmentation returned no masks for its proposals")
    masks = result.masks.data.cpu().numpy() > 0.5
    if masks.shape != (len(proposals), *image.shape[:2]):
        raise RuntimeError("Startup segmentation changed source dimensions or count")
    selected = select_startup_masks(masks, proposals)
    logger.info(
        "Anonymous camera initialization: %d of %d proposals accepted",
        len(selected.proposal_indices),
        len(proposals),
    )
    return selected
