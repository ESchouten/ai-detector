from copy import deepcopy

import pytest
from detection_birth_parity import check_cached_sources


def inputs():
    sources = [
        dict(second=i / 2, publisher_frame=i * 10 + 1, pixels_sha256=str(i))
        for i in range(3)
    ]
    cache = [
        dict(
            second=r["second"],
            publisher_frame=r["publisher_frame"],
            source_pixels_sha256=r["pixels_sha256"],
            boxes=[{"x1": i}],
            origin="new_half_second" if i == 1 else "frozen_integer_baseline",
        )
        for i, r in enumerate(sources)
    ]
    baseline = [
        dict(
            second=r["second"],
            publisher_frame=r["publisher_frame"],
            source_pixels_sha256=r["source_pixels_sha256"],
            raw_detector_boxes=deepcopy(r["boxes"]),
        )
        for r in (cache[0], cache[2])
    ]
    return cache, sources, baseline


def test_complete_cache_preserves_integers_but_never_reuses_half_second_proposals():
    cache, sources, baseline = inputs()
    assert list(check_cached_sources(cache, sources, baseline)) == [0, 1]
    cache[2]["boxes"][0]["x1"] += 1
    with pytest.raises(ValueError, match="preserved exactly"):
        check_cached_sources(cache, sources, baseline)


@pytest.mark.parametrize("change", ["missing", "shifted", "duplicate", "pixels"])
def test_all_intermediate_sources_are_verified_even_though_not_replayed(change):
    cache, sources, baseline = inputs()
    if change == "missing":
        cache.pop(1)
    elif change == "shifted":
        cache[1]["publisher_frame"] += 1
    elif change == "duplicate":
        cache[1] = deepcopy(cache[0])
    else:
        cache[1]["source_pixels_sha256"] = "changed"
    with pytest.raises(ValueError):
        check_cached_sources(cache, sources, baseline)
