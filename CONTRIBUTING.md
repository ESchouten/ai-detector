# Working on AI Detector

The repository has three deployable responsibilities. The web app owns setup and reviewing recordings; the detector owns inference and event rules; distribution assembles those programs into one download. They exchange `config.json` and the detection archive, not Python imports or an internal HTTP API.

| Start here | Responsibility | Checks |
| --- | --- | --- |
| [Web architecture](web/ARCHITECTURE.md) | Svelte pages, validated configuration, process control, archive playback | `cd web && pnpm quality && pnpm build && pnpm test:production` |
| [Detector reading path](detector/README.md) | Sources, models, events, validation and delivery | VS Code **Detector: check** or the commands in its README |
| [Distribution](distribution/README.md) | Installers, update feeds, native launchers and release smoke tests | VS Code **Distribution: tests**, including its isolated release dependencies |
| [System overview](SYSTEM_OVERVIEW.md) | How the running programs and files connect | Update when a process boundary or public contract changes |

## Local setup

Use uv, Node, pnpm and Bun. `distribution/toolchain.json` pins Node, Bun and the other desktop tools, and `web/package.json` pins pnpm. Python 3.12 is the minimum supported version; uv selects the exact development and build version from [`detector/.python-version`](detector/.python-version). CI and the downloadable Windows CUDA runtime use the same pin. From the repository root:

```sh
uv sync --project detector --locked --extra default
pnpm --dir web install --frozen-lockfile
```

Then run **Repository: check** in VS Code (**Run Build Task**). It runs detector checks, distribution lint/tests, web quality checks, the production build and HTTP smoke tests. Each check is also an independent task for a faster edit loop. The distribution task supplies its additional Python dependencies automatically; desktop TypeScript checks are included in web quality checks. Native Windows tray tests and the .NET SDK commands are described in the distribution guide. Tests use temporary files and generated media; they do not need farm cameras or notification credentials.

Run the web app with a disposable data folder while developing setup or configuration changes:

```sh
AIDETECTOR_DATA_DIR=/tmp/ai-detector-development pnpm --dir web dev
```

Without a configured detector executable the web app is a frontend for separately managed detection. To exercise managed startup, set `AIDETECTOR_EXECUTABLE` to a built detector. Never use real notification destinations in automated tests.

To build a complete desktop preview with the same stages used in CI, follow the [single-command build](distribution/README.md#local-builds-and-tests).

## Repository map

| Location | Owns |
| --- | --- |
| `detector/` | Python application, runtime dependencies, tests and architecture contracts |
| `web/` | Browser application, server services, desktop web runtime and their checks |
| `config/` | Generated shared schemas, bundled presets and configuration guidance |
| `distribution/` | Build stages, native launchers, installers, toolchain pins and packaging tests |
| `ruff.toml` | Shared Python formatting, import and complexity rules |
| `.github/` | CI orchestration using those same build stages and quality tools |
| `.vscode/` | Editor tasks and debug entry points into the existing commands |

Python tools discover the root `ruff.toml` from either the repository or component directory. Do not copy its rules into another project file. The [configuration guide](config/README.md) identifies each settings file's owner; the [distribution guide](distribution/README.md) identifies build outputs and tool versions.

## Keeping packages current

[Dependabot](.github/dependabot.yml) opens one pull request every Monday with the minor and patch updates of the web packages, the release tools, the Windows launcher's packages and the GitHub Actions, and one for the detector's lock file. Merge them when the checks pass. Updates of PyTorch, ONNX Runtime, Ultralytics or OpenCV also need a look on real hardware, as the last paragraph of this guide says: CI has no graphics card.

Major versions are not proposed. List them with `pnpm --dir web outdated` and `uv lock --project detector --upgrade --dry-run`, and take them one at a time. These wait for something else:

| Package | Stays at | Until |
| --- | --- | --- |
| ONNX Runtime GPU in the `nvidia-cuda12` extra | 1.20, the last release that runs on CUDA 12.6 | PyTorch stops building for CUDA 12.6 and that extra goes |
| TensorRT on Windows with NVIDIA | The version pinned in `detector/pyproject.toml` | Someone checks a newer one on an NVIDIA computer |
| NumPy on macOS | 2.3, the last that coremltools 9 converts models with | coremltools converts with NumPy 2.4 |
| `@sveltejs/kit`, `@sveltejs/adapter-node`, `devalue` | SvelteKit 2 | `@jesterkit/exe-sveltekit`, which builds the desktop executable, supports SvelteKit 3 |
| `typescript` | 6 | `svelte-check` and `typescript-eslint` accept 7 |
| `@types/node`, `@types/bun` | Node 24 and the Bun version in `distribution/toolchain.json` | Those runtimes move |
| `@tanstack/table-core`, `sveltekit-superforms`, `layerchart` | What the components in `web/src/lib/components/ui` are written for | shadcn-svelte publishes them for the newer versions |
| Container base images in the `Dockerfile` | Their pinned digests | Someone qualifies a newer one, as the comments there say |

An update of Ultralytics deserves a comparison of detections before and after on recorded pictures: between 8.4.80 and 8.4.177 it changed which head of a model it runs by default, how a prepared backend is reused and how models are downloaded, each without a failing test of its own.

## Changing a feature

Follow one request through the relevant feature before adding files: the [web architecture](web/ARCHITECTURE.md) and the [detector reading path](detector/README.md#working-on-it) show the route. Keep new behavior with its existing owner; create a module when it isolates a real responsibility, not to match a diagram.

The Python-generated schemas in `config/` are shared contracts. After changing Python configuration or archive metadata, regenerate them as the [configuration guide](config/README.md#who-owns-which-file) describes, and check both applications.

Keep `web/src/lib/components/ui` as published by shadcn-svelte, including components the app does not use yet, and change the look outside that folder: with classes at the call site, or as [appearance and the shadcn components](web/ARCHITECTURE.md#appearance-and-the-shadcn-components) describes. ESLint skips the folder; formatting and Svelte checks still cover it, so an update may need its newer dependencies installed before `pnpm check` passes.

The interface is translated (English, Dutch, German, French). Write text in `web/src` in sentences a farmer would understand; after adding or changing it, run `pnpm --dir web i18n` and translate the new entries. [Languages](web/ARCHITECTURE.md#languages) in the web architecture guide has the rules that keep text translatable and what stays in English.

Before handing off a change, state what behavior changed, which tests establish it, and what still requires a target machine. A passing CPU smoke test does not establish GPU acceleration, live camera behavior or signed installer support.
