# Workflows

Use **Application download** for the complete application. The standalone workflows serve existing container deployments and developers who run the web app or detector separately.

| Workflow | When it runs | Responsibility |
| --- | --- | --- |
| [Application download](workflows/application.yml) | `app/v*`, `app/test-*`, manual | Check all three OSes, build the matching NVIDIA image and native applications, smoke-test packages, then publish signed stable or preview updates. |
| [Standalone detector releases](workflows/detector.yaml) | `detector/v*`, manual | One image matrix for amd64/arm64 and JetPack; one native matrix for Windows ML/CUDA and Mac detector executables. |
| [Standalone web releases](workflows/web.yml) | `web/v*`, manual | Web container and standalone Windows/Mac executables, built with one native matrix. |
| [Detector Tests](workflows/detector-tests.yml) | Relevant branch pushes/PRs, manual | Python/OS compatibility, branch coverage, architecture, schemas, complexity and domain mutation reports. Static checks run once. |
| [Web and setup tests](workflows/web-tests.yml) | Relevant branch pushes/PRs, manual, application workflow | Source checks on Linux, Windows and Mac; production server and Compose checks on Linux. |
| [Desktop distribution tests](workflows/distribution-tests.yml) | Relevant branch pushes/PRs, manual | Workflow lint, native launchers, compiled web lifecycle, installers and framework update/delta tests. |

The three test workflows respond to branch pushes rather than release tags. Obsolete CI runs are cancelled per ref. Mutation testing runs on PRs, the default branch and manual runs; feature-branch pushes still run the normal tests. Release runs are never cancelled automatically; application publishing is serialized separately for stable and preview feeds. Web checks complete before the expensive application image and packaging jobs start, so a failing Windows test is reported without waiting for a frozen detector.

Tool versions live in [distribution/toolchain.json](../distribution/toolchain.json), [web/package.json](../web/package.json), and the Python/NuGet lockfiles. The shared setup action installs those tools and caches pnpm/uv dependencies. Release assets are already compressed, so artifact upload does not compress them again.

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

The first preview with update support must be installed manually. Later previews use the **app-preview-updates** feed; stable apps use **app-updates**. Published tags and versions are immutable. Failed runs can be retried, but a published build needs a new tag/run. Neither standalone component release changes the application's update feeds.
