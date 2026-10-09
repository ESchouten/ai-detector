"""Confirm the photographs the application itself would have taken of tracked videos.

The application saves a photograph of every animal it follows, of crops fit to
identify from, once every `review_interval` seconds, and a farmer confirms
the photographs of one followed animal together. Here the publisher's boxes
stand in for the farmer: a photograph is confirmed as the cow whose box the
application's box was paired with, and photographs of unpaired boxes and of
cows that are not to be enrolled are left out.

That gives the herd of a farmer who reviewed those videos without pause, the
most the application can take of them: many photographs of each animal from
few moments, and none of a cow that was not in view. The application's limit
on photographs per hour is left out here.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from app_policy import fit_crops
from app_score import preset_rules
from app_scores import tracked_crops
from enroll import identifier
from tune import tracked_run

from aidetector.adapters.identity_catalog import Catalog, EnrolledIdentity
from aidetector.adapters.media.images import encode_jpeg
from aidetector.configuration import IdentityConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tracks", type=Path, nargs="+", help="Written by app_track")
    parser.add_argument("--frames", type=Path, required=True, help="Folder of frame folders")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--enrolled", type=int, nargs="+", required=True)
    parser.add_argument("--preset", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True, help="Empty data folder")
    arguments = parser.parse_args()
    settings = json.loads(arguments.preset.read_text())
    rules = preset_rules(settings)
    interval = IdentityConfig.model_validate(settings["identity"]).review_interval
    images = arguments.data / "identities" / "images"
    images.mkdir(parents=True)
    samples, followed = defaultdict(list), defaultdict(set)
    for track in arguments.tracks:
        run = tracked_run(track, arguments.frames, arguments.labels)
        crops = tracked_crops(track, arguments.frames / run["video"])
        saved = {}
        for box, fit, cow, crop in zip(
            run["boxes"], fit_crops(run["boxes"], rules), run["partner"], crops, strict=True
        ):
            due = box["track"] not in saved or box["seconds"] - saved[box["track"]] >= interval
            if not (fit and due):
                continue
            # The application takes the photograph whoever it shows; the farmer confirms it or not.
            saved[box["track"]] = box["seconds"]
            if cow in arguments.enrolled:
                sample = identifier(f"{run['video']} {box['track']} {box['seconds']}")
                (images / f"{sample}.jpg").write_bytes(encode_jpeg(crop, quality=95))
                samples[cow].append(sample)
                followed[cow].add((run["video"], box["track"]))
    catalog = Catalog(
        revision=1,
        identities=tuple(
            EnrolledIdentity(id=identifier(f"cow {cow}"), name=str(cow), samples=tuple(photos))
            for cow, photos in sorted(samples.items())
        ),
    )
    (images.parent / "catalog.json").write_text(catalog.model_dump_json())
    print(
        json.dumps(
            {
                str(cow): {"photographs": len(photos), "confirmations": len(followed[cow])}
                for cow, photos in sorted(samples.items())
            }
        )
    )


if __name__ == "__main__":
    main()
