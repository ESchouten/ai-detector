# Detector maintainability assessment

Historical assessment: source paths, measurements and recommendations describe the recorded snapshot. Start with the [current contributor guide](../../../CONTRIBUTING.md) for the maintained implementation.

Reviewed on 2026-09-22. Scope: all 36 Python source modules, detector tests and development tools, schemas, packaging and detector workflows. The web application, live configuration and existing archives are outside this cleanup. [README.md](../../../detector/README.md#start-contributing) is the contributor entry point; [ARCHITECTURE.md](../../../detector/ARCHITECTURE.md) explains the system; [QUALITY.md](../../../detector/QUALITY.md) contains measurements and commands; [AUDIT.md](AUDIT.md) preserves verification history.

## Architecture and code placement

The detector uses a small hexagonal architecture. Domain objects own event decisions, application use cases coordinate them through narrow contracts, adapters perform I/O, bootstrap constructs the concrete graph, and runtime owns concurrent execution. This division fits the existing event-processing bounded context.

Keep these responsibilities visible in the current packages. An additional `entities`, `usecases`, `interfaces` or `infrastructure` hierarchy would mostly rename the same concepts and increase navigation. The application already has two named use cases: `DetectionPipeline.process` and `EventDelivery.deliver`.

| Location | Responsibility and placement decision |
| --- | --- |
| `domain/models.py` | Observations, event records, bounding geometry and explicit validation outcomes. No archive paths, SDK calls or clocks. |
| `domain/events.py` | Single-owner event windows, source isolation, timeout boundaries and flushing. State is deterministic, with time supplied by callers. |
| `domain/policy.py` | Confidence eligibility, accepted-event cooldown and destination policy. These rules belong with the domain rather than exporters. |
| `application/pipeline.py`, `delivery.py` | Detection/event assembly and ordered validation/delivery. Failures, rejections, disabled verification and cooldown skips remain distinct. |
| `application/ports.py` | Boundary contracts and source batches. Keeping the five small protocols together is a navigation choice; lifecycle contracts describe what runtime consumes, without implementing threading here. |
| `configuration.py` | External schema, validation and normalization. Kept at the package boundary, independent of domain rules and inference setup. Its size reflects the public configuration surface, not multiple runtime responsibilities. |
| `bootstrap.py` | Explicit composition and configuration projection. Adding an adapter requires visible wiring rather than a registry, container or discovery framework. |
| `runtime.py` | Workers, bounded queues, supervision, stop requests and draining. Acquisition and delivery retain separate state owners. |
| `cli.py`, `schema.py`, entrypoints, `version.py` | User commands, exit status, schema production and build metadata. Early CLI returns are clearer than forwarding-only dispatch helpers. |
| `adapters/sources/` | `files.py` owns finite media time; `streams.py` owns shared live acquisition and independent subscriptions. Related pool/subscription classes stay together. |
| `adapters/health.py` | Timed health requests have their own supervised lifecycle, separate from detection-event exports. |
| `adapters/inference/` | `model_assets.py` resolves assets, `onnx.py` owns provider lifetime, and `yolo.py` integrates inference. ONNX setup receives provider settings and model requirements, never the application's detector/exporter tree. |
| `adapters/media/` | `images.py` owns image operations, `video.py` stages and encodes video, and `event_media.py` reuses event encodings across destinations. The package defines their shared `MediaError`. |
| `adapters/exporters/` | Disk publication and its public `archive_metadata.py` projection sit beside Telegram and webhook destinations. A local publication function owns timestamp collisions and final rename separately from writing media. No common exporter superclass is needed. |
| `adapters/http.py` | Bounded HTTP transport shared by event destinations and health monitoring. Destination-specific payloads and response contracts stay in the exporters. |
| `adapters/vlm.py` | Provider requests, strict answers, retries and fallback. Configuration, model and attempt loops express three real choices; another retry abstraction is unnecessary. |
| `tools/quality_report.py`, `tests/` | Development analysis and behavioral evidence. Tests mirror domain, application and adapter responsibilities; subprocess and model helpers live in `tests/support/`. Whole-application checks remain at the test root. |

Sources, inference, exporters and media each form a cohesive group. Grouping gives developers a local reading path while health, shared HTTP transport and VLM verification retain direct module names. `SourceConfig` and `TelegramConfig` identify their concrete responsibilities; the public JSON keys remain unchanged. Small domain models, policies, application ports and runtime supervision stay together. No forwarding imports, generic registries or additional architectural layers were introduced. Import contracts reject cycles and dependencies between sources, inference and exporters, including indirect paths through shared modules.

## Principle-by-principle assessment

These judgments use current callers, contracts and behavioral tests, not a composite quality score or a claim of an author's endorsement.

| Principle | Evidence and interpretation |
| --- | --- |
| Clean / Hexagonal Architecture | Runtime invokes application entrypoints; outgoing operations use application-owned protocols; adapters translate integration details. Five Import Linter contracts plus core dependency/cycle tests enforce import direction and adapter-group independence, including type-checking-only imports. |
| DRY | Event timing, cooldown acceptance and destination eligibility each have one rule owner. Shared HTTP, geometry, media caches and camera acquisition serve multiple actual consumers. Similar transport payloads and input/output threshold decisions remain separate where their contracts differ. |
| KISS | Ordinary dataclasses, functions, protocols and explicit constructors explain the graph. Archive media writing and publication are named operations; unexpected delivery failures retain only the first exception that will propagate. |
| YAGNI | No repository layer, domain-event bus, generic worker hierarchy, service locator or dependency-injection framework. No interface is added solely because a class exists. |
| SRP | The ownership table above separates policy, orchestration, transport, encoding, lifecycle and composition. ONNX helpers no longer traverse application-wide configuration. |
| OCP | An exporter or verifier can implement an existing port without changing delivery orchestration. Configuration, schema and bootstrap still change to expose a supported integration; avoiding all edits would require unnecessary registration machinery. |
| LSP | Substitutes must preserve source identity, chronological batches, borrowed-data lifetime, expected exceptions and cleanup semantics. File/live-source, real YOLO, provider, exporter and runtime tests exercise those contracts. Type signatures alone are insufficient. |
| ISP | Detection, validation and export each expose one operation. Source and health ports expose only the operations their consumers use. The source generator supports explicit close because runtime actually requires it. |
| DIP | Application code depends on its own protocols and domain types; bootstrap supplies concrete adapters. Domain rules perform no I/O. The explicit static NumPy annotation tradeoff is described below. |
| Separation of Concerns | Domain decisions do not choose archive directories or provider options. Adapters translate schemas and failures; runtime supervises; bootstrap supplies resources and settings. |
| Modularity | Import cycles are rejected. A new exporter, event-rule change and inference replacement have documented edit boundaries in QUALITY.md. Provider settings now cross the bootstrap/ONNX boundary as a small immutable input. |
| Boy Scout Rule | This pass removes unnecessary failure storage, narrows a broad input, separates archive publication, clarifies port contracts, closes the annotation-import enforcement gap, separates verifier tests and avoids installing development tools for runtime-only source users. Existing behavior and public schemas are preserved. |

## Cleanup decisions

`inference_runtime` takes `OnnxConfig`, a tuple of `ModelRequirements(path, image_size, batch_size)`, and the build type. Bootstrap owns that projection. TensorRT profile computation remains inside the provider adapter and runs once per setup. This record isolates a real boundary; it is not a second application configuration hierarchy.

`DiskExporter._write_event` prepares the archive's media. `_publish_event` chooses a collision-free timestamp, writes matching metadata and renames the completed directory. Both remain in the storage adapter and share its existing error/cleanup boundary. Real-media tests cover duplicate timestamps, a competing archive appearing at rename, and publication failure cleanup.

`EventDelivery` retains the first unexpected exception, logs each failing destination, and attempts all independent destinations before re-raising that exact exception. The previous exception list was never otherwise consumed. Its existing multi-failure test now verifies identity as well as ordering and later success.

The verifier keeps explicit retry/fallback loops. Extracting them solely to lower nesting would add parameters or change failure diagnostics. Likewise, separate file/live acquisition, ordered delivery, cache keys and SDK cleanup scopes represent required behavior. Broad exception handlers remain only where supervision, cleanup or independent-destination isolation requires them; failures remain observable.

Contributor-facing contracts are explicit at their definitions: images are borrowed read-only BGR arrays, completed events are nonempty and chronological, and `SourceBatch.advance_to` advances the event clock after buffered frames are processed. Bootstrap helpers accept only source/exporter settings. Processing and delivery logs carry safe detector ordinals; the runtime restores a reused caller thread's name on exit. No new wrapper, defensive validation or runtime abstraction was needed.

Architecture tests compare the filesystem with the discovered import graph so a missing package initializer cannot hide code from dependency checks. Source-only and disk-only tests now live beside their adapters, while the root reference flow remains a small cross-layer example. HTTP status/exception and Telegram response failures have explicit tests, as does successful full-frame archiving. VS Code tasks run the existing checks, and its debug profile steps through the offline reference flow.

## Deliberate tradeoffs and verification limits

- **Domain records have static NumPy coupling.** `NDArray[np.uint8]` appears under `TYPE_CHECKING` to describe image data. Domain imports load no NumPy and domain rules never inspect pixels. This is not complete type-level library independence. Replacing useful types with `object`, pervasive payload generics or an image registry would add complexity without serving a current use case.
- **Records are shallowly immutable.** Arrays and mappings are borrowed as read-only values. Shared capture publishes read-only arrays; inference creates score mappings and rendering copies before drawing. Deep-copying every frame would increase memory and processing cost.
- **Active footage has no byte budget.** Duration, unread retention and pending-event counts are bounded, but memory also depends on image size and input rate. Completed events and encoded variants are released; spooling active footage would require a retention/performance decision.
- **Inference setup is process-scoped.** Ultralytics predictor preparation and the temporary ONNX session hook support one application runtime per process. Their lifetime and failure restoration have real SDK contract tests.
- **Optional detection is supported.** Without YOLO, the pipeline emits the latest frame directly. Its unused assembler stays empty, avoiding a second hierarchy or conditional resource ownership.
- **Platform and service checks have limits.** Local CPU ONNX, generated Torch models, fake Windows ML contracts and macOS packaging are verifiable here. They do not establish native Windows/CUDA/Jetson operation, model accuracy or production service availability. GPU images also inherit base-image and driver constraints.
- **Automated architecture checks are partial.** Structural checks include type-checking imports with the explicit domain-model NumPy allowance, but cannot establish semantic responsibility or arbitrary dynamic dependencies. Mutation testing skips decorated properties. Neither passing checks nor lower complexity proves universal correctness.

## Ongoing review

Validate external input once, give mutable state and resources one owner, and keep integration details at their boundary. For every guard or abstraction, identify the actual failure or current consumer it serves. Keep tests focused on externally visible outcomes, ownership and failure alternatives.

Run the required lint, formatting, typing, architecture, schema and behavioral checks. Inspect changed complexity and coverage gaps, then exercise affected packages. Keep historical runs in AUDIT.md and current results in QUALITY.md so this assessment remains about the present design.
