# Web application architecture

Start with Add camera: `lib/components/camera-editor.svelte` calls `lib/remote/camera.remote.ts` to find a device and resolve its stream profile. `lib/camera-check.ts` checks a short recording through the `/camera-checks` HTTP route; leaving the editor cancels the fetch and its FFmpeg work. The editor then calls `lib/remote/stream.remote.ts` to save the named camera and its monitoring rules together through `lib/server/configuration/store.ts`. The store validates the canonical detector schema, persists settings and applies changed monitoring settings to the managed detector. The same editor handles initial setup and additional cameras; the editor does not know where files live or how a process is started.

```mermaid
flowchart LR
    UI["Feature pages and editors"] --> Remote["Remote request handlers"]
    UI --> Models["Shared types and configuration validation"]
    Remote --> Config["ConfigurationStore"]
    Remote --> Runtime["ManagedDetector"]
    Remote --> Archive["DetectionArchive"]
    Remote --> Cameras["Camera discovery and connection checks"]
    Cameras --> ONVIF["ONVIF SDK"]
    Cameras --> FFmpeg
    UI --> Routes["Camera-check and media HTTP routes"]
    Routes --> Cameras
    Routes --> Media["Archive media and stream previews"]
    Config --> Files["Staged settings files"]
    Config --> Runtime
    Archive --> Disk["Detection archive"]
    Media --> Disk
    Media --> FFmpeg["FFmpeg subprocess"]
    Runtime --> Process["Native detector; optional Docker override"]
```

## Where a change belongs

| Concern                                       | Read first                                                                    | Regression tests                                                                     |
| --------------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Setup, detector/source/notification edits     | `lib/configuration.ts`, `lib/server/configuration/store.ts`                   | `configuration.test.ts`, `detector-editor.test.ts`                                   |
| Settings persistence and failure recovery     | `lib/server/configuration/files.ts`, `lib/server/json-file.ts`                | `configuration.test.ts`                                                              |
| Starting, stopping, restarting and resuming   | `lib/server/managed-detector.ts`, `lib/server/runtime-platform.ts`            | `runtime.test.ts`                                                                    |
| Archived detections, pagination and playback  | `lib/server/archive.ts`, `lib/server/archive-media.ts`, `lib/detections.ts`   | `archive.test.ts`                                                                    |
| Camera discovery, connection, test recording  | `lib/server/cameras/`, `lib/cameras.ts`, `lib/camera-check.ts`                | `cameras.test.ts`, `camera-check.test.ts`, `production/camera-cancellation.test.mjs` |
| Camera and alert assignment                   | `lib/server/configuration/cameras.ts`                                         | `camera-configuration.test.ts`, `telegram.test.ts`                                   |
| Operational readiness                         | `lib/server/runtime-status.ts`, `lib/runtime.ts`                              | `runtime-status.test.ts`, `runtime.test.ts`                                          |
| Camera preview lifetime and FFmpeg resolution | `lib/server/stream-preview.ts`, `lib/server/ffmpeg.ts`                        | `preview.test.ts`                                                                    |
| Editable form state                           | `lib/components/camera-editor.svelte` and the feature's `add/*-editor.svelte` | Draft-helper tests plus browser verification                                         |
| Dependency direction                          | `.dependency-cruiser.cjs`                                                     | `architecture.test.ts` deliberately violates the rules                               |

Paths in the table are relative to `src/` (code) or `tests/` (tests); `.dependency-cruiser.cjs` is at the web project root. `lib/server/configuration/index.ts` is the composition point for the singleton store; `lib/server/detector-service.ts` owns the singleton runtime. Other services accept their dependencies explicitly and can be tested with Node's test runner. There is no container or generic repository framework.

`node-server.mjs` starts the official Node adapter with the local HTTP transport configured. Use `pnpm start`; HTTPS reverse proxies supply an explicit `ORIGIN` (see the README). `tests/production/` tests the built server, separately from the fast source tests.

## Boundaries and ownership

- Shared types describe configuration, runtime status and archive records. Shared configuration validation uses Ajv with the Python-generated JSON schema. Valibot validates web-only request fields.
- Remote handlers own SvelteKit request validation, redirects and translating expected input errors. They call server services directly, not other remote handlers.
- `ConfigurationStore` serializes reads, edits, persistence and runtime application in one web process. Changed detector settings are staged together with their metadata; ordinary replacement failures restore the previous metadata before rejecting the save. This is not a cross-process lock or a power-loss-safe transaction; do not run multiple web writers against the same data folder.
- `ManagedDetector` serializes lifecycle commands. Stop cancels queued startup work, child checks finish before temporary files are deleted, and process output is bounded and redacted. Polling observes state; it does not create processes.
- `hooks.server.ts` initializes monitoring during server startup, independently of browser requests. Automatic mode selects the bundled native runtime. Packaged relaunch/quit and installer lifecycle belong in `distribution/`, not request handlers.
- `RuntimeProgress` consumes the detector’s versioned status records. A spawned process is not a ready camera: every configured rule must report completed processing, frames must remain fresh, and recording failures remain attributed to their own destinations. Human logs are diagnostic text, never the readiness protocol.
- Camera discovery uses the ONVIF SDK; FFmpeg checks actual recording and playback. Temporary checks expire after 15 minutes, are bounded, and use opaque URLs. Saved camera previews use stable IDs; credentials never belong in navigation URLs.
- Camera edits preserve IDs, existing rules and alert relationships unless the user changes them. Alert assignment can split a shared rule so a recipient only receives selected cameras.
- Each stream preview owns its FFmpeg child until the child closes. Client disconnects, read timeouts and EOF all release it; a force-kill deadline survives closing the HTTP response.
- Archive reads validate metadata and confine decoded paths and symbolic links to the archive. Missing files are different from malformed records or I/O failures. Videos stream with byte ranges rather than loading into memory in full. The card identity includes category, stage and timestamp; overlapping offset pages are deduplicated when new events arrive.
- Remote command failures are SvelteKit `HttpError` objects. `lib/remote-errors.ts` reads their public message for actionable feedback instead of replacing expected errors with a generic message.
- Editor drafts are separate from saved configuration. Incomplete advanced JSON never becomes the basic form's live object. Snapshot detectors keep their absent/null YOLO configuration.

There are no separate domain/use-case/port folders here because this application primarily coordinates files and processes. Concrete services and small shared models express the current boundaries without mirroring the detector's richer event domain.

## Settings save boundary

Camera setup proof lives with camera metadata: picture confirmation, recording-location check, alert choice and completion. Connection metadata contains only a safe ONVIF endpoint/profile, never another copy of login credentials. Archive checks copy and decode a temporary setup clip at the configured location, remove it afterward and publish no detection event. Completion is tied to current rule settings and checked against current runtime state inside the serialized save operation; persisted completion is not a live health claim.

Telegram pairing is a bounded local interaction in `lib/server/telegram-pairing.ts`; its separate session identifier and one-use link code expire after five minutes. Token validation, webhook inspection and Telegram requests remain in `lib/server/telegram.ts`. Polling and QR generation do not hold the configuration write queue. The browser lifetime helper retires late responses and cancels abandoned sessions. Existing recipients reuse the camera/alert save boundary; unchanged credentials do not require a repeated receipt confirmation. Dedicated-bot automatic pairing owns its update filter, while manually entered destinations remain available for bots managed elsewhere. No manager token or hosted delivery service is included.

Validation precedes any replacement: the shared schema checks every save, and a managed detector validates changed, nonempty detector settings. When detector settings change, `configuration/files.ts` stages both new JSON files and the exact previous `app.json` bytes beside their destinations. It replaces `app.json` first, then `config.json`, using a rename for each file. If the second replacement fails, it restores the staged metadata or removes the new `app.json` when none existed before. A failed restore reports both failures and retains the available metadata backup for manual recovery. Temporary-file cleanup failures are logged without changing the outcome of an already committed save.

The pair is **not atomically visible to other processes**, and a crash or power failure between replacements can leave mismatched files. There is no filesystem journal or automatic crash recovery. This deliberately small boundary handles normal I/O rejection without changing the existing file formats; it is not a backup/restore feature.

After both replacements succeed, the saved configuration remains authoritative. A failure applying it or stopping the managed runtime updates runtime failure status and does not reject the successful save, so a client does not retry an already created camera. A save result does not mean monitoring is ready; readiness comes from the runtime's status records. Metadata-only edits use the existing single-file writer, leave `config.json` untouched and skip the detector executable's validation and restart.

`configuration.test.ts` covers validation and staging failures, replacement rollback with existing or missing metadata, rollback and cleanup failures, queue recovery, concurrent camera additions, metadata-only edits, and an actual managed-runtime settings-write failure after a completed save.

## Quality commands

`pnpm quality` runs formatting, ESLint, strict Svelte/TypeScript checking, dependency rules and behavioral tests. Application functions have an ESLint cyclomatic complexity ceiling of 15 and nesting ceiling of 4. Those limits prompt review; they do not prove readability or justify splitting a coherent function just to lower a number. The preserved shadcn library is excluded from the complexity ceiling, not from type or formatting checks.

`pnpm test:coverage` measures executed shared/server code. It does not measure browser interactions or prove platform behavior. `pnpm build` checks the actual adapter output. `pnpm test:production` then exercises the built Node server over HTTP, including setup, origin checks and process shutdown. CI runs all three.

`pnpm architecture:graph` writes `.reports/dependencies.mmd`, a Mermaid graph of server code and its local dependencies; open it beside the source in VS Code. `pnpm architecture:metrics` prints module coupling metrics. The checked rules reject feature cycles, presentation imports from services, Node imports from browser/request code, and unresolved project imports. The negative test proves alias, dynamic import and type-only violations are detected.

Dependency-cruiser uses its own resolver: `tools/dependency-resolution.mjs` supplies SvelteKit's `$lib` alias and TypeScript `.js` imports. Its pinned patch enables the same Svelte async compiler flag used by the app. Remove that patch when the analyzer supports this option directly. SvelteKit virtual imports and third-party package resolution are checked by Svelte/Vite; project import resolution is checked by the dependency graph too.
