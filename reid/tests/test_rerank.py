from pathlib import Path

import numpy as np

from conftest import FakeEmbedder
from reid.benchmark import embeddings
from reid.rerank import Candidates, Options, _named, candidates, evaluate


class FakeMatcher:
    """Pictures of one cow share many coat details, of different cows few."""

    name = "fake-matcher"

    def __init__(self):
        self.pairs = []

    def matches(self, pairs):
        self.pairs.extend(pairs)
        return np.array(
            [100.0 if Path(a).parent == Path(b).parent else 5.0 for a, b in pairs],
            dtype=np.float32,
        )


def test_coat_matches_fix_what_a_blurry_embedding_confuses(herd):
    vectors = embeddings(herd, FakeEmbedder(noise=0.6))
    matcher = FakeMatcher()
    options = Options(top=3, query_crops=2, gallery_crops=2, weights=(0.0, 0.5))

    found = candidates(herd, vectors, matcher, options)
    result = evaluate(found, options)

    assert result["queries"] == len(found.truth) == 32
    # Two pictures of the sighting against two of each of three candidates.
    assert len(matcher.pairs) == 32 * 3 * 2 * 2
    alone, fused = (row for row in result["rows"] if row["margin"] == 0.0)
    assert fused["rank1"] == result["in_top"]
    assert fused["rank1"] > alone["rank1"]
    assert fused["named"] >= alone["named"]


def test_weight_zero_and_no_margin_name_by_the_embedding_alone():
    found = Candidates(
        names=np.array([["a", "b"], ["b", "a"], ["a", "b"]]),
        deep=np.array([[0.9, 0.5], [0.8, 0.7], [0.6, 0.55]], dtype=np.float32),
        matches=np.array([[0, 200], [0, 0], [0, 0]], dtype=np.float32),
        truth=np.array(["b", "b", "c"]),
        known=np.array([True, True, False]),
        in_top=np.array([True, True, False]),
    )
    options = Options(precision=0.99)

    alone = _named(found, 0.0, 0.0, options)
    fused = _named(found, 1.0, 0.0, options)

    assert alone["rank1"] == 0.5
    assert fused["rank1"] == 1.0
    assert fused["named"] == 1.0
    assert fused["strangers_named"] == 0.0
