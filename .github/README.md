# Workflows

Use **Application download** for desktop installers and automatic updates. Use **Container releases** for independently managed Docker/Compose deployments, including existing Jetson deployments.

| Workflow | When it runs | Responsibility |
| --- | --- | --- |
| [Application download](workflows/application.yml) | `app/v*`, `app/test-*`, manual | Check all three OSes, build the matching NVIDIA image and native applications, smoke-test packages, then publish signed stable or preview updates. |
| [Container releases](workflows/containers.yml) | `detector/v*`, `web/v*`, manual | Test and publish native amd64/arm64 detector and web images. JetPack 6 images are no longer built. |
| [Detector Tests](workflows/detector-tests.yml) | Relevant main pushes/PRs, manual, application/container workflows | Pinned Python 3.12 on all three OSes, branch coverage, architecture, schemas, complexity and domain mutation reports. Static checks run once. |
| [Web and setup tests](workflows/web-tests.yml) | Relevant main pushes/PRs, manual, application/container workflows | Behavioral tests on Linux, Windows and Mac; static, production server and Compose checks on Linux. |
| [Desktop distribution tests](workflows/distribution-tests.yml) | Relevant main pushes/PRs, manual | Workflow lint, native launchers, compiled web lifecycle, installers and framework update/delta tests. |
| [Workflow syntax](workflows/workflow-tests.yml) | Called by distribution, application and container workflows | Validate workflow syntax and embedded shell scripts. |

The three test workflows respond to relevant pull requests and pushes to main. Feature branches can run them manually; release tags trigger their own build workflow. Application and container releases call the detector and web checks for the exact release commit. Their concurrency groups include the calling workflow, so normal CI cannot cancel a release's checks. Mutation testing runs on PRs, the default branch and manual runs; release-tag builds run the normal tests.

Application runs are serialized across stable and preview releases because both update the combined channel feed. After release configuration, native compilation, the NVIDIA image, web/detector checks and a fresh Windows NVIDIA runtime installation test start in parallel. Each installer waits only for its own platform's binaries; Windows and Linux also wait for the image digest for optional Docker mode. macOS packaging has no NVIDIA dependency. The desktop tests for those binaries (launcher, packaging and process lifecycle) run in their own job beside packaging. Publication requires all installers, desktop tests and checks to succeed.

Freezing the detector is the slowest step, and its result depends only on the detector's sources, locked dependencies and build scripts. A preview build therefore first looks for an earlier application build of this repository that froze and smoke-tested the same inputs, downloads that build's binaries, and writes its own version into `aidetector/version.py`, which the freeze keeps as a plain file for this purpose. If none is found, or anything in that path fails, the detector is frozen and smoke-tested as before. Official `app/v*` releases always freeze afresh. Editing `application.yml`, `build.py` or the PyInstaller hooks changes the inputs, so the first build afterwards freezes again. Keep this workflow's filename and run-number sequence: internal update versions depend on it.

Web schema, formatting, lint, type and dependency checks run once per invocation, on Linux. Web behavior and native packaging/lifecycle tests still run on all three OSes. Distribution lint also runs once per workflow, on Linux; distribution tests cover Bun and native binaries while the web workflow owns Node/TypeScript checks.

Python is pinned once in [`detector/.python-version`](../detector/.python-version), shared by development, CI, native builds and the Windows CUDA payload. Other tool versions live in [distribution/toolchain.json](../distribution/toolchain.json), [web/package.json](../web/package.json), and the Python/NuGet lockfiles. Shared actions have narrow responsibilities:

- [setup-web](actions/setup-web/action.yml): Node, pnpm, Bun, dependency caching and locked web installation. Web tests do not install Python or .NET build tools.
- [setup-distribution](actions/setup-distribution/action.yml): Python/uv, build dependencies, optional .NET and the shared web setup. Installer assembly skips web tools because it receives tested binaries.
- [build-launcher](actions/build-launcher/action.yml): native launcher compilation, Windows tray tests and optional portable .NET update tests. Both desktop CI and application builds use it.
- [test-distribution](actions/test-distribution/action.yml): packaging and process lifecycle checks against the compiled web application, shared by desktop CI and application builds.
- [package-application](actions/package-application/action.yml): assemble tested binaries, smoke-test the application, and generate installers and update feeds.
- [setup-container](actions/setup-container/action.yml): Buildx, registry login and disk cleanup when available space is below the requested build budget.

Build commands remain in [distribution/build.py](../distribution/build.py), usable locally and in CI. Docker builds share the existing Dockerfiles and use Docker's metadata action for version tags. Release assets are already compressed, so artifact upload does not compress them again.

## Container releases

Pushing `detector/vX.Y.Z` publishes only the detector; `web/vX.Y.Z` publishes only the web image. Stable tags also update `latest`, while prerelease tags keep their versioned image without moving `latest`. Both components build amd64 and arm64 on native runners. Version tags are published only after both architectures pass their container smoke checks, component tests and workflow lint. JetPack 6 builds and their variant matrix have been removed. Previously published `-jetpack6` images remain available for existing deployments but receive no new builds. The generic ARM64 image is not yet qualified for Orin / JetPack 7.2; see the [detector guide](../detector/README.md#jetson-installations).

For development, select a branch in **Run workflow**, then choose `all`, `detector` or `web`. Branch runs publish branch-named images without changing `latest`. With `all`, the detector and web builds run independently. Container publication is serialized to avoid concurrent writes to shared tags.

The old standalone detector/web workflows are removed. Component tags now publish containers only; desktop executables are distributed through the complete application. Developers can still build individual components locally with `distribution/build.py`. No GitHub releases or assets are created by the container workflow, and existing Compose image names stay the same.

## Application artifacts

The internal `native-build-PLATFORM` artifacts transfer tested binaries between build and packaging jobs, using tar to preserve executable permissions and macOS framework symlinks. They expire after seven days, allowing packaging retries to reuse the same tested binaries. A small `detector-PLATFORM-HASH` marker artifact beside them names the detector inputs that build contains; later preview builds find a reusable detector by that name. [`tested_detector.py`](../distribution/tested_detector.py) accepts a marker only from this repository's own tag or manual application runs, never from a pull request.

Each `AI-Detector-PLATFORM` artifact contains only its installer: a Mac `.dmg`, Windows setup `.exe`, or Linux `.deb`. GitHub wraps this single file in a ZIP when downloaded from Actions. For application releases, the publishing job wraps only the Windows setup EXE in a ZIP; Mac and Linux installers are attached directly. This keeps the Windows ZIP download without nesting ZIPs in Actions artifacts or publishing duplicate EXE and ZIP downloads. Mac and Windows `update-files-PLATFORM` artifacts carry the update packages, deltas and signed feeds. The publishing job attaches the required update packages/deltas alongside the three downloads, and publishes feeds only to their dedicated update releases. Linux needs no updater artifact. Application releases have no portable application ZIPs or separate `.sha256` files; integrity checks remain part of the signed update metadata.

## Debugging a failure

The application build summary links jobs with their results and durations and lists installer artifact sizes. Open the first failing named step, rather than the later skipped jobs. Each platform remains visible when another fails. Failure diagnostics are retained for seven days. Use `gh run view RUN_ID --log-failed` to retrieve the failing logs.

Run the relevant check locally:

```sh
actionlint
pnpm --dir web quality
pnpm --dir web build
pnpm --dir web test:production
uv run --project detector ruff check distribution
python -m unittest discover -s distribution -p 'test_*.py'
dotnet test distribution/windows/update-tests/Update.Tests.csproj --configuration Release
```

Packaging tests need `distribution/requirements.txt`. Platform-specific tests explain missing prerequisites when skipped; set `SPARKLE_SDK` or `WINDOWS_LAUNCHER` to the built tools to exercise signed Mac deltas or Windows full-update packages. See [distribution/README.md](../distribution/README.md) for complete local build commands and [detector/README.md](../detector/README.md) for Python checks.

The first preview with update support must be installed manually. New launchers use **app-update-channels** and expose **Include preview updates** in the native menu. The separate **app-preview-updates** and **app-updates** feeds remain for older launchers and Mac delta generation. Windows publishes full packages because delta reconstruction does not preserve the exact archive bytes authenticated by the signed feed. A shared internal build version orders releases across both channels. Published tags and versions are immutable. Failed runs can be retried, but a published build needs a new tag/run. Container releases do not change the application's update feeds.

Native detector builds start fresh on CI. GitHub's dependency cache cannot be restored across different preview tags, so this workflow does not upload a PyInstaller cache that later previews cannot use. Local builds still reuse PyInstaller's processed libraries; use `distribution/build.py detector --clean` to clear them when debugging. The common build runner prints elapsed time for each external command. Mac delta preparation downloads at most two previous DMGs concurrently, retaining the existing missing-asset fallback. Compare step durations on the next preview to measure the runner-specific gain; no additional acceptance workflow is introduced.
