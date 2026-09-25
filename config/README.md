# Configuration and presets

## Settings ownership

User settings live in the application's data directory, outside the installed binaries. The [application guide](../distribution/README.md#installation-and-data) lists its location on each platform.

| File or folder | Purpose | Code owner |
| --- | --- | --- |
| `config.json` | Sources, models, event rules, verification and delivery | Python [configuration models](../detector/src/aidetector/configuration.py); the web app validates with their generated schema |
| `app.json` | Camera identities, labels, setup progress and notification metadata | Web [configuration validation](../web/src/lib/configuration.ts) and [configuration store](../web/src/lib/server/configuration/store.ts) |
| `runtime.json` | Monitoring resume preference and native/Docker selection | Web [managed detector](../web/src/lib/server/managed-detector.ts) |
| `presets/` | Optional installation-specific detector presets | Web [preset files](../web/src/lib/server/configuration/preset-files.ts) |

The `application.json` shipped beside the executable is build metadata, not user settings. Build dependencies and tool versions belong in the component manifests and `distribution/toolchain.json`, not in these runtime files.

`config.schema.json` and `metadata.schema.json` are generated contracts. Edit their Python models, then run `uv run --project detector --no-sync generate-schema --output-directory config` from the repository root. Verify with the same command plus `--check`. Run `pnpm --dir web schema:generate` afterward to update the web's TypeScript declarations; `pnpm --dir web schema:check` verifies them without writing. Both checks run in CI. Do not maintain another detector schema in the web application.

## Presets

Each JSON file in [detector/](detector/) is a preset. The application discovers the files automatically and lists them alphabetically. The filename without `.json` is its ID; dashes, underscores and spaces separate words in the displayed name. For example, `cow-catcher.json` becomes **Cow Catcher**, and `calving-catcher.json` becomes **Calving Catcher**.

The file contains only detector settings: model, watched classes, event rules and delivery defaults. No catalogue entry, description or setup guidance is required. Users choose their preset explicitly. Adding a bundled preset requires only a new JSON file in `config/detector/`; the build embeds it automatically.

Model support follows the detector's supported YOLO detection/segmentation adapters and compatible exports. Adding another inference framework still requires an adapter.

## Add a preset to an installed application

Create a `presets/` folder in the application's data directory, alongside `config.json` and `app.json`. The data directory is shown under **Advanced and troubleshooting**. Put detector JSON files directly in that folder, then reload the editor. Subfolders and files without the `.json` extension are ignored. No application rebuild is required.

A local preset folder replaces the bundled choices. Copy the bundled JSON files into it if you want to retain those choices alongside your own. An empty folder gives an empty list; an absent folder uses the bundled presets. Alternatively, set `AIDETECTOR_PRESETS` to a preset directory. An explicit directory must exist, and invalid files are reported rather than replaced with a different model.

For example, create `presets/entrance-activity.json` to add **Entrance Activity**:

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

Cameras are added first; selecting them in the detector step supplies `detection.source`. Model identifiers, download URLs and local model paths retain the detector's normal interpretation. Relative model paths are relative to the detector's working data directory. Other detector fields, including class names, thresholds, timing, optional VLM configuration and exporters, use the canonical [configuration schema](config.schema.json).

YOLO presets can optionally set `iou` (0–1), `tracking: true` and `tracker` (`botsort.yaml` or `bytetrack.yaml`). Omitting `iou` and `tracker` preserves Ultralytics defaults. Tracking supplies temporary IDs for objects between frames; it does not recognise individuals across sessions. On macOS, native `.pt` models use available PyTorch MPS automatically; exported ONNX models and explicit ONNX provider choices retain their configured path.

Older installations that used a `presets.json` catalogue should move its referenced detector files into `presets/`. The catalogue is no longer read, and `AIDETECTOR_PRESETS` now takes a directory rather than a catalogue filename.

## Saved detectors

Applying a preset copies its detector settings into the saved configuration. Editing, renaming or removing a preset file does not change saved detectors. Editing a camera preserves its detector assignments. A detector can watch several cameras, and a camera can be selected by several detectors. New detectors use the preset's recording and delivery defaults; existing detectors preserve their delivery settings when switching presets. Choosing **Advanced settings** also preserves those choices when loading another preset into the draft.

Preset names remain attached when changing a detector's name, cameras or delivery settings. Changing its detection settings makes it a custom configuration. Previously saved preset IDs remain valid even if the file is renamed or removed; the interface falls back to the saved detector label. Applying an unknown preset to a new configuration is rejected before saving.

## Verification

Python schema tests validate every bundled detector fragment. Web tests cover directory discovery, filename labels, runtime file changes, validation, configuration preservation and source binding. Production HTTP checks exercise bundled and local presets, including a filename that matches an application action. Preset files use the same validation as detector settings; malformed JSON and invalid model options identify the file that needs correction.
