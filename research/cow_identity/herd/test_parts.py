import numpy as np

from parts import fewer_photographs
from parts_compare import scores


def test_thinning_keeps_every_cow_and_the_order_of_her_photographs():
    rows = [{"cow": cow, "path": f"{cow}-{number}"} for cow in (5, 1) for number in range(6)]
    rows.append({"cow": 9, "path": "9-0"})

    kept = fewer_photographs(rows, 3)

    assert [row["cow"] for row in kept] == [1, 1, 1, 5, 5, 5, 9]
    for cow in (1, 5):
        numbers = [int(row["path"].split("-")[1]) for row in kept if row["cow"] == cow]
        assert numbers == sorted(numbers)


def kept(folder, label, seed, photographs, crops):
    np.savez(
        folder / f"{label}-s{seed}.npz",
        photographs=np.array(photographs, np.float16),
        crops=np.array(crops, np.float16),
    )


def test_each_kind_takes_its_own_nearest_photographs_and_the_kinds_are_averaged(tmp_path):
    # Three photographs of cow 4 and two of cow 7, described in one dimension per network.
    np.save(tmp_path / "owners.npy", np.array([4, 4, 4, 7, 7]))
    kept(tmp_path, "first", 0, [[1.0], [0.5], [0.0], [0.25], [0.25]], [[1.0]])
    kept(tmp_path, "first", 1, [[0.0], [0.5], [1.0], [0.75], [0.75]], [[1.0]])
    kept(tmp_path, "second", 0, [[0.0], [0.0], [1.0], [1.0], [0.5]], [[1.0]])

    alone, cows = scores(tmp_path, "first:0")
    together, _ = scores(tmp_path, "first:0,1")
    kinds, _ = scores(tmp_path, "first:0+second:0")

    assert cows == [4, 7]
    # Cow 4's two nearest photographs: 1 and 0.5.
    np.testing.assert_allclose(alone, [[0.75, 0.25]])
    # Networks of a kind are averaged photograph by photograph first.
    np.testing.assert_allclose(together, [[0.5, 0.5]])
    # The second kind's nearest are other photographs: 1 and 0, and 1 and 0.5.
    np.testing.assert_allclose(kinds, [[(0.75 + 0.5) / 2, (0.25 + 0.75) / 2]])


def test_a_share_of_the_photographs_grows_with_their_number(tmp_path):
    owners = np.array([4] * 200 + [7] * 2)
    np.save(tmp_path / "owners.npy", owners)
    similar = np.linspace(0.0, 0.995, 200).tolist() + [0.5, 0.25]
    kept(tmp_path, "first", 0, [[value] for value in similar], [[1.0]])

    two, _ = scores(tmp_path, "first:0")
    share, _ = scores(tmp_path, "first:0@share")

    np.testing.assert_allclose(two, [[np.mean(similar[198:200]), 0.375]], rtol=1e-3)
    # Two per cent of two hundred photographs are four; of two, still two.
    np.testing.assert_allclose(share, [[np.mean(similar[196:200]), 0.375]], rtol=1e-3)
