# Workflows

Use **Application download** for desktop installers and their updates, and **Container releases** for Docker and Compose deployments.

| Workflow | Runs on | Does |
| --- | --- | --- |
| [Application download](workflows/application.yml) | `app/v*`, `app/test-*`, manual | Checks all three systems, builds the matching NVIDIA image and the native applications, tests the packages, then publishes signed official or preview updates. |
| [Container releases](workflows/containers.yml) | `app/v*`, manual | Tests and publishes the amd64 and arm64 image, which holds the web application and the detector it runs. |
| [Detector Tests](workflows/detector-tests.yml) | Relevant pushes to `main` and pull requests, manual, and the two release workflows | Tests on three systems, branch coverage, architecture, schemas, the change report and domain mutation tests. |
| [Web and setup tests](workflows/web-tests.yml) | The same | Unit tests on three systems; static checks, the production server and Compose checks on Linux. |
| [Desktop distribution tests](workflows/distribution-tests.yml) | Relevant pushes to `main` and pull requests, manual | Native launchers, the compiled web process, installers and update packages. |
| [Workflow syntax](workflows/workflow-tests.yml) | Called by the others | Lints workflow files and their embedded scripts. |

A release workflow calls the detector and web checks for the exact commit it releases. Feature branches can run the test workflows by hand.

## Application builds

After the release configuration, these start together: native compilation per system, the NVIDIA image, the web and detector checks, and a real installation of the Windows NVIDIA runtime. Each installer waits only for its own system's binaries; Windows and Linux also wait for the image digest. The desktop tests for those binaries run beside packaging. Publication needs every installer, test and check to succeed. Runs are serialized across official and preview releases because both write the same update feeds.

Freezing the detector is the slowest step, and its result depends only on the detector's sources, its locked dependencies and the build scripts. A preview build therefore first looks for an earlier application build of this repository that froze and smoke-tested the same inputs, takes that build's binaries, and writes its own version into `aidetector/version.py`, which the freeze keeps as a plain file for this purpose. If none is found, or anything on that path fails, it freezes and smoke-tests as usual. Official `app/v*` releases always freeze afresh. Editing `application.yml`, `build.py` or the PyInstaller hooks changes those inputs, so the next build freezes again. [`tested_detector.py`](../distribution/tested_detector.py) accepts an earlier build only from this repository's own tag or manual runs, never from a pull request.

Artifacts of a run:

- `native-build-PLATFORM`: the tested binaries, as a tar to keep executable permissions and macOS symlinks, kept seven days so a packaging retry can reuse them. A small `detector-PLATFORM-HASH` marker beside it names the detector inputs it contains.
- `AI-Detector-PLATFORM`: one installer each, a Mac `.dmg`, a Windows setup `.exe` or a Linux `.deb`.
- `update-files-PLATFORM` (Mac and Windows): update packages, deltas and signed feeds for the publishing job.

A release offers one download per system; the Windows setup EXE is wrapped in a ZIP. Feeds are published only to their dedicated update releases. Tags, versions and retries are covered by the [preview](../distribution/README.md#github-actions-previews) and [release](../distribution/README.md#publishing-a-release) procedures.

## Container releases

`detector/vX.Y.Z` publishes only the detector image and `web/vX.Y.Z` only the web image. Stable tags also move `latest`; prerelease tags do not. Both are built for amd64 and arm64 on native runners, and a tag is published only after both architectures pass their smoke checks, the component's tests and workflow lint. A manual run on a branch publishes branch-named images. JetPack 6 images are no longer built; see [Jetson](../detector/MIGRATION.md#jetson).

## Shared setup

Python is pinned once in [`detector/.python-version`](../detector/.python-version); other tool versions are in [distribution/toolchain.json](../distribution/toolchain.json), [web/package.json](../web/package.json) and the lockfiles. Build commands live in [distribution/build.py](../distribution/build.py) and run the same locally and in CI.

| Action | Does |
| --- | --- |
| [setup-web](actions/setup-web/action.yml) | Node, pnpm, Bun, caches and the locked web installation |
| [setup-distribution](actions/setup-distribution/action.yml) | Python and uv, optional .NET, and the web setup |
| [build-launcher](actions/build-launcher/action.yml) | Compiles the native launcher and runs its tests |
| [test-distribution](actions/test-distribution/action.yml) | Packaging and process lifecycle checks against the compiled web application |
| [package-application](actions/package-application/action.yml) | Assembles tested binaries, smoke-tests the application, creates installers and update feeds |
| [setup-container](actions/setup-container/action.yml) | Buildx, registry login, and disk cleanup when space is short |

## Debugging a failure

The build summary lists each job with its result and duration. Open the first failing step, not the jobs skipped after it; `gh run view RUN_ID --log-failed` prints its log. Failure diagnostics are kept for seven days.

Run the matching check locally:

```sh
actionlint
pnpm --dir web quality
pnpm --dir web build
pnpm --dir web test:production
uv run --project detector ruff check distribution
python -m unittest discover -s distribution -p 'test_*.py'
dotnet test distribution/windows/update-tests/Update.Tests.csproj --configuration Release
```

The packaging tests need `distribution/requirements.txt`. See the [distribution guide](../distribution/README.md#local-builds-and-tests) for complete builds and the [detector guide](../detector/README.md#development-checks) for the Python checks.
