"""Command line: build manifests and benchmark embedding networks on them."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reid.benchmark import Options, embeddings, evaluate, subsample
from reid.manifest import crops_from_pattern, read_manifest, write_manifest


def _percent(value: float | None) -> str:
    return "–" if value is None else f"{100 * value:.1f}"


def table(results: Sequence[dict[str, Any]]) -> str:
    """One Markdown row per run: ranking, then naming at the target precision."""
    lines = [
        "| Model | Data | Rank-1 | mAP | Level | In top 3 | Named, own fold | "
        "Named, carried | Right when named | Strangers named | Day | Night |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        summary = result["summary"]
        for level in ("crop", "track"):
            if level not in summary:
                continue
            entry = summary[level]
            lines.append(
                f"| {result['model']} | {result['manifest']} "
                f"| {_percent(summary['rank1'])} | {_percent(summary['map'])} | {level} "
                f"| {_percent(entry['top3'])} "
                f"| {_percent(entry['oracle_coverage'])} "
                f"| {_percent(entry['carried_coverage'])} "
                f"| {_percent(entry['carried_precision'])} "
                f"| {_percent(entry['carried_strangers_named'])} "
                f"| {_percent(entry['day_coverage'])} "
                f"| {_percent(entry['night_coverage'])} |"
            )
    return "\n".join(lines)


def _benchmark(arguments: argparse.Namespace) -> None:
    from reid.backbones import build

    options = Options(
        strangers=arguments.strangers,
        folds=arguments.folds,
        seed=arguments.seed,
        k=arguments.k,
        gallery_fraction=arguments.gallery_fraction,
        gap_sessions=arguments.gap_sessions,
        precision=arguments.precision,
        max_per_identity=arguments.max_per_identity,
    )
    crops = subsample(
        read_manifest(arguments.manifest), options.max_per_identity, options.seed
    )
    arguments.out.mkdir(parents=True, exist_ok=True)
    results = []
    for model in arguments.model:
        embedder = build(
            model,
            checkpoint=arguments.checkpoint,
            grayscale=arguments.grayscale,
            batch_size=arguments.batch_size,
            device=arguments.device,
        )
        print(
            f"Embedding {len(crops)} crops with {embedder.name} on {embedder.device}…",
            file=sys.stderr,
        )
        if embedder.device.type == "cpu" and arguments.device is None:
            print(
                "Warning: no GPU found; embedding on the processor is slow. "
                "Saved embeddings are reused on the next run.",
                file=sys.stderr,
            )
        vectors = embeddings(crops, embedder, arguments.out / "cache")
        result = {
            "model": embedder.name,
            "manifest": arguments.manifest.stem,
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            **evaluate(crops, vectors, options),
        }
        if not result["time_disjoint"]:
            print(
                "Warning: no sessions in the manifest; gallery and queries were split "
                "at random, so these scores are optimistic.",
                file=sys.stderr,
            )
        path = arguments.out / f"{arguments.manifest.stem}.{embedder.name}.json"
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        results.append(result)
    print(table(results))


def _report(arguments: argparse.Namespace) -> None:
    results = [
        json.loads(path.read_text(encoding="utf-8")) for path in arguments.results
    ]
    print(table(results))


def _pattern(arguments: argparse.Namespace) -> None:
    crops = crops_from_pattern(
        arguments.root, arguments.pattern, arguments.night_from_colour
    )
    write_manifest(arguments.out, crops)
    print(
        f"{len(crops)} crops of {len({crop.identity for crop in crops})} animals "
        f"written to {arguments.out}",
        file=sys.stderr,
    )


def _video(arguments: argparse.Namespace) -> None:
    from reid.video import crops_from_labelled_video

    crops = crops_from_labelled_video(
        arguments.video,
        arguments.labels,
        arguments.out,
        session=arguments.session,
        every=arguments.every,
        frame_pattern=arguments.frame_pattern,
        frame_offset=arguments.frame_offset,
        identity_prefix=arguments.identity_prefix,
        min_size=arguments.min_size,
        night_from_colour=arguments.night_from_colour,
    )
    existing = (
        read_manifest(arguments.manifest)
        if arguments.append and arguments.manifest.exists()
        else ()
    )
    write_manifest(arguments.manifest, [*existing, *crops])
    print(
        f"{len(crops)} crops in {len({crop.track for crop in crops})} tracks added to "
        f"{arguments.manifest}",
        file=sys.stderr,
    )


def _tracks(arguments: argparse.Namespace) -> None:
    from reid.tracking import tracks_from_video

    crops = tracks_from_video(
        arguments.video,
        arguments.out,
        session=arguments.session,
        model=arguments.model,
        every=arguments.every,
        imgsz=arguments.imgsz,
        confidence=arguments.confidence,
        min_size=arguments.min_size,
        max_covered=arguments.max_covered,
        min_crops=arguments.min_crops,
        mask_background=not arguments.no_mask,
        device=arguments.device,
    )
    existing = (
        read_manifest(arguments.manifest)
        if arguments.append and arguments.manifest.exists()
        else ()
    )
    write_manifest(arguments.manifest, [*existing, *crops])
    print(
        f"{len(crops)} crops in {len({crop.track for crop in crops})} tracks added to "
        f"{arguments.manifest}",
        file=sys.stderr,
    )


def _add_scoring(commands: argparse._SubParsersAction) -> None:
    bench = commands.add_parser("benchmark", help="score models on a manifest")
    bench.add_argument("manifest", type=Path)
    bench.add_argument(
        "--model",
        action="append",
        required=True,
        help="preset name or timm:<name>[@size]; repeat to compare models",
    )
    bench.add_argument("--checkpoint", type=Path, help="weights for a timm model")
    bench.add_argument("--grayscale", action="store_true")
    bench.add_argument("--strangers", type=float, default=0.25)
    bench.add_argument("--folds", type=int, default=3)
    bench.add_argument("--seed", type=int, default=0)
    bench.add_argument("--k", type=int, default=2, help="nearest pictures per animal")
    bench.add_argument("--gallery-fraction", type=float, default=0.5)
    bench.add_argument("--gap-sessions", type=int, default=0)
    bench.add_argument("--precision", type=float, default=0.99)
    bench.add_argument("--max-per-identity", type=int)
    bench.add_argument("--batch-size", type=int, default=32)
    bench.add_argument("--device", help="cuda, mps or cpu; detected when left out")
    bench.add_argument("--out", type=Path, default=Path("results"))
    bench.set_defaults(run=_benchmark)

    report = commands.add_parser("report", help="table of earlier results")
    report.add_argument("results", type=Path, nargs="+")
    report.set_defaults(run=_report)


def _add_imports(commands: argparse._SubParsersAction) -> None:
    pattern = commands.add_parser(
        "manifest-from-pattern", help="manifest from labels in picture paths"
    )
    pattern.add_argument("root", type=Path)
    pattern.add_argument("--out", type=Path, required=True)
    pattern.add_argument(
        "--pattern",
        default=r"^(?P<identity>[^/]+)/",
        help="regex on the relative path with named groups identity, session, "
        "camera, track (default: one folder per animal)",
    )
    pattern.add_argument("--night-from-colour", action="store_true")
    pattern.set_defaults(run=_pattern)

    video = commands.add_parser(
        "crops-from-video", help="identified crops from a video and per-frame boxes"
    )
    video.add_argument("video", type=Path)
    video.add_argument("labels", type=Path, help="folder of per-frame label files")
    video.add_argument("--out", type=Path, required=True, help="folder for crops")
    video.add_argument("--manifest", type=Path, required=True)
    video.add_argument("--append", action="store_true")
    video.add_argument("--session", required=True, help="recording day, sortable")
    video.add_argument("--every", type=int, default=30, help="use every Nth frame")
    video.add_argument("--frame-pattern", default=r"(\d+)\.txt$")
    video.add_argument("--frame-offset", type=int, default=0)
    video.add_argument("--identity-prefix", default="")
    video.add_argument("--min-size", type=int, default=96)
    video.add_argument("--night-from-colour", action="store_true")
    video.set_defaults(run=_video)


def _add_tracking(commands: argparse._SubParsersAction) -> None:
    tracks = commands.add_parser(
        "tracks-from-video", help="unlabelled cow tracks from farm video"
    )
    tracks.add_argument("video", type=Path)
    tracks.add_argument("--out", type=Path, required=True, help="folder for crops")
    tracks.add_argument("--manifest", type=Path, required=True)
    tracks.add_argument("--append", action="store_true")
    tracks.add_argument("--session", required=True, help="recording day, sortable")
    tracks.add_argument("--model", default="yolo26x-seg.pt")
    tracks.add_argument("--every", type=int, default=5, help="use every Nth frame")
    tracks.add_argument("--imgsz", type=int, default=1280)
    tracks.add_argument("--confidence", type=float, default=0.5)
    tracks.add_argument("--min-size", type=int, default=128)
    tracks.add_argument(
        "--max-covered", type=float, default=0.3, help="share hidden by other cows"
    )
    tracks.add_argument("--min-crops", type=int, default=3)
    tracks.add_argument("--no-mask", action="store_true", help="keep the background")
    tracks.add_argument("--device", help="mps, cuda or cpu")
    tracks.set_defaults(run=_tracks)


def _train(arguments: argparse.Namespace) -> None:
    from reid.training import TrainOptions, train

    crops = read_manifest(arguments.manifest)
    if arguments.until:
        if any(not crop.session for crop in crops):
            raise ValueError("--until needs a session on every crop")
        crops = tuple(crop for crop in crops if crop.session < arguments.until)
    crops = subsample(crops, arguments.max_per_identity, arguments.seed)
    options = TrainOptions(
        epochs=arguments.epochs,
        identities_per_batch=arguments.identities_per_batch,
        crops_per_identity=arguments.crops_per_identity,
        learning_rate=arguments.learning_rate,
        grayscale=arguments.grayscale,
        seed=arguments.seed,
    )
    print(
        f"Training {arguments.model} on {len(crops)} crops of "
        f"{len({crop.identity for crop in crops})} animals",
        file=sys.stderr,
    )
    path = train(
        crops,
        arguments.model,
        arguments.out,
        options,
        checkpoint=arguments.checkpoint,
        device=arguments.device,
    )
    print(
        f"Saved {path}; benchmark it with --model {arguments.model} --checkpoint {path}"
    )


def _add_training(commands: argparse._SubParsersAction) -> None:
    training = commands.add_parser("train", help="fine-tune a timm model on cows")
    training.add_argument("manifest", type=Path)
    training.add_argument("--model", required=True)
    training.add_argument("--out", type=Path, required=True, help="a .safetensors file")
    training.add_argument("--checkpoint", type=Path, help="start from these weights")
    training.add_argument(
        "--until", help="train only on sessions before this one, to test on the rest"
    )
    training.add_argument("--epochs", type=int, default=10)
    training.add_argument("--identities-per-batch", type=int, default=16)
    training.add_argument("--crops-per-identity", type=int, default=4)
    training.add_argument("--learning-rate", type=float, default=3e-5)
    training.add_argument("--max-per-identity", type=int)
    training.add_argument("--grayscale", action="store_true")
    training.add_argument("--seed", type=int, default=0)
    training.add_argument("--device", help="mps, cuda or cpu")
    training.set_defaults(run=_train)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="reid", description=__doc__)
    commands = root.add_subparsers(required=True)
    _add_scoring(commands)
    _add_imports(commands)
    _add_tracking(commands)
    _add_training(commands)
    return root


def main(argv: Sequence[str] | None = None) -> None:
    arguments = parser().parse_args(argv)
    try:
        arguments.run(arguments)
    except (OSError, ValueError) as error:
        raise SystemExit(f"reid: {error}") from error
