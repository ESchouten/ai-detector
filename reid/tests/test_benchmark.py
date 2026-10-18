from pathlib import Path

from conftest import FakeEmbedder
from reid.benchmark import Options, embeddings, evaluate, subsample


def test_a_separable_herd_is_named_and_strangers_are_refused(herd, tmp_path: Path):
    vectors = embeddings(herd, FakeEmbedder(noise=0.1), tmp_path / "cache")

    result = evaluate(herd, vectors, Options(strangers=0.25, folds=3))

    assert result["time_disjoint"]
    assert result["identities"] == 8
    assert [len(fold["strangers"]) for fold in result["folds"]] == [2, 2, 2]
    summary = result["summary"]
    assert summary["rank1"] == 1.0
    assert summary["crop"]["oracle_precision"] >= 0.99
    assert summary["crop"]["oracle_coverage"] > 0.9
    assert summary["crop"]["carried_strangers_named"] < 0.05
    assert {"track", "crop"} <= set(summary)
    assert summary["crop"]["night_coverage"] is not None


def test_embeddings_are_cached_per_model_and_pictures(herd, tmp_path: Path):
    embedder = FakeEmbedder()

    first = embeddings(herd, embedder, tmp_path)
    second = embeddings(herd, embedder, tmp_path)
    embeddings(herd[:5], embedder, tmp_path)

    assert (first == second).all()
    assert embedder.calls == 2


def test_subsample_keeps_at_most_n_per_animal(herd):
    kept = subsample(herd, 5)

    assert len(kept) == 8 * 5
    assert kept == subsample(herd, 5)
    assert subsample(herd, None) == tuple(herd)
