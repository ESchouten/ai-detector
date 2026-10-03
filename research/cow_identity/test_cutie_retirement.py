"""Pinned SDK retirement contracts; run against the isolated patched source."""

import pytest
import torch
from cutie.inference.kv_memory_store import KeyValueMemoryStore


@pytest.mark.parametrize("temporary", [False, True])
@pytest.mark.parametrize("selection", [False, True])
def test_repeated_retirement_releases_permanent_and_temporary_bucket_state(
    temporary, selection
):
    store = KeyValueMemoryStore(save_selection=selection, save_usage=True)
    key = torch.ones((1, 2, 3))
    shrinkage = torch.ones((1, 1, 3))
    value = torch.ones((1, 4, 3))
    for object_id in range(1, 51):
        store.add(key, {object_id: value}, shrinkage, key, as_permanent="first")
        if temporary:
            store.add(key, {object_id: value}, shrinkage, key)
        assert store.num_objects == 1
        store.purge_except([])
        assert not store.engaged()
        for field in ("buckets", "k", "v", "s", "perm_end_pt", "use_cnt", "life_cnt"):
            assert not getattr(store, field)
        if selection:
            assert not store.e


def test_retiring_one_bucket_preserves_the_other_objects_memory():
    store = KeyValueMemoryStore(save_selection=True, save_usage=True)
    key = torch.ones((1, 2, 3))
    shrinkage = torch.ones((1, 1, 3))
    value = torch.ones((1, 4, 3))
    store.add(key, {7: value}, shrinkage, key, as_permanent="first")
    store.add(key, {42: value * 2}, shrinkage, key, as_permanent="first")
    survivor = store.v[42]
    store.purge_except([42])
    assert store.buckets == {1: [42]}
    assert store.v == {42: survivor}
    assert set(store.k) == set(store.s) == set(store.perm_end_pt) == {1}
    torch.testing.assert_close(store.v[42], value * 2)
