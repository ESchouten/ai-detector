"""Score names shown on video against publisher boxes.

Every predicted box of a sampled frame is paired one-to-one with an annotated
animal at an overlap of 0.5 or more. A name counts as correct only on the
animal it is paired with.

A named box without a partner is not simply wrong: the detector may have drawn
it loosely around the right cow, or around a cow the publisher did not box in
that frame. It is judged by the annotated animal it lies on, which is the one
it overlaps most, by at least half the overlap that pairing asks for. On the
named cow it proves nothing either way. On another annotated animal, or on
none while the named cow is annotated elsewhere in the frame, it is an error.
Otherwise it cannot be judged. The conservative precision counts every such
name as wrong.
"""

from collections import Counter, defaultdict

from matching import match, overlap

COUNTS = (
    "visible_enrolled",
    "visible_withheld",
    "located_enrolled",
    "located_withheld",
    "correct",
    "wrong_enrolled",
    "named_withheld",
    "named_unannotated",
    "unpaired_on_named",
    "unpaired_on_other",
    "unpaired_on_withheld",
    "unpaired_elsewhere",
    "unpaired_unjudged",
)


LOOSE = 0.25


def lies_on(box, truth):
    """The annotated animal an unpaired box lies on, or None when on none."""
    if not truth:
        return None
    shared = overlap([item[1:] for item in truth], [box])[:, 0]
    return truth[int(shared.argmax())][0] if shared.max() >= LOOSE else None


def unpaired(name, nearest, present, enrolled):
    """How a name on a box without an annotated partner is counted."""
    if nearest == name:
        return "unpaired_on_named"
    if nearest is not None:
        return "unpaired_on_other" if nearest in enrolled else "unpaired_on_withheld"
    return "unpaired_elsewhere" if name in present else "unpaired_unjudged"


def score_frame(truth, predictions, enrolled, ignored=frozenset()):
    """`truth`: (cow, x1, y1, x2, y2); `predictions`: dicts with `box` and `name`.

    Animals in `ignored` and the predictions paired with them are left out of
    every count: development must not look at the animals the final test withholds.
    """
    counts = Counter()
    per_cow = defaultdict(Counter)
    pairs = match([box[1:] for box in truth], [item["box"] for item in predictions])
    partner = {predicted: annotated for annotated, predicted in pairs}
    located = {annotated for annotated, _ in pairs}
    for position, (cow, *_) in enumerate(truth):
        if cow in ignored:
            continue
        kind = "enrolled" if cow in enrolled else "withheld"
        counts[f"visible_{kind}"] += 1
        per_cow[cow]["visible"] += 1
        if position in located:
            counts[f"located_{kind}"] += 1
            per_cow[cow]["located"] += 1
    for position, item in enumerate(predictions):
        name = item.get("name")
        if name is None:
            continue
        if position not in partner:
            nearest = lies_on(item["box"], truth)
            if nearest not in ignored:
                counts["named_unannotated"] += 1
                counts[unpaired(name, nearest, {cow for cow, *_ in truth}, enrolled)] += 1
            continue
        cow = truth[partner[position]][0]
        if cow in ignored:
            continue
        if cow not in enrolled:
            counts["named_withheld"] += 1
            per_cow[cow]["named"] += 1
        elif cow == name:
            counts["correct"] += 1
            per_cow[cow]["correct"] += 1
        else:
            counts["wrong_enrolled"] += 1
            per_cow[cow]["wrong"] += 1
    return counts, per_cow


def summarise(counts):
    supported = counts["correct"] + counts["wrong_enrolled"] + counts["named_withheld"]
    judged = (
        supported
        + counts["unpaired_on_other"]
        + counts["unpaired_on_withheld"]
        + counts["unpaired_elsewhere"]
    )

    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None

    return {
        **{key: counts[key] for key in COUNTS},
        "coverage": ratio(counts["correct"], counts["visible_enrolled"]),
        "precision": ratio(counts["correct"], judged),
        "precision_conservative": ratio(
            counts["correct"], supported + counts["named_unannotated"]
        ),
        "withheld_named": ratio(
            counts["named_withheld"] + counts["unpaired_on_withheld"],
            counts["visible_withheld"],
        ),
        "localization_recall": ratio(
            counts["located_enrolled"] + counts["located_withheld"],
            counts["visible_enrolled"] + counts["visible_withheld"],
        ),
    }


def score_video(frames, labels, enrolled, ignored=frozenset()):
    """`frames`: list of (index, predictions); `labels(index)` returns the truth."""
    total = Counter()
    cows = defaultdict(Counter)
    for index, predictions in frames:
        counts, per_cow = score_frame(labels(index), predictions, enrolled, ignored)
        total += counts
        for cow, values in per_cow.items():
            cows[cow] += values
    result = summarise(total)
    result["per_cow"] = {str(cow): dict(values) for cow, values in sorted(cows.items())}
    return result
