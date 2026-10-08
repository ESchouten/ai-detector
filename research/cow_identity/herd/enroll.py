"""Write publisher crops into a data folder as the farmer's confirmed herd.

The folder then holds exactly what the web application would have written
after someone confirmed those photographs: a catalog and one JPEG per example.
"""

import hashlib
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "detector" / "src"))

from aidetector.adapters.identity_catalog import Catalog, EnrolledIdentity
from aidetector.adapters.media.images import encode_jpeg


def identifier(text):
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def write_herd(rows, root, directory):
    """One identity per cow, named by its publisher number; returns id by cow."""
    images = Path(directory) / "identities" / "images"
    images.mkdir(parents=True, exist_ok=True)
    samples = {}
    for row in rows:
        sample = identifier(row["path"])
        image = cv2.imread(str(Path(root) / row["path"]))
        (images / f"{sample}.jpg").write_bytes(encode_jpeg(image, quality=95))
        samples.setdefault(row["cow"], []).append(sample)
    identities = {cow: identifier(f"cow {cow}") for cow in samples}
    catalog = Catalog(
        revision=1,
        identities=tuple(
            EnrolledIdentity(id=identities[cow], name=str(cow), samples=tuple(photos))
            for cow, photos in sorted(samples.items())
        ),
    )
    (images.parent / "catalog.json").write_text(catalog.model_dump_json())
    return identities
