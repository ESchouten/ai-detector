"""Choose the identity rules on development videos, by exact replay.

Every run pairs boxes tracked by the application's detector adapter with the
similarities of a herd model taught by the application's code. The rules are
then the only free choice, and the replay applies them as the application does.

A development video is wholly daylight or wholly infrared, so one searched
limit stands for both of the application's limits and the two are read off the
runs of each kind.
"""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path

import numpy as np

from app_policy import Rules, funnel, name_crops
from ethz import DISPUTED, frame_labels
from video_eval import associate, tally

FINAL_WITHHELD = (3, 4, 12)
ENROLLABLE = (0, 1, 5, 6, 7, 8, 9, 10, 11, 13)


def load_run(scores_path, frames_root, labels_root):
    meta = json.loads(Path(scores_path).with_suffix(".json").read_text())
    saved = np.load(Path(scores_path).with_suffix(".npz"))
    track = json.loads(Path(meta["track"]).read_text())
    boxes = track["boxes"]
    video = track["video"]
    frames = [
        frame["index"]
        for frame in json.loads((Path(frames_root) / video / "frames.json").read_text())["frames"]
    ]
    width, height = boxes[0]["frame_size"]
    partner, visible, located, around = associate(
        boxes, frames, lambda index: frame_labels(labels_root, video, index, width, height)
    )
    occupied = {box["seconds"] for box in boxes}
    return {
        "name": Path(scores_path).name,
        "video": video,
        "classes": saved["classes"].tolist(),
        # No cow of another farm competes in the application: an empty last column.
        "scores": np.concatenate(
            [saved["scores"], np.full((len(saved["scores"]), 1), -1.0)], axis=1
        ),
        "boxes": [{**box, "box": box["app_box"], "frame_size": box["app_size"]} for box in boxes],
        "empty": [float(step) for step in range(track["frames"]) if float(step) not in occupied],
        "infrared": boxes[0]["infrared"],
        "partner": partner,
        "visible": visible,
        "located": located,
        "around": around,
        "meta": meta,
    }


def replay(run, rules, ignored):
    names, stages = name_crops(run["boxes"], run["scores"], run["classes"], rules, run["empty"])
    enrolled = set(run["classes"])
    result = tally(
        names,
        run["partner"],
        run["visible"],
        run["located"],
        run["around"],
        enrolled,
        {*ignored, DISPUTED},
    )
    result["stages"] = funnel(stages, run["partner"], run["visible"], run["located"], enrolled)
    return result


def replay_grid(job):
    run, grid = job
    return [
        replay(
            run,
            Rules(*values, 32, 1.0, whole_animal=True, min_similarity_infrared=values[0]),
            FINAL_WITHHELD,
        )
        for values in grid
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scores", type=Path, nargs="+", help="Written by app_scores")
    parser.add_argument("--frames", type=Path, required=True, help="Folder of frame folders")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument(
        "--similarity", type=float, nargs="+", default=[0.82, 0.84, 0.85, 0.86, 0.87, 0.88]
    )
    parser.add_argument("--margin", type=float, nargs="+", default=[0.0, 0.1])
    parser.add_argument("--observations", type=int, nargs="+", default=[3, 5, 8])
    parser.add_argument("--hold", type=float, nargs="+", default=[0, 60, 300])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    runs = [load_run(path, arguments.frames, arguments.labels) for path in arguments.scores]
    grid = list(
        product(arguments.similarity, arguments.margin, arguments.observations, arguments.hold)
    )
    with ProcessPoolExecutor(len(runs)) as pool:
        replayed = list(pool.map(replay_grid, [(run, grid) for run in runs]))
    rows = [
        {
            "min_similarity": similarity,
            "min_margin": margin,
            "min_observations": observations,
            "hold": hold,
            "runs": {
                run["name"]: {
                    key: value for key, value in results[position].items() if key != "per_cow"
                }
                for run, results in zip(runs, replayed, strict=True)
            },
        }
        for position, (similarity, margin, observations, hold) in enumerate(grid)
    ]

    for light, infrared in (("daylight", False), ("infrared", True)):
        names = [run["name"] for run in runs if run["infrared"] == infrared]
        if not names:
            continue

        def lowest(row, names=names):
            return min(row["runs"][name]["coverage"] for name in names)

        # No stranger named and no name judged wrong, in any run of this light.
        clean = [
            row
            for row in rows
            if all(
                row["runs"][name]["precision"] == 1 and not row["runs"][name]["withheld_named"]
                for name in names
            )
        ]
        print(f"{light}: {len(clean)} of {len(rows)} rule sets name no stranger and nobody wrongly")
        for row in sorted(clean, key=lowest, reverse=True)[:8]:
            print(
                f"  similarity {row['min_similarity']} margin {row['min_margin']} "
                f"observations {row['min_observations']} hold {row['hold']:.0f}: "
                + " | ".join(
                    f"{name.removeprefix('scores-')}: {row['runs'][name]['coverage']:.3f} "
                    f"(conservative {row['runs'][name]['precision_conservative']:.4f})"
                    for name in names
                )
            )
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(
                {
                    "runs": {run["name"]: run["meta"] | {"infrared": run["infrared"]} for run in runs},
                    "ignored": list(FINAL_WITHHELD),
                    "rows": rows,
                },
                indent=1,
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
