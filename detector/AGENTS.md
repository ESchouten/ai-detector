# Detector engineering rules

Scope: the Python detector, its schemas, tests, packaging, and documentation. The web application is outside the current rewrite. Preserve its on-disk event contract.

- Read ARCHITECTURE.md and MIGRATION.md before changing module boundaries or public behavior. Record intentional behavior changes there.
- Domain code owns event rules and data. It must not import configuration models, adapters, application services, network libraries, or inference frameworks.
- Application code depends on domain types and narrow ports. Bootstrap constructs concrete integrations. Imports never read configuration, create directories, configure logging, start threads, or make network requests.
- Validate external configuration once. Internal functions accept precise types and established invariants. Do not add speculative guards, generic factories, service locators, or wrappers that only forward calls.
- Distinguish absent configuration, invalid configuration, rejected detections, unavailable validation, and failed delivery. Never convert a failure into a successful empty result.
- Catch expected integration failures at their boundary. Broad exception handling is reserved for supervising a worker, releasing resources, or isolating independent exporters; the failure must remain observable.
- One thread owns event aggregation. Bound queued events. Observe worker failures, flush eligible events at EOF/shutdown, and release captures, subprocesses, and executors explicitly.
- Keep configuration and event metadata compatible with the documented schema. Schema generation must be deterministic and independent of local config or hardware.
- Tests describe public behavior and real integration contracts. Do not construct partially initialized objects with __new__, monkeypatch private application methods, weaken assertions to fit code, or use sleeps to test domain time rules.
- Every new abstraction must isolate an actual I/O boundary or simplify a current use case. Prefer ordinary functions, dataclasses, and explicit constructors.
- Keep the README's reading path and change-to-test map current. Tests follow production responsibilities; subprocess and model-building helpers belong in tests/support. Module moves must update imports, patch targets, mutation selectors and executable smoke entrypoints together.
- Run Ruff, formatting checks, ty, the behavioral suite, schema checks, and the local media/reference-flow checks. State which hardware-specific checks were not executable locally.
- Never use real camera credentials, AI keys, Telegram bots, or webhooks in tests. Use temporary directories for runtime output.
- Remove superseded implementation and update documentation when a replacement is verified. Do not leave permanent migration shims.
