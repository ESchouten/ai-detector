# Configuration and presets

## Who owns which file

Settings live in the application's data folder, outside the installed program. The [distribution guide](../distribution/README.md#installation-and-data) lists its location per system.

| File or folder | Holds | Owner |
| --- | --- | --- |
| `config.json` | Sources, models, event rules, verification and delivery | Python [configuration models](../detector/src/aidetector/configuration.py); the web application validates with their generated schema |
| `app.json` | Camera identities and names, setup progress, saved recipients and AI connections, and `language`. Also paired devices and `monitoring` (whether monitoring resumes at start), which stay with the installation and are never exported or recovered | Web [schema](../web/src/lib/schema.ts) and [settings store](../web/src/lib/server/configuration/store.ts) |
| `presets/` | Optional presets of this installation | Web [preset files](../web/src/lib/server/configuration/preset-files.ts) |

`config.schema.json` and `metadata.schema.json` in this folder are generated. Change the Python models, then from the repository root:

```sh
uv run --project detector --no-sync generate-schema --output-directory config
pnpm --dir web schema:generate
```

Add `--check` to the first command, or run `pnpm --dir web schema:check`, to verify without writing; CI runs both checks. The web application never keeps a second detector schema.

## Presets

Each JSON file in [detector/](detector/) is a preset. The filename without `.json` is its ID, and dashes, underscores and spaces separate the words of its name: `cow-catcher.json` appears as **Cow Catcher**. There is no catalogue, description or default; adding a bundled preset means adding a file.

A preset contains only detector settings: model, watched classes, event rules and delivery defaults. Cameras are added first, and selecting them in the detector step supplies `detection.source`. Everything else follows the [configuration schema](config.schema.json).

### Presets of one installation

Create a `presets/` folder in the data folder, beside `config.json`, and put detector JSON files directly in it; then reload the editor. The data folder is shown on the monitoring status page under **Technical details**.

A local folder replaces the bundled and the published choices: copy the bundled files into it to keep them. Such copies are yours, and nothing published updates them. An empty folder gives an empty list, and no folder gives the bundled presets. `AIDETECTOR_PRESETS` names another folder, which must exist. An invalid file is reported by name; it is never replaced by something else.

For example, `presets/entrance-activity.json` adds **Entrance Activity**:

```json
{
  "yolo": {
    "model": "yolo11n.pt",
    "confidence": { "person": 0.6 },
    "frames_min": 3
  },
  "exporters": { "disk": { "directory": "entrance" } }
}
```

A preset can prepare verification without choosing a provider. The question waits until an AI connection is saved:

```json
{
  "vlm": {
    "key": null,
    "prompt": "Does the video show a person entering the building?",
    "strategy": "VIDEO"
  }
}
```

## Saved detectors

Applying a preset copies its settings into the saved detector, which then follows that preset. Before monitoring starts, and once a day while the application runs, the application looks for the preset's newest version: in the installation's own `presets/` folder when it has one, otherwise in [`config/detector/` on the `main` branch](https://github.com/ESchouten/ai-detector/tree/main/config/detector). When its detection settings have changed, as when it names a newer model, and that model can be downloaded, the detector takes them and monitoring restarts with them. Its cameras, delivery settings, AI connection and question stay as saved. Without an internet connection nothing changes, and renaming or removing a preset file changes nothing that is saved.

Publishing is therefore a change to a file in `config/detector/` on `main`: every installation that follows that preset has it within a day, without a new release. A preset that some version of the application cannot use is ignored by that version, and the released application reads the same folder when a detector is added. Test builds and development keep the presets they were built with. `AIDETECTOR_PRESETS_URL` names another folder listing in GitHub's format, or nothing to switch this off.

- A detector keeps following its preset when its own name, cameras or delivery settings change. Changing its detection settings, in the editor, under Advanced or in `config.json` itself, makes it a custom detector: it keeps its settings and no preset updates it. Choosing the preset again makes it follow once more.
- `presetVersion` in `app.json` records which detection settings the preset gave. It is how the application tells a detector that still follows from one that was changed.
- A new detector takes the preset's recording and delivery defaults. An existing detector keeps its delivery settings when another preset is applied.
- A detector can watch several cameras, and a camera can be watched by several detectors. Telegram recipients are assigned to detectors and apply to every camera of that detector.
- Saving an AI connection fills in the detectors whose preset question was waiting for one. Detectors that already have a model or connection are not reassigned. Turning verification off clears the keys and keeps questions and models.
