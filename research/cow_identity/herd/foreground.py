"""Keep the animal and grey out everything else in a crop.

Stalls, bedding and neighbours look the same whichever cow lies there, and a
model shown whole crops learns the place as readily as the coat. The mask comes
from the stock segmentation model applied to the crop itself, so photographs
confirmed by the farmer and crops taken from live video are treated alike.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

FILL = (124, 116, 104)[::-1]
ANIMALS = ("cow", "horse", "sheep", "dog", "bear", "elephant", "zebra", "giraffe", "cat")


class Foreground:
    def __init__(self, weights, device="mps", size=448, confidence=0.05):
        self.model = YOLO(str(weights))
        self.classes = [key for key, name in self.model.names.items() if name in ANIMALS]
        self.device, self.size, self.confidence = device, size, confidence

    def masks(self, images):
        """One boolean mask per image, or None where no animal was outlined."""
        results = self.model.predict(
            images,
            conf=self.confidence,
            classes=self.classes,
            imgsz=self.size,
            device=self.device,
            retina_masks=True,
            verbose=False,
        )
        masks = []
        for image, result in zip(images, results, strict=True):
            if result.masks is None or not len(result.masks):
                masks.append(None)
                continue
            found = result.masks.data.cpu().numpy() > 0.5
            largest = found[found.reshape(len(found), -1).sum(1).argmax()]
            if largest.shape != image.shape[:2]:
                largest = (
                    cv2.resize(
                        largest.astype(np.uint8),
                        (image.shape[1], image.shape[0]),
                        interpolation=cv2.INTER_NEAREST,
                    )
                    > 0
                )
            masks.append(largest)
        return masks

    def cut(self, images):
        """(image with grey background, share of the crop kept) per image."""
        cut = []
        for image, mask in zip(images, self.masks(images), strict=True):
            if mask is None:
                cut.append((image, 0.0))
                continue
            kept = image.copy()
            kept[~mask] = FILL
            cut.append((kept, float(mask.mean())))
        return cut


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON rows with a path")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=448, help="Longest side stored")
    parser.add_argument("--batch", type=int, default=16)
    arguments = parser.parse_args()
    rows = json.loads(arguments.manifest.read_text())
    root = arguments.manifest.parent
    foreground = Foreground(arguments.weights)
    for start in range(0, len(rows), arguments.batch):
        chunk = rows[start : start + arguments.batch]
        images = []
        for row in chunk:
            image = cv2.imread(str(root / row["path"]))
            scale = arguments.limit / max(image.shape[:2])
            if scale < 1:
                image = cv2.resize(
                    image,
                    (max(1, round(image.shape[1] * scale)), max(1, round(image.shape[0] * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            images.append(image)
        for row, (image, share) in zip(chunk, foreground.cut(images), strict=True):
            target = arguments.output / Path(row["path"]).with_suffix(".jpg")
            target.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(target), image, [cv2.IMWRITE_JPEG_QUALITY, 95])
            row["path"] = str(Path(row["path"]).with_suffix(".jpg"))
            row["foreground"] = round(share, 4)
        if start % 800 == 0:
            print(f"{start}/{len(rows)}", flush=True)
    (arguments.output / arguments.manifest.name).write_text(json.dumps(rows) + "\n")
    shares = np.array([row["foreground"] for row in rows])
    print(
        f"{len(rows)} crops; no outline for {(shares == 0).sum()}; "
        f"median share kept {np.median(shares[shares > 0]):.2f}"
    )


if __name__ == "__main__":
    main()
