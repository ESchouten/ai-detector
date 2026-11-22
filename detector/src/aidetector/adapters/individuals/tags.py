"""Read the number on the tag an individual wears, such as a cow's ear tag.

Three bring-your-own ONNX models, on the processor. The finder and the lines
model are detectors with their box selection built in, as Ultralytics exports
them with `nms=True`: each takes one float32 RGB picture as 1×3×S×S in 0 to 1,
with a fixed square size, and returns 1×N×6 rows of x1, y1, x2, y2, confidence
and class in that picture's pixels. A picture is shrunk to fit, never
enlarged, and sits in the top left corner of the square. The finder is shown
an individual's picture and finds the tags in it. The lines model is shown one
tag, with its longer side at half the model's size, and finds its lines of
text; class 0 is the line with the number. The reader takes that line,
stretched to its fixed 1×3×H×W in -1 to 1, and returns 1×T×C scores for each
position, over an end mark followed by the characters its metadata lists under
`charset`, as PARSeq does. Only digits are read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from aidetector.adapters.individuals.coat import processor_session

Image = NDArray[np.uint8]
Box = tuple[int, int, int, int]
# Smaller tags have digits of a few pixels, which read as noise.
HEIGHT_MIN = 40
# How sure the models must be of a tag and of a line.
TAG_FOUND = 0.25
LINE_FOUND = 0.1
# Share of its size kept around a tag and around a line, so a tilted one is whole.
TAG_MARGIN = 0.15
LINE_MARGIN = 0.08
# The grey Ultralytics pads a picture with to make it square.
PADDING = 114


@dataclass(frozen=True)
class Tag:
    """One tag in a picture: where it is, its pixels with a margin, and what
    its number read as, with how sure the reader is of its least sure digit."""

    box: Box
    crop: Image
    text: str
    confidence: float


def around(image: Image, box: Box, margin: float) -> Box:
    """The box with a margin, within the picture."""
    x1, y1, x2, y2 = box
    across, down = round(margin * (x2 - x1)), round(margin * (y2 - y1))
    height, width = image.shape[:2]
    return (
        max(0, x1 - across),
        max(0, y1 - down),
        min(width, x2 + across),
        min(height, y2 + down),
    )


class _Detector:
    def __init__(self, path: str):
        self._session: Any = processor_session(path)
        model_input = self._session.get_inputs()[0]
        self._input = model_input.name
        self.size = int(model_input.shape[2])

    def found(self, image: Image, sure: float) -> NDArray[np.float32]:
        """The rows the model is sure enough of, with boxes in the BGR
        picture's pixels."""
        height, width = image.shape[:2]
        scale = min(self.size / height, self.size / width, 1.0)
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        square = np.full((self.size, self.size, 3), PADDING, np.uint8)
        square[: size[1], : size[0]] = (
            cv2.resize(image, size, interpolation=cv2.INTER_AREA)
            if scale < 1
            else image
        )
        rgb = cv2.cvtColor(square, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
        rows = self._session.run(None, {self._input: rgb.transpose(2, 0, 1)[None]})[0][
            0
        ]
        rows = rows[rows[:, 4] >= sure]
        rows[:, :4] /= scale
        return rows


class _Reader:
    def __init__(self, path: str):
        self._session: Any = processor_session(path)
        model_input = self._session.get_inputs()[0]
        self._input = model_input.name
        self._size = (int(model_input.shape[3]), int(model_input.shape[2]))
        charset = self._session.get_modelmeta().custom_metadata_map.get("charset")
        if not charset:
            raise ValueError("The tag reader's metadata needs its charset")
        self._charset = charset
        # The end mark and the digits; nothing else is on a number's line.
        self._read = [0, *(1 + charset.index(digit) for digit in "0123456789")]

    def read(self, image: Image, line: NDArray[np.float32]) -> tuple[str, float]:
        """The digits of a line in a BGR picture, and how sure the model is of
        the least sure one; nothing read is sure of nothing."""
        x1, y1, x2, y2 = line
        across, down = LINE_MARGIN * (x2 - x1), LINE_MARGIN * (y2 - y1)
        width, height = self._size
        # The line with its margin, stretched over the whole of the input.
        left, top = x1 - across, y1 - down
        wider = (width - 1) / (x2 + across - left)
        taller = (height - 1) / (y2 + down - top)
        stretched = cv2.warpAffine(
            image,
            np.array([[wider, 0, -left * wider], [0, taller, -top * taller]]),
            self._size,
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        rgb = cv2.cvtColor(stretched, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
        pixels = ((rgb - 0.5) / 0.5).transpose(2, 0, 1)[None]
        scores = self._session.run(None, {self._input: pixels})[0][0][:, self._read]
        scores = np.exp(scores - scores.max(axis=1, keepdims=True))
        likely = scores / scores.sum(axis=1, keepdims=True)
        text, confidence = "", 1.0
        for position in likely:
            character = int(position.argmax())
            if character == 0:
                break
            text += str(character - 1)
            confidence = min(confidence, float(position[character]))
        return text, confidence if text else 0.0


class TagReader:
    """The three ONNX Runtime sessions, on the processor.

    Create it outside the inference runtime's scope, as the coat check: the
    models are small, and tags vary in size.
    """

    def __init__(self, finder: str, lines: str, reader: str):
        self._finder = _Detector(finder)
        self._lines = _Detector(lines)
        self._reader = _Reader(reader)

    def read(self, image: Image) -> list[Tag]:
        """The tags of at least HEIGHT_MIN pixels in a BGR picture, each with
        the number on it; no text where its line was not found."""
        tags = []
        for row in self._finder.found(image, TAG_FOUND):
            x1, y1, x2, y2 = (int(value) for value in row[:4].round())
            box = (x1, y1, x2, y2)
            if y2 - y1 < HEIGHT_MIN:
                continue
            left, top, right, bottom = around(image, box, TAG_MARGIN)
            crop = image[top:bottom, left:right].copy()
            scale = self._lines.size / 2 / max(crop.shape[:2])
            size = (
                max(1, round(crop.shape[1] * scale)),
                max(1, round(crop.shape[0] * scale)),
            )
            shown = cv2.resize(
                crop,
                size,
                interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA,
            )
            lines = self._lines.found(shown, LINE_FOUND)
            lines = lines[lines[:, 5] == 0]
            text, confidence = "", 0.0
            if len(lines):
                line = lines[lines[:, 4].argmax(), :4]
                text, confidence = self._reader.read(shown, line)
            tags.append(Tag(box, crop, text, confidence))
        return tags
