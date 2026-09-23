# Working on AI Detector

The repository has three deployable responsibilities. The web app owns setup and reviewing recordings; the detector owns inference and event rules; distribution assembles those programs into one download. They exchange `config.json` and the detection archive, not Python imports or an internal HTTP API.

| Start here | Responsibility | Checks |
| --- | --- | --- |
| [Web architecture](web/ARCHITECTURE.md) | Svelte pages, validated configuration, process control, archive playback | `cd web && pnpm quality && pnpm build && pnpm test:production` |
| [Detector reading path](detector/README.md) | Sources, models, events, validation and delivery | VS Code **Detector: check** or the commands in its README |
| [Distribution](distribution/README.md) | Native ZIP layouts, boot setup and release smoke tests | VS Code **Distribution: tests**, including its isolated release dependencies |
| [System overview](SYSTEM_OVERVIEW.md) | How the running programs and files connect | Update when a process boundary or public contract changes |

## Local setup

Use Python 3.11 or 3.12 for development, uv, Node 24, pnpm 9.15.9 and Bun 1.3.9. Release builds use Python 3.11. The shared desktop toolchain is recorded in `distribution/toolchain.json`. From the repository root:

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

To build a complete desktop preview with the same stages used in CI, follow the [single-command build](distribution/README.md#local-builds-and-tests). The current contributor guides are authoritative; [historical assessments](docs/history/README.md) preserve earlier evidence and decisions.

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
| `docs/history/` | Dated assessments; not current setup instructions or pending work |

Python tools discover the root `ruff.toml` from either the repository or component directory. Do not copy its rules into another project file. The [configuration guide](config/README.md) identifies each settings file's owner; the [distribution guide](distribution/README.md) identifies build outputs and tool versions.

## Changing a feature

Follow one request through the relevant feature before adding files. In the web app, a page calls a remote handler, which validates the request and delegates to a concrete server service. In the detector, bootstrap connects the pure event rules to adapters. Keep new behavior with its existing owner; create a module when it isolates a real responsibility, not to match a diagram.

The Python-generated schemas in `config/` are shared contracts. After changing Python configuration or archive metadata, regenerate the schemas, run `pnpm --dir web schema:generate`, and check both applications. The web app uses these schemas for Ajv validation and generated TypeScript declarations in `web/src/lib/generated/`. Edit the Python models rather than those generated files. `pnpm --dir web quality` checks that the declarations are current. Web-only labels are stored in `app.json`.

Preserve unused shadcn components. They are an intentional local component library. Prefer composition and small reviewed fixes over wholesale component upgrades. Application complexity checks exclude that upstream library; formatting and Svelte checks still cover it.

Before handing off a change, state what behavior changed, which tests establish it, and what still requires a target machine. A passing CPU smoke test does not establish GPU acceleration, live camera behavior or signed installer support.
