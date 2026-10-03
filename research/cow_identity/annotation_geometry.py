"""Extract predeclared clean frames; no annotation or prediction input exists."""

import argparse
import hashlib
import json
from pathlib import Path

import cv2


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract(protocol_path, output):
    protocol = json.loads(protocol_path.read_text())
    if digest(Path(__file__)) != protocol["extractor_sha256"]:
        raise ValueError("Extractor differs from the pre-review freeze")
    video = Path(protocol["video"]["path"])
    if digest(video) != protocol["video"]["sha256"]:
        raise ValueError("Source video changed")
    centers = [
        start + 37 + 75 * index
        for start in (330, 930, 1230, 1800, 2700)
        for index in range(4)
    ]
    if protocol["seconds"] != centers or protocol["context_offsets"] != [-1, 0, 1]:
        raise ValueError("Uniform selection changed")
    output.mkdir(parents=True, exist_ok=False)
    capture = cv2.VideoCapture(str(video))
    try:
        if (capture.get(cv2.CAP_PROP_FPS), capture.get(cv2.CAP_PROP_FRAME_COUNT)) != (
            20,
            67760,
        ):
            raise ValueError("Unexpected source frame rate or length")
        rows = []
        for center in centers:
            for offset in protocol["context_offsets"]:
                second = center + offset
                frame = second * 20
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame)
                ok, image = capture.read()
                if not ok or image.shape != (600, 800, 3):
                    raise ValueError("Expected source image is unavailable")
                if capture.get(cv2.CAP_PROP_POS_FRAMES) != frame + 1:
                    raise ValueError("Source-frame seek failed")
                path = output / f"{second}.png"
                if not cv2.imwrite(str(path), image):
                    raise OSError("Could not save clean frame")
                rows.append(
                    {
                        "center": center,
                        "second": second,
                        "video_frame": frame,
                        "path": str(path),
                        "sha256": digest(path),
                        "pixels_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                        "width": 800,
                        "height": 600,
                    }
                )
    finally:
        capture.release()
    value = {
        "protocol_sha256": digest(protocol_path),
        "video_sha256": protocol["video"]["sha256"],
        "libraries": {"opencv": cv2.__version__},
        "rows": rows,
    }
    (output / "manifest.json").write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps({"scored_centers": len(centers), "clean_images": len(rows)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    extract(args.protocol, args.output)
