# Workflows

Use **Application download** for desktop installers and automatic updates. Use **Container releases** for independently managed Docker/Compose deployments, including Jetson.

| Workflow | When it runs | Responsibility |
| --- | --- | --- |
| [Application download](workflows/application.yml) | `app/v*`, `app/test-*`, manual | Check all three OSes, build the matching NVIDIA image and native applications, smoke-test packages, then publish signed stable or preview updates. |
| [Container releases](workflows/containers.yml) | `detector/v*`, `web/v*`, manual | Publish detector and web images; retain amd64/arm64 and the separate JetPack 6 detector image. |
| [Detector Tests](workflows/detector-tests.yml) | Relevant branch pushes/PRs, manual, application workflow | Python/OS compatibility, branch coverage, architecture, schemas, complexity and domain mutation reports. Static checks run once. |
| [Web and setup tests](workflows/web-tests.yml) | Relevant branch pushes/PRs, manual, application workflow | Behavioral tests on Linux, Windows and Mac; static, production server and Compose checks on Linux. |
| [Desktop distribution tests](workflows/distribution-tests.yml) | Relevant branch pushes/PRs, manual | Workflow lint, native launchers, compiled web lifecycle, installers and framework update/delta tests. |

The three test workflows respond to branch pushes rather than release tags. Application releases also call the detector and web test workflows for the exact release commit. Their concurrency groups include the calling workflow, so normal CI cannot cancel a release's checks. Mutation testing runs on PRs, the default branch and manual runs; feature-branch and release-tag pushes still run the normal tests.

Application publishing is serialized across stable and preview releases because both update the combined channel feed. Detector and web checks complete before the expensive builds start. The NVIDIA image and the Windows, macOS and Linux binaries then build in parallel. Installer assembly waits for the tested binaries and the image digest, so every installer still names the exact matching NVIDIA image. Only publication waits for all installers to succeed. Keep this workflow's filename and run-number sequence: internal update versions depend on it.

Web schema, formatting, lint, type and dependency checks run once per invocation, on Linux. Web behavior and native packaging/lifecycle tests still run on all three OSes. Distribution lint also runs once per workflow, on Linux; distribution tests cover Bun and native binaries while the web workflow owns Node/TypeScript checks.

Tool versions live in [distribution/toolchain.json](../distribution/toolchain.json), [web/package.json](../web/package.json), and the Python/NuGet lockfiles. Shared actions have narrow responsibilities:

- [setup-web](actions/setup-web/action.yml): Node, pnpm, Bun, dependency caching and locked web installation. Web tests do not install Python or .NET build tools.
- [setup-distribution](actions/setup-distribution/action.yml): Python/uv, build dependencies, optional .NET and the shared web setup. Installer assembly skips web tools because it receives tested binaries.
- [build-launcher](actions/build-launcher/action.yml): native launcher compilation, Windows tray tests and optional portable .NET update tests. Both desktop CI and application builds use it.
- [setup-container](actions/setup-container/action.yml): Buildx and registry login for both application and container publishing.

Build commands remain in [distribution/build.py](../distribution/build.py), usable locally and in CI. Docker builds share the existing Dockerfiles and use Docker's metadata action for version tags. Release assets are already compressed, so artifact upload does not compress them again.

## Container releases

Pushing `detector/vX.Y.Z` publishes only the detector; `web/vX.Y.Z` publishes only the web image. Stable tags also update `latest`, while prerelease tags keep their versioned image without moving `latest`. The detector's native amd64 and arm64 jobs combine into one multi-architecture image; JetPack 6 retains its separate `-jetpack6` suffix, including `latest-jetpack6`.

For development, select a branch in **Run workflow**, then choose `all`, `detector` or `web`. Branch runs publish branch-named images without changing `latest`. With `all`, the detector and web builds run independently. Container publication is serialized to avoid concurrent writes to shared tags.

The old standalone detector/web workflows are removed. Component tags now publish containers only; desktop executables are distributed through the complete application. Developers can still build individual components locally with `distribution/build.py`. No GitHub releases or assets are created by the container workflow, and existing Compose image names stay the same.

## Application artifacts

The internal `native-build-PLATFORM` artifacts transfer tested binaries between build and packaging jobs, using tar to preserve executable permissions and macOS framework symlinks. They expire after one day.

Each `AI-Detector-PLATFORM` artifact contains only its installer: a Mac `.dmg`, Windows setup `.exe`, or Linux `.deb`. GitHub wraps this single file in a ZIP when downloaded from Actions. For application releases, the publishing job wraps only the Windows setup EXE in a ZIP; Mac and Linux installers are attached directly. This keeps the Windows ZIP download without nesting ZIPs in Actions artifacts or publishing duplicate EXE and ZIP downloads. Mac and Windows `update-files-PLATFORM` artifacts carry the update packages, deltas and signed feeds. The publishing job attaches the required update packages/deltas alongside the three downloads, and publishes feeds only to their dedicated update releases. Linux needs no updater artifact. Application releases have no portable application ZIPs or separate `.sha256` files; integrity checks remain part of the signed update metadata.

## Debugging a failure

Open the first failing named step, rather than the later skipped jobs. Each platform remains visible when another fails. Use `gh run view RUN_ID --log-failed` to retrieve the failing logs.

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

Packaging tests need `distribution/requirements.txt`. Platform-specific tests explain missing prerequisites when skipped; set `SPARKLE_SDK` or `WINDOWS_LAUNCHER` to the built tools to exercise real signed deltas. See [distribution/README.md](../distribution/README.md) for complete local build commands and [detector/README.md](../detector/README.md) for Python checks.

The first preview with update support must be installed manually. New launchers use **app-update-channels** and expose **Include preview updates** in the native menu. The separate **app-preview-updates** and **app-updates** feeds remain for older launchers and delta generation. A shared internal build version orders releases across both channels. Published tags and versions are immutable. Failed runs can be retried, but a published build needs a new tag/run. Container releases do not change the application's update feeds.
