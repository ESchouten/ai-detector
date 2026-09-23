# Configuration and presets

## Settings ownership

User settings live in the application's data directory, outside the installed binaries. The [application guide](../distribution/README.md#installation-and-data) lists its location on each platform.

| File | Purpose | Code owner |
| --- | --- | --- |
| `config.json` | Sources, models, event rules, verification and delivery | Python [configuration models](../detector/src/aidetector/configuration.py); the web app validates with their generated schema |
| `app.json` | Camera identities, labels, setup progress and notification metadata | Web [configuration validation](../web/src/lib/configuration.ts) and [configuration store](../web/src/lib/server/configuration/store.ts) |
| `runtime.json` | Monitoring resume preference and native/Docker selection | Web [managed detector](../web/src/lib/server/managed-detector.ts) |
| `presets.json` | Optional installation-specific choices for adding monitoring rules | Web [preset catalogue](../web/src/lib/server/configuration/preset-catalog.ts) |

The `application.json` shipped beside the executable is build metadata, not user settings. Build dependencies and tool versions belong in the component manifests and `distribution/toolchain.json`, not in these runtime files.

`config.schema.json` and `metadata.schema.json` are generated contracts. Edit their Python models, then run `uv run --project detector --no-sync generate-schema --output-directory config` from the repository root. Verify with the same command plus `--check`. Run `pnpm --dir web schema:generate` afterward to update the web's TypeScript declarations; `pnpm --dir web schema:check` verifies them without writing. Both checks run in CI. Do not maintain another detector schema in the web application.

## Presets

AI Detector's application handles camera connections, monitoring, recordings and delivery. A preset supplies the model, watched classes, event rules, display name and setup guidance. Model support follows the detector's supported YOLO detection/segmentation adapters and compatible exports; adding another inference framework still requires an adapter.

The bundled catalogue is [presets.json](presets.json). Its `configuration` entries reference ordinary detector fragments in [detector/](detector/). Those fragments remain usable independently of the web application. The default is the general detection preset; cattle-specific models and instructions live entirely in preset data.

## Add a use case to an installed application

Put `presets.json` in the application's data folder, alongside its existing `config.json` and `app.json`. The folder is shown under **Advanced and troubleshooting**. Alternatively, set `AIDETECTOR_PRESETS` to a catalogue filename. An explicit override must exist; a broken catalogue is reported rather than silently replaced by bundled defaults.

A local catalogue replaces the bundled choices. To extend the existing list, copy the bundled catalogue and its referenced detector fragments into the data folder, then add your entries. Reload the editor after changing it; no application rebuild is required.

For example, use this catalogue to configure entrance monitoring:

```json
{
  "defaultPreset": "entrance-activity",
  "presets": [
    {
      "id": "entrance-activity",
      "name": "People at the entrance",
      "description": "Record people entering the monitored area.",
      "guidance": "Keep the doorway and the approach clearly visible.",
      "configuration": "presets/entrance.json"
    }
  ]
}
```

Create the referenced `presets/entrance.json`:

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

The `configuration` filename is resolved relative to the catalogue. Model identifiers, download URLs and local model paths retain the detector's normal interpretation; relative model paths are relative to the detector's working data directory, not the catalogue file. The selected camera supplies `detection.source`. Other detector fields, including class names, thresholds, timing, optional VLM configuration and exporters, use the canonical [configuration schema](config.schema.json).

YOLO presets can optionally set `iou` (0–1), `tracking: true` and `tracker` (`botsort.yaml` or `bytetrack.yaml`). Omitting `iou` and `tracker` preserves Ultralytics defaults. Tracking supplies temporary IDs for objects between frames; it does not recognise individuals across sessions. On macOS, native `.pt` models use available PyTorch MPS automatically; exported ONNX models and explicit ONNX provider choices retain their configured path.

IDs must be nonempty and unique. Display names and descriptions are required; guidance and `defaultPreset` are optional. Without a default, setup asks the user to choose. Preset IDs are independent of application actions such as copying a camera or keeping existing settings.

## Existing cameras

Applying a preset copies its detector settings into the saved configuration. Editing or removing a catalogue entry does not change a running camera. Camera changes default to **Keep current monitoring settings**, and copying an existing camera uses its actual saved rules even when its original preset is unavailable. Existing alert destinations and recording settings remain preserved when switching presets.

Unknown preset IDs already stored in camera metadata remain valid. The camera list uses the saved rule label when the catalogue no longer supplies a name. Applying an unknown preset to a new configuration is rejected before saving.

Preset files use the same validation as detector settings. Invalid JSON, duplicate IDs, missing references and invalid model options produce errors. The catalogue is a local configuration mechanism; it is not a remote plugin or executable-code registry.

## Bundled changes and verification

To add a bundled choice, add its detector fragment under `config/detector/` and reference it in `config/presets.json`. The build embeds those files automatically. Do not add per-preset branches to application code.

Python schema tests validate every bundled detector fragment. Web tests cover arbitrary IDs, runtime catalogue changes, configuration preservation and source binding. Production HTTP checks use a separate non-agricultural catalogue, including an ID that matches an application action, to exercise the normal setup route.
