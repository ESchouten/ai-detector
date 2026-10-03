from copy import deepcopy

import pytest
from recognition_spatial_tail_train import validate_prefix_parity


def test_complete_original_parity_required_for_every_spatial_crop():
    good = {"max_absolute_error": 1e-7, "minimum_cosine": 0.9999999}
    manifest = {
        "parity": [
            {"source_indices": [1, 3], "full_split": good, "original_cache": good},
            {"source_indices": [5], "full_split": None, "original_cache": good},
        ]
    }
    validate_prefix_parity(manifest, [1, 3, 5])
    for mutation in ("missing", "duplicate", "numerical", "no_full"):
        invalid = deepcopy(manifest)
        if mutation == "missing":
            invalid["parity"].pop()
        elif mutation == "duplicate":
            invalid["parity"][1]["source_indices"] = [3]
        elif mutation == "numerical":
            invalid["parity"][1]["original_cache"]["max_absolute_error"] = 0.01
        else:
            invalid["parity"][0]["full_split"] = None
        with pytest.raises(ValueError):
            validate_prefix_parity(invalid, [1, 3, 5])
