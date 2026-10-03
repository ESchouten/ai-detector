"""Research-only mapping from separately detected torsos to whole-animal tracks."""

from dataclasses import replace

from aidetector.domain.models import IdentityMatch


def contained_fraction(inner, outer):
    area = (inner.x2 - inner.x1) * (inner.y2 - inner.y1)
    if area <= 0:
        return 0.0
    overlap = max(0, min(inner.x2, outer.x2) - max(inner.x1, outer.x1)) * max(
        0, min(inner.y2, outer.y2) - max(inner.y1, outer.y1)
    )
    return overlap / area


def associate_torsos(whole, torsos, minimum_containment=0.9):
    """Require a unique geometric relation in both directions, without truth labels."""
    candidates = [
        [
            i
            for i, box in enumerate(whole)
            if contained_fraction(torso, box) >= minimum_containment
        ]
        for torso in torsos
    ]
    result = []
    for index, owners in enumerate(candidates):
        if len(owners) != 1:
            continue
        owner = owners[0]
        if sum(owner in choices for choices in candidates) != 1:
            continue
        result.append(
            (
                owner,
                replace(torsos[index], label="cow", track_id=whole[owner].track_id),
            )
        )
    return result


def identify_whole_animals(identifier, source, observation):
    whole = tuple(b for b in observation.boxes if b.label == "whole_visible_cow")
    torsos = tuple(b for b in observation.boxes if b.label == "coat_torso")
    pairs = associate_torsos(whole, torsos)
    crop_observation = replace(observation, boxes=tuple(torso for _, torso in pairs))
    recognized = identifier.identify(source, crop_observation)
    identities = {
        index: box.identity
        for (index, _), box in zip(pairs, recognized.boxes, strict=True)
    }
    return replace(
        observation,
        boxes=tuple(
            replace(box, label="cow", identity=identities.get(i, IdentityMatch()))
            for i, box in enumerate(whole)
        ),
    )
