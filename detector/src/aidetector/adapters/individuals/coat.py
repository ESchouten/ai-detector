"""Count the coat details two pictures of individuals share.

Two bring-your-own ONNX models, such as ALIKED keypoints and the LightGlue
matcher. The keypoints model takes one float32 RGB picture as 1×3×H×W in 0 to
1, of any size, and returns `keypoints`, N×2 pixel positions (x, y), and
`descriptors`, N×D. The matcher takes `keypoints0`, `descriptors0` and `size0`
(the picture's width and height) and the same for picture 1, each with a batch
of one, and returns `scores`: how sure it is that each of picture 0's
keypoints shows in picture 1. The keypoints model's metadata may set `size`,
the longer side its pictures are scaled to; 512 otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from aidetector.adapters.individuals.embedding import model_key

SIZE = 512
SIDE_MIN = 32
# A keypoint counts as shared when the matcher is at least this sure of it.
SURE = 0.5


def processor_session(path: str) -> Any:
    """An ONNX Runtime session on the processor."""
    import onnxruntime as ort

    options = ort.SessionOptions()
    # Camera capture and the detectors need the processor between runs.
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return ort.InferenceSession(
        path, sess_options=options, providers=["CPUExecutionProvider"]
    )


@dataclass(frozen=True)
class Described:
    """One picture's keypoints as the matcher takes them."""

    keypoints: NDArray[np.float32]
    descriptors: NDArray[np.float32]
    size: NDArray[np.float32]


class CoatModel:
    """Both ONNX Runtime sessions, on the processor.

    Create it outside the inference runtime's scope, which would put the
    sessions on its accelerator: pictures and keypoint counts vary in size,
    and accelerators run such models several times slower than the processor.
    `key` names the counts they make by the two model files.
    """

    def __init__(self, keypoints: str, matcher: str):
        self.key = model_key(keypoints)[:8] + model_key(matcher)[:8]
        self._keypoints = processor_session(keypoints)
        self._matcher = processor_session(matcher)
        metadata = self._keypoints.get_modelmeta().custom_metadata_map
        self._size = int(metadata.get("size", SIZE))

    def describe(self, image: NDArray[np.uint8]) -> Described:
        """The keypoints of a BGR picture, scaled so its longer side is the model's."""
        height, width = image.shape[:2]
        scale = self._size / max(height, width)
        size = (
            max(SIDE_MIN, round(width * scale)),
            max(SIDE_MIN, round(height * scale)),
        )
        resized = cv2.resize(
            image,
            size,
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
        )
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
        keypoints, descriptors = self._keypoints.run(
            ["keypoints", "descriptors"], {"image": rgb.transpose(2, 0, 1)[None]}
        )
        return Described(
            keypoints[None], descriptors[None], np.array([size], np.float32)
        )

    def shared(self, first: Described, second: Described) -> int:
        """How many of the first picture's keypoints show in the second."""
        (scores,) = self._matcher.run(
            ["scores"],
            {
                "keypoints0": first.keypoints,
                "descriptors0": first.descriptors,
                "size0": first.size,
                "keypoints1": second.keypoints,
                "descriptors1": second.descriptors,
                "size1": second.size,
            },
        )
        return int((scores >= SURE).sum())
