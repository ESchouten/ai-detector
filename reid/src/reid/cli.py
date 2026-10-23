"""Command line: build manifests and benchmark embedding networks on them."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reid.benchmark import (
    Options,
    embeddings,
    other_farms,
    own_thresholds,
    report,
    score,
    subsample,
)
from reid.manifest import Crop, crops_from_pattern, read_manifest, write_manifest


def _percent(value: float | None) -> str:
    return "–" if value is None else f"{100 * value:.1f}"


def _naming(entry: dict[str, Any], kind: str) -> str:
    """Share of enrolled cows named, and in brackets how often the name was right."""
    coverage = entry.get(f"{kind}_coverage")
    if coverage is None:
        return "–"
    return f"{_percent(coverage)} ({_percent(entry.get(f'{kind}_precision'))})"


def table(results: Sequence[dict[str, Any]]) -> str:
    """One Markdown row per run and level: ranking, then naming at each threshold.

    mAP compares single pictures, so track rows leave it out.
    """
    lines = [
        "| Model | Data | Level | Rank-1 | mAP | In top 3 | Own fold | Other days "
        "| Self-set | Other farms | Day | Night |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        summary = result["summary"]
        for level in ("crop", "track"):
            if level not in summary:
                continue
            entry = summary[level]
            lines.append(
                f"| {result['model']} | {result['manifest']} | {level} "
                # Results saved before rank-1 was split by level carry only one.
                f"| {_percent(entry.get('rank1', summary['rank1']))} "
                f"| {_percent(summary['map']) if level == 'crop' else '–'} "
                f"| {_percent(entry['top3'])} "
                f"| {_naming(entry, 'oracle')} | {_naming(entry, 'carried')} "
                f"| {_naming(entry, 'self_set')} | {_naming(entry, 'other_farms')} "
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
        margin=arguments.margin,
    )
    farms = {
        manifest: subsample(
            read_manifest(manifest), options.max_per_identity, options.seed
        )
        for manifest in arguments.manifests
    }
    arguments.out.mkdir(parents=True, exist_ok=True)
    results = []
    for model in arguments.model:
        embedder = build(
            model,
            checkpoint=arguments.checkpoint,
            grayscale=arguments.grayscale,
            batch_size=arguments.batch_size,
            device=arguments.device,
            half=arguments.half,
        )
        if embedder.device.type == "cpu" and arguments.device is None:
            print(
                "Warning: no GPU found; embedding on the processor is slow. "
                "Saved embeddings are reused on the next run.",
                file=sys.stderr,
            )
        scored = {}
        for manifest, crops in farms.items():
            print(
                f"Embedding {len(crops)} crops of {manifest.stem} with "
                f"{embedder.name} on {embedder.device}…",
                file=sys.stderr,
            )
            vectors = embeddings(crops, embedder, arguments.out / "cache")
            scored[manifest] = score(crops, vectors, options)
            if not scored[manifest].time_disjoint:
                print(
                    f"Warning: no sessions in {manifest.stem}; gallery and queries "
                    "were split at random, so its scores are optimistic.",
                    file=sys.stderr,
                )
        own = {manifest: own_thresholds(scores) for manifest, scores in scored.items()}
        for manifest, scores in scored.items():
            others = [
                thresholds for farm, thresholds in own.items() if farm != manifest
            ]
            result = {
                "model": embedder.name,
                "manifest": manifest.stem,
                "created": datetime.now(UTC).isoformat(timespec="seconds"),
                **report(scores, options, other_farms(others) if others else None),
            }
            path = arguments.out / f"{manifest.stem}.{embedder.name}.json"
            path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            results.append(result)
    print(table(results))


def enrolment_table(result: dict[str, Any]) -> str:
    """One Markdown row per grouping similarity, after the labelled ceiling.

    Day columns are means over the test days: sightings named (right when named),
    cows recognised at least once that day, and the right cow in the top 3.
    """
    lines = [
        "| Gallery | Groups | Pure | Taps | Taps 90% | Taps 100% | Named | "
        "Cows a day | In top 3 | Wrong |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    rows = [("labelled", {}, result["labelled"])] + [
        (f"grouped at {entry['merge']}", entry, entry) for entry in result["grouped"]
    ]
    for label, enrolment, scored in rows:
        days = scored["mean"]
        milestones = enrolment.get("milestones", {})
        lines.append(
            f"| {label} | {enrolment.get('groups', '–')} "
            f"| {_percent(enrolment.get('purity'))} | {enrolment.get('taps', '–')} "
            f"| {milestones.get('0.9') or '–'} | {milestones.get('1.0') or '–'} "
            f"| {_percent(days['named'])} ({_percent(days['right'])}) "
            f"| {_percent(days['recognised'])} | {_percent(days['top3'])} "
            f"| {days['wrong']} |"
        )
    return "\n".join(lines)


def _enroll(arguments: argparse.Namespace) -> None:
    from reid.backbones import build
    from reid.enrollment import Options as EnrolOptions
    from reid.enrollment import simulate

    options = EnrolOptions(
        enrol_sessions=arguments.enrol_sessions,
        merges=tuple(arguments.merge),
        goal=arguments.goal,
        k=arguments.k,
        precision=arguments.precision,
        margin=arguments.margin,
    )
    crops = read_manifest(arguments.manifest)
    embedder = build(
        arguments.model,
        checkpoint=arguments.checkpoint,
        grayscale=arguments.grayscale,
        batch_size=arguments.batch_size,
        device=arguments.device,
        half=arguments.half,
    )
    print(
        f"Embedding {len(crops)} crops of {arguments.manifest.stem} with "
        f"{embedder.name} on {embedder.device}…",
        file=sys.stderr,
    )
    vectors = embeddings(crops, embedder, arguments.out / "cache")
    result = {
        "model": embedder.name,
        "manifest": arguments.manifest.stem,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        **simulate(crops, vectors, options),
    }
    arguments.out.mkdir(parents=True, exist_ok=True)
    path = arguments.out / f"enrol-{arguments.manifest.stem}.{embedder.name}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"{result['herd']} cows in {result['sightings']} sightings while enrolling "
        f"({', '.join(result['enrol_sessions'])}); "
        f"tested on {len(result['test_sessions'])} later sessions"
    )
    print(enrolment_table(result))


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
    bench = commands.add_parser(
        "benchmark", help="score models on one or more farms' manifests"
    )
    bench.add_argument(
        "manifests",
        type=Path,
        nargs="+",
        help="one manifest per farm; with several, each is also scored at a "
        "threshold set on the others",
    )
    bench.add_argument(
        "--model",
        action="append",
        required=True,
        help="preset name or timm:<name>[@size]; repeat to compare models",
    )
    bench.add_argument(
        "--checkpoint", type=Path, help="fine-tuned weights for the model"
    )
    bench.add_argument("--grayscale", action="store_true")
    bench.add_argument("--strangers", type=float, default=0.25)
    bench.add_argument("--folds", type=int, default=3)
    bench.add_argument("--seed", type=int, default=0)
    bench.add_argument("--k", type=int, default=2, help="nearest pictures per animal")
    bench.add_argument("--gallery-fraction", type=float, default=0.5)
    bench.add_argument("--gap-sessions", type=int, default=0)
    bench.add_argument("--precision", type=float, default=0.99)
    bench.add_argument(
        "--margin",
        type=float,
        default=0.0,
        help="share of the runner-up cow's score taken off the best one's before "
        "naming; 1 names by the lead over the runner-up",
    )
    bench.add_argument("--max-per-identity", type=int)
    bench.add_argument("--batch-size", type=int, default=32)
    bench.add_argument("--device", help="cuda, mps or cpu; detected when left out")
    bench.add_argument(
        "--half", action="store_true", help="run the network in float16 on the GPU"
    )
    bench.add_argument("--out", type=Path, default=Path("results"))
    bench.set_defaults(run=_benchmark)

    enroll = commands.add_parser(
        "enroll",
        help="simulate a farmer naming groups of a farm's first sightings, then "
        "name later days against them",
    )
    enroll.add_argument("manifest", type=Path, help="one farm, with sessions")
    enroll.add_argument("--model", required=True)
    enroll.add_argument("--checkpoint", type=Path)
    enroll.add_argument("--grayscale", action="store_true")
    enroll.add_argument(
        "--enrol-sessions",
        type=int,
        default=2,
        help="the first N sessions are for enrolling, later ones for testing",
    )
    enroll.add_argument(
        "--merge",
        type=float,
        nargs="+",
        default=[0.5, 0.6, 0.7, 0.8],
        help="similarities at which sightings are grouped; each is tried",
    )
    enroll.add_argument(
        "--goal",
        type=float,
        default=0.9,
        help="the farmer names groups until this share of the cows has a name",
    )
    enroll.add_argument("--k", type=int, default=2)
    enroll.add_argument("--precision", type=float, default=0.99)
    enroll.add_argument(
        "--margin",
        type=float,
        default=0.0,
        help="share of the runner-up cow's score taken off the best one's before "
        "naming; 1 names by the lead over the runner-up",
    )
    enroll.add_argument("--batch-size", type=int, default=32)
    enroll.add_argument("--device")
    enroll.add_argument("--half", action="store_true")
    enroll.add_argument("--out", type=Path, default=Path("results"))
    enroll.set_defaults(run=_enroll)

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


def _training_crops(
    manifests: Sequence[Path], until: str | None, limit: int | None, seed: int
) -> tuple[list[Crop], list[str]]:
    """Crops of every manifest, and the farm each came from.

    With several manifests, identities and tracks are prefixed with the
    manifest's name, so cow 1 of one farm is not cow 1 of another.
    """
    if until and len(manifests) > 1:
        raise ValueError("--until works with one manifest; sessions differ per farm")
    crops: list[Crop] = []
    farms: list[str] = []
    for manifest in manifests:
        loaded = read_manifest(manifest)
        if until:
            if any(not crop.session for crop in loaded):
                raise ValueError("--until needs a session on every crop")
            loaded = tuple(crop for crop in loaded if crop.session < until)
        loaded = subsample(loaded, limit, seed)
        if len(manifests) > 1:
            farm = manifest.stem
            loaded = tuple(
                replace(
                    crop,
                    identity=f"{farm}/{crop.identity}",
                    track=f"{farm}/{crop.track}" if crop.track else "",
                )
                for crop in loaded
            )
        crops.extend(loaded)
        farms.extend([manifest.stem] * len(loaded))
    return crops, farms


def _train(arguments: argparse.Namespace) -> None:
    from reid.training import TrainOptions, train

    crops, farms = _training_crops(
        arguments.manifests,
        arguments.until,
        arguments.max_per_identity,
        arguments.seed,
    )
    options = TrainOptions(
        epochs=arguments.epochs,
        identities_per_batch=arguments.identities_per_batch,
        crops_per_identity=arguments.crops_per_identity,
        learning_rate=arguments.learning_rate,
        grayscale=arguments.grayscale,
        gray_chance=arguments.gray_chance,
        seed=arguments.seed,
        chunk=arguments.chunk,
    )
    print(
        f"Training {arguments.model} on {len(crops)} crops of "
        f"{len({crop.identity for crop in crops})} animals from "
        f"{len(set(farms))} farm(s)",
        file=sys.stderr,
    )
    path = train(
        crops,
        arguments.model,
        arguments.out,
        options,
        checkpoint=arguments.checkpoint,
        device=arguments.device,
        farms=farms,
    )
    print(
        f"Saved {path}; benchmark it with --model {arguments.model} --checkpoint {path}"
    )


def _add_training(commands: argparse._SubParsersAction) -> None:
    training = commands.add_parser(
        "train", help="fine-tune an embedding network on cows"
    )
    training.add_argument(
        "manifests",
        type=Path,
        nargs="+",
        help="one manifest per farm; batches hold cows of one farm at a time",
    )
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
    training.add_argument(
        "--chunk",
        type=int,
        help="pictures through the network at once; smaller saves memory",
    )
    training.add_argument("--grayscale", action="store_true")
    training.add_argument(
        "--gray-chance",
        type=float,
        default=0.0,
        help="share of pictures turned gray at random, e.g. 0.3 for infrared nights",
    )
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
