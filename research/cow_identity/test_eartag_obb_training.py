"""A stopped or recovered run cannot masquerade as the fixed final checkpoint."""

import pytest
from eartag_obb_training import eligible_final


def test_final_checkpoint_requires_every_epoch_and_native_update():
    history = [{"epoch": i} for i in range(1, 21)]
    eligible_final(history, 1700)
    for invalid, steps in (
        (history[:-1], 1700),
        (history, 1699),
        (history[:-1] + [{"epoch": 19}], 1700),
    ):
        with pytest.raises(ValueError, match="all original"):
            eligible_final(invalid, steps)
