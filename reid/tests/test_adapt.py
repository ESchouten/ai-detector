import numpy as np
import pytest

from conftest import FakeEmbedder
from reid.adapt import Adaptation, fit
from reid.benchmark import embeddings
from reid.enrollment import Options, simulate


def _unit(rows) -> np.ndarray:
    rows = np.asarray(rows, dtype=np.float32)
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


# Two cows along axes 0 and 1, seen on two days that shift every picture along
# axis 2, all far out along axis 3, which every picture in the barn shares.
COWS = np.eye(5)[[0, 0, 1, 1]]
DAYS = np.array([1.0, -1.0, 1.0, -1.0])[:, None] * np.eye(5)[2]
BARN = 3 * np.eye(5)[3]
SEEN = [[0], [1], [2], [3]]


def test_adaptations_are_named_kind_and_shrink():
    assert Adaptation.parse("names:0.3") == Adaptation("names", 0.3)
    assert str(Adaptation.parse("whiten")) == "whiten:1"
    assert str(Adaptation.parse("center:5")) == "center"
    with pytest.raises(ValueError, match="Unknown adaptation"):
        Adaptation.parse("rotate")


def test_none_leaves_the_embedding_as_it_is():
    vectors = _unit(COWS + DAYS + BARN)

    assert fit(Adaptation(), vectors, SEEN)(vectors) is vectors


def test_centring_takes_off_the_look_every_cow_in_the_barn_shares():
    vectors = _unit(COWS + BARN)

    adapted = fit(Adaptation("center"), vectors, SEEN)(vectors)

    assert vectors[0] @ vectors[2] > 0.8
    assert adapted[0] @ adapted[2] == pytest.approx(-1.0)
    assert np.linalg.norm(adapted, axis=1) == pytest.approx(1.0)


def test_the_farmers_names_damp_what_changes_from_day_to_day():
    vectors = _unit(COWS + DAYS + BARN)

    centred = fit(Adaptation("center"), vectors, SEEN)(vectors)
    named = fit(Adaptation("names", 1e-6), vectors, SEEN, ["a", "a", "b", "b"])(vectors)

    # Centred, the day shows more than the cow; damped, only the cow is left.
    assert centred[0] @ centred[1] < centred[0] @ centred[2]
    assert named[0] @ named[1] == pytest.approx(1.0, abs=1e-4)
    assert named[0] @ named[2] == pytest.approx(-1.0, abs=1e-4)
    # Unnamed sightings teach nothing beyond the centring.
    unnamed = fit(Adaptation("names", 1e-6), vectors, SEEN, ["", "", "", ""])
    assert unnamed(vectors) == pytest.approx(centred)


def test_tracks_damp_what_changes_within_one_cows_track():
    vectors = _unit(COWS + DAYS + BARN)

    adapted = fit(Adaptation("tracks", 1e-6), vectors, [[0, 1], [2, 3]])(vectors)

    assert adapted[0] @ adapted[1] == pytest.approx(1.0, abs=1e-4)


def test_each_adaptation_is_scored_on_every_gallery(herd):
    vectors = embeddings(herd, FakeEmbedder(noise=0.1))
    adapts = (Adaptation(), Adaptation("center"), Adaptation("names"))

    result = simulate(herd, vectors, Options(merges=(0.8,), goal=1.0, adapts=adapts))

    assert [entry["adapt"] for entry in result["labelled"]] == [
        "none",
        "center",
        "names:1",
    ]
    assert [entry["adapt"] for entry in result["grouped"]] == [
        "none",
        "center",
        "names:1",
    ]
    assert result["options"]["adapts"] == ["none", "center", "names:1"]
    for entry in result["labelled"]:
        assert entry["mean"]["wrong"] == 0
