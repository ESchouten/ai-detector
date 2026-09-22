"""Generate small deterministic video inputs for file and reference-flow tests."""

import cv2
import numpy as np


def write_video(path, frames=12, fps=10):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (64, 48))
    assert writer.isOpened()
    try:
        for index in range(frames):
            image = np.full((48, 64, 3), index * 15, dtype=np.uint8)
            cv2.rectangle(image, (8, 8), (24, 32), (255, 80, 20), -1)
            writer.write(image)
    finally:
        writer.release()
