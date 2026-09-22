# Working on AI Detector

The repository has three deployable responsibilities. The web app owns setup and reviewing recordings; the detector owns inference and event rules; distribution assembles those programs into one download. They exchange `config.json` and the detection archive, not Python imports or an internal HTTP API.

| Start here | Responsibility | Checks |
| --- | --- | --- |
| [Web architecture](web/ARCHITECTURE.md) | Svelte pages, validated configuration, process control, archive playback | `cd web && pnpm quality && pnpm build && pnpm test:production` |
| [Detector reading path](detector/README.md) | Sources, models, events, validation and delivery | VS Code **Detector: check** or the commands in its README |
| [Distribution](distribution/README.md) | Native ZIP layouts, boot setup and release smoke tests | `python -m unittest discover -s distribution -p 'test_*.py'` |
| [System overview](SYSTEM_OVERVIEW.md) | How the running programs and files connect | Update when a process boundary or public contract changes |

## Local setup

Use Python 3.11 or 3.12, uv, Node 24 and pnpm 9.15.9. From the repository root:

```sh
uv sync --project detector --locked --extra default
pnpm --dir web install --frozen-lockfile
```

Then run **Repository: check** in VS Code (**Run Build Task**). It runs detector checks, distribution lint/tests, web quality checks, the production build and HTTP smoke tests. Each check is also an independent task for a faster edit loop. Tests use temporary files and generated media; they do not need farm cameras or notification credentials.

Run the web app with a disposable data folder while developing setup or configuration changes:

```sh
AIDETECTOR_DATA_DIR=/tmp/ai-detector-development pnpm --dir web dev
```

Without a configured detector executable the web app is a frontend for separately managed detection. To exercise managed startup, set `AIDETECTOR_EXECUTABLE` to a built detector. Never use real notification destinations in automated tests.

## Changing a feature

Follow one request through the relevant feature before adding files. In the web app, a page calls a remote handler, which validates the request and delegates to a concrete server service. In the detector, bootstrap connects the pure event rules to adapters. Keep new behavior with its existing owner; create a module when it isolates a real responsibility, not to match a diagram.

The Python-generated schemas in `config/` are shared contracts. After changing Python configuration or archive metadata, regenerate the schemas and check both applications. The web app validates against these checked-in files instead of maintaining another detector schema. Web-only labels are stored in `app.json`.

Preserve unused shadcn components. They are an intentional local component library. Prefer composition and small reviewed fixes over wholesale component upgrades. Application complexity checks exclude that upstream library; formatting and Svelte checks still cover it.

Before handing off a change, state what behavior changed, which tests establish it, and what still requires a target machine. A passing CPU smoke test does not establish GPU acceleration, live camera behavior or signed installer support.
