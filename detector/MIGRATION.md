# Upgrading the detector

What someone replacing an older detector, or reading its files from other software, needs to know or do. Changes that need no action are in the Git history, not here.

## What stays compatible

- `config.json` keeps its top-level `detectors`, `onnx` and `health`. Sources, VLM configurations, model names and exporters accept one value or a list.
- Archives stay readable: `detections/<category>/<stage>/<timestamp>/` with `best.jpg`, `clean.jpg`, an optional `video.mp4` and `metadata.json` with its existing required fields.
- Runtime data lives outside the installed program. An upgrade does not rewrite configuration or recordings.
- Docker, macOS, Windows CUDA and Windows ML builds remain supported. Whether a GPU provider actually runs can only be checked on that hardware.

## Configuration written for an earlier detector

Run `--check-config` against the saved file and correct what it reports. These are deliberate differences from the detector before the rewrite:

- Configuration is validated before anything starts and is never repaired or rewritten. Unknown options are errors; remove `yolo.strategy`, which never had an effect.
- Nothing creates a configuration implicitly. A missing file is an error; `--init-config` writes a template and refuses to overwrite.
- `frames_min` defaults to `3` on every platform. Set `6` explicitly to keep the old CUDA default. It counts matching observations in an event; they need not be consecutive.
- Verification is switched by `key` alone. A null or omitted key turns an entry off and no longer falls back to credentials from the environment; `""` selects an unauthenticated local service. Add the key to every verifier that should keep running.
- A verifier must answer exactly `{"detected": true}` or `{"detected": false}`. Custom providers and fixtures that return `confidence` or `reasoning` are rejected.
- Failed verification is its own outcome. It does not send ordinary Telegram or webhook notifications; disk may keep the event under `unvalidated` with `validation_error`.
- Disk `directory` is one category name under `detections/`, such as `mounts`. Move an old absolute output root to `--data-dir` and choose a category name.
- Put finite files and live streams in separate detector definitions. Unsupported URL schemes, missing hosts, out-of-range ports and HTTP image URLs fail the check instead of reconnecting forever.
- Relative media and model paths resolve against the configuration's folder. Output goes there or to `--data-dir`; downloaded models go to its `models/` folder.
- Python 3.12 or newer is required. [`.python-version`](.python-version) pins the version used for development, CI and native builds.
- The generated schema names follow the Python classes: tools that refer to `$defs` directly use `SourceConfig` and `TelegramConfig`.

## Files other software reads

- Each delivered event has an `event_id` in `metadata.json`; metadata written before that has none and stays valid.
- A person's review is the optional `review` object in `metadata.json` (`validated`, `source`, `reviewed_at`), written by the web application. `validated` stays the validator's own result.
- Status records for the launcher (`--status-json`) and live pictures (`--live-preview`) are versioned protocols between the detector and the web application of the same release. Deploy both from one release.

## Docker

There is one image now, `ghcr.io/eschouten/ai-detector`: the web application starts and supervises the detector inside it, so detector settings apply without restarting a container. The separate `ai-detector-web` image is no longer published, and the `ai-detector` image no longer runs the detector as its default command.

To move an installation that used the two images:

1. Stop it with `docker compose down`, and back up the data folder.
2. Replace the Compose file with [`example/compose.yml`](../example/compose.yml) or, on a Jetson with JetPack 7.2, [`example/compose.jetson.yml`](../example/compose.jetson.yml). They have one service and use the host's network on port 80.
3. Give the data folder to the image's user: `sudo chown -R 999:999 .` in that folder. The web image wrote its files as another user, which the single image cannot change.
4. Start it with `docker compose up -d`.

Running the detector alone still works by naming the command: `python3 -m aidetector`.

## Jetson

JetPack 6 is no longer supported. Its images are no longer built and the published `-jetpack6` images receive no updates; do not point a JetPack 6 host at the generic `latest` image.

JetPack 7.2 runs the standard ARM64 CUDA 13 software on Orin and Thor, so the ARM64 image is built from plain Ubuntu 24.04 with the standard PyTorch build for CUDA 13, as Ultralytics' [Jetson guide](https://docs.ultralytics.com/guides/nvidia-jetson/) describes for a native installation; use it with [`example/compose.jetson.yml`](../example/compose.jetson.yml). It starts on PyTorch on the GPU and prepares TensorRT 10 engines in the background, taking them at the next start; without a GPU it says so in the log and detects on the processor.

The image has been run on a Jetson Orin Nano with JetPack 7.2 and one RTSP camera. Detection ran on the GPU with PyTorch, the engine for a YOLO26m model was built in about twenty minutes with TensorRT 10.16 from NVIDIA's Jetson packages, and from the next start of monitoring TensorRT took about 16 ms per frame where PyTorch had taken 45 ms. A Thor has not been tried. Before moving a farm installation, check it on that board with the farm's own cameras, and back up the mounted settings and recordings.

## Upgrade steps

1. Keep the current executable or container available, and copy `config.json`.
2. Check the saved configuration with the replacement. Correct only what it reports.
3. Run a recording into a separate data folder and compare how events are grouped and delivered.
4. Stop the old detector before starting the replacement on the same output folder. Never run two versions against one live folder.
5. To go back: stop the replacement, restore the previous program and configuration, and start it again. Archives need no conversion in either direction.

From `detector/`:

```sh
uv sync --locked --extra default
uv run --no-sync aidetector --config /path/to/saved-config.json --check-config
uv run --no-sync aidetector --config /path/to/recorded-input-config.json --data-dir /path/to/trial-output
```

For an executable, replace `uv run --no-sync aidetector` with its path. In Docker, configuration and output stay under the mounted `/data`. For the trial, use a copy of the configuration that points to a local recording and model and a disk exporter; leave verifiers and notification destinations in only when their requests are intended.

A finite run exits with `1` after any verification or delivery failure and `2` for a configuration error. Look for `validation_error` in `unvalidated/*/metadata.json` when checking that a provider is reachable.

## What the tests cannot tell you

Tests and package checks use local stand-ins for cameras, providers and notification services. They do not establish model quality, provider accuracy, or that Windows ML, NVIDIA or Jetson hardware runs the model. Check those on the target system.
