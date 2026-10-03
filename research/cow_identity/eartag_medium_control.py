"""Freeze one PP-OCRv6 medium pair comparison with unchanged OCR scoring."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json
from eartag_ocr import checked

BASE = Path(__file__).with_name("eartag_ocr_protocol.json")
MODELS = Path(".cache/cow-ear-tags/medium-models.json")


def freeze(destination):
    base = checked(BASE)
    medium = json.loads(MODELS.read_text())
    if digest(Path(medium["official_catalog"])) != medium["catalog_sha256"]:
        raise ValueError("Official pinned model catalog changed")
    for row in medium["models"]:
        if (
            Path(row["path"]).stat().st_size != row["bytes"]
            or digest(Path(row["path"])) != row["sha256"]
        ):
            raise ValueError("Medium model differs from official hash or size")
        component = row["kind"].title()
        base["params"][f"{component}.model_path"] = str(Path(row["path"]).resolve())
        base["params"][f"{component}.model_type"] = "medium"
    base["files"].update(
        {
            name: digest(Path(name))
            for name in (
                __file__,
                str(BASE),
                str(MODELS),
                medium["official_catalog"],
                *(row["path"] for row in medium["models"]),
            )
        }
    )
    base["scope"] = (
        "One stronger pretrained PP-OCRv6-medium detector and recognizer pair, same frozen64 development tags/all157 GTlines, same CPU2thread pipeline and fixed .95 literal scoring. No training, threshold sweep, character restriction, identity-field heuristic or heldout access."
    )
    base["comparison"] = {
        "base_protocol_sha256": digest(BASE),
        "changed": "Only detector/recognizer weights and their model_type metadata small→medium; same orientation classifier and all other pipeline/settings/scoring.",
        "motivation": "Original errors included both text localization truncation and wrong high-confidence recognition even with oracle line polygons.",
        "primary_sources": [
            "https://arxiv.org/abs/2606.13108",
            "https://github.com/RapidAI/RapidOCR/blob/v3.9.2/python/rapidocr/default_models.yaml",
        ],
        "limits": "Upstream generic OCR results do not establish ear-tag or biological identity accuracy. OCR confidence remains uncalibrated; no automatic naming promotion.",
    }
    write_json(destination, base)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    if args.protocol.exists():
        parser.error("Preserve immutable protocols")
    freeze(args.protocol)
