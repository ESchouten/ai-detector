"""Run the whole application on a short clip and check that it names cows.

The video evaluation drives the detector and identity adapters frame by frame
so that every frame's publisher labels are known. This smoke test starts the
application itself instead, with the shipped preset and a video file as its
camera, and listens only where the live preview listens.
"""

import argparse
import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import cv2

from app_run import preset_config
from enroll import write_herd
from ethz import DISPUTED, confirmed_before, frame_labels
from video_eval import associate, tally

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.inference.herd_gallery import prepare_herd
from aidetector.adapters.inference.miewid import published_weights
from aidetector.adapters.live_preview import LivePreview
from aidetector.adapters.media.images import shrink_image
from aidetector.bootstrap import run_application


def write_clip(frames_directory, sampled, path, width):
    """The sampled frames as a one-frame-per-second video file."""
    writer = None
    for frame in sampled:
        image = shrink_image(cv2.imread(str(frames_directory / frame["file"])), width)
        if writer is None:
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*"mp4v"), 1.0, image.shape[1::-1]
            )
        writer.write(image)
    writer.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--video", required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--first", type=int, default=600, help="First sampled second")
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--enrolled", type=int, nargs="+", required=True)
    parser.add_argument("--ignored", type=int, nargs="*", default=[])
    parser.add_argument("--preset", type=Path, required=True)
    parser.add_argument("--detector-weights", type=Path, required=True)
    parser.add_argument("--herd-weights", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True, help="Empty data folder")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    rows = confirmed_before(
        json.loads(arguments.manifest.read_text()),
        arguments.video,
        set(arguments.enrolled),
        either_side=True,
    )
    identities = write_herd(rows, arguments.manifest.parent, arguments.data)
    cow_of = {identity: cow for cow, identity in identities.items()}
    clip = (arguments.data / "clip.mp4").resolve()
    config = preset_config(
        arguments.preset, arguments.detector_weights, arguments.herd_weights, clip
    )
    settings = config.detectors[0]
    sampled = json.loads((arguments.frames / "frames.json").read_text())["frames"][
        arguments.first : arguments.first + arguments.count
    ]
    write_clip(arguments.frames, sampled, clip, settings.detection.frames_width)
    # Learn before starting: a clip this short ends before learning would.
    store = IdentityCatalog(arguments.data / "identities")
    prepare_herd(
        store.load(),
        store=store,
        cattle_start=Path(settings.identity.weights),
        animal_start=published_weights(arguments.data / "models" / "identity"),
        directory=arguments.data / "identities" / "herd",
    )

    observed, statuses = [], []
    observer = LivePreview.observer

    def recording(preview, rule_id, sources):
        publish = observer(preview, rule_id, sources)

        def record(source, observation):
            observed.append(observation)
            publish(source, observation)

        return record

    with ExitStack() as stack:
        stack.enter_context(patch.object(LivePreview, "observer", recording))
        run_application(
            config,
            arguments.data,
            arguments.data,
            report_status=lambda event: statuses.append(event.kind),
            live_preview=True,
        )

    boxes, shown = [], []
    for frame, observation in zip(sampled, observed, strict=True):
        for box in observation.boxes:
            boxes.append(
                {
                    "index": frame["index"],
                    "box": [value * 2 for value in (box.x1, box.y1, box.x2, box.y2)],
                }
            )
            shown.append(
                cow_of[box.identity.identity_id]
                if box.identity is not None and box.identity.identity_id
                else None
            )
    partner, visible, located, around = associate(
        boxes,
        [frame["index"] for frame in sampled],
        lambda index: frame_labels(arguments.labels, arguments.video, index, 2560, 1440),
    )
    result = tally(
        shown,
        partner,
        visible,
        located,
        around,
        set(arguments.enrolled),
        {*arguments.ignored, DISPUTED},
    )
    result |= {
        "video": arguments.video,
        "first_second": arguments.first,
        "frames": len(sampled),
        "observations": len(observed),
        "identity_statuses": sorted({kind for kind in statuses if kind.startswith("identity")}),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "per_cow"}))


if __name__ == "__main__":
    main()
