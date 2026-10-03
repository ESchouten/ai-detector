import pytest
from detection_birth_extended_cache import join_existing


def rows():
    source = [
        {"second": t, "publisher_frame": int(t * 20) + 1, "pixels_sha256": str(t)}
        for t in (0, 0.5, 1)
    ]
    prefix = [
        {
            "second": r["second"],
            "publisher_frame": r["publisher_frame"],
            "source_pixels_sha256": r["pixels_sha256"],
            "boxes": [r["second"]],
        }
        for r in source[:2]
    ]
    old = [
        {
            "second": r["second"],
            "publisher_frame": r["publisher_frame"],
            "source_pixels_sha256": r["pixels_sha256"],
            "raw_detector_boxes": [r["second"]],
            "boxes": ["propagated"],
        }
        for r in (source[0], source[2])
    ]
    return source, prefix, old


def test_reuses_raw_arrays_and_preserves_prefix_overlap():
    source, prefix, old = rows()
    result = join_existing(prefix, old, source)
    assert [result[t]["boxes"] for t in (0, 0.5, 1)] == [[0], [0.5], [1]]
    assert result[0]["origin"] == "frozen_development_cache"
    assert result[1]["origin"] == "frozen_reserved_integer"


def test_conflicting_overlap_is_not_silently_replaced():
    source, prefix, old = rows()
    old[0]["raw_detector_boxes"] = ["changed"]
    with pytest.raises(ValueError, match="arrays differ"):
        join_existing(prefix, old, source)


@pytest.mark.parametrize("mutation", ["pixels", "duplicate", "outside"])
def test_cache_source_corruption_fails(mutation):
    source, prefix, old = rows()
    if mutation == "pixels":
        old[0]["source_pixels_sha256"] = "other"
    elif mutation == "duplicate":
        old.append(old[0])
    else:
        old[0]["second"] = 3000
    with pytest.raises(ValueError):
        join_existing(prefix, old, source)
