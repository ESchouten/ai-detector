from pathlib import Path

from conftest import FakeEmbedder
from reid.benchmark import (
    Options,
    embeddings,
    evaluate,
    other_farms,
    own_thresholds,
    report,
    score,
    subsample,
)


def test_a_separable_herd_is_named_and_strangers_are_refused(herd, tmp_path: Path):
    vectors = embeddings(herd, FakeEmbedder(noise=0.1), tmp_path / "cache")

    result = evaluate(herd, vectors, Options(strangers=0.25, folds=3))

    assert result["time_disjoint"]
    assert result["identities"] == 8
    assert [len(fold["strangers"]) for fold in result["folds"]] == [2, 2, 2]
    summary = result["summary"]
    assert summary["rank1"] == 1.0
    assert summary["track"]["rank1"] == 1.0
    assert result["folds"][0]["levels"]["track"]["rank1"] is not None
    assert summary["crop"]["oracle_precision"] >= 0.99
    assert summary["crop"]["oracle_coverage"] > 0.9
    assert summary["crop"]["carried_strangers_named"] < 0.05
    assert {"track", "crop"} <= set(summary)
    assert summary["crop"]["night_coverage"] is not None
    assert summary["crop"]["self_set_precision"] >= 0.95
    assert summary["crop"]["self_set_coverage"] > 0.5
    assert summary["crop"]["other_farms_coverage"] is None


def test_a_threshold_from_other_farms_is_applied_to_every_fold(herd, tmp_path: Path):
    options = Options()
    farm = score(herd, embeddings(herd, FakeEmbedder(noise=0.1)), options)
    noisy = score(herd, embeddings(herd, FakeEmbedder(noise=0.3, seed=1)), options)
    strict = score(herd, embeddings(herd, FakeEmbedder(noise=0.05, seed=2)), options)

    shared = other_farms([own_thresholds(noisy), own_thresholds(strict)])
    result = report(farm, options, shared)

    assert set(shared) == {"crop", "track"}
    assert (
        shared["crop"]
        == (own_thresholds(noisy)["crop"] + own_thresholds(strict)["crop"]) / 2
    )
    assert result["thresholds"]["other_farms"] == shared
    for fold in result["folds"]:
        assert fold["levels"]["crop"]["other_farms"]["threshold"] == shared["crop"]
    assert result["summary"]["track"]["other_farms_coverage"] is not None


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
