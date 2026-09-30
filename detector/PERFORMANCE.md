# Measuring inference without trading away detection quality

Native NVIDIA inference uses PyTorch/CUDA FP16, Ultralytics preprocessing and fused model layers. The Windows application now attempts direct TensorRT FP16 on compute capability 8.0+ after preparing CUDA, retaining CUDA when the optimization cannot be prepared. This automatic route has functional checks, but has not yet been benchmarked or qualified for detection quality on the target GPU. Live capture reads continuously; each inference batch scores only the latest retained frame from each active camera. Older frames provide event context. Increasing `detection.interval`, lowering `imgsz`, selecting a smaller model or changing `frames_min` can change event sensitivity. Keep those settings fixed when comparing implementation changes.

## Read the running application's timings

At the default INFO level, each prediction includes total wall time, time waiting for the shared MPS lock, Ultralytics preprocessing/inference/postprocessing milliseconds per image, result mapping time, and input shapes in height/width order. Mapping includes moving bounding boxes to CPU memory. Total wall time includes SDK overhead and, on MPS, final synchronization; it need not equal the stage totals. CUDA does not use the MPS lock.

Every thirty seconds, each camera reports decoded frames/second, average read time, and average resize/publication time. Read time includes waiting for the camera or network; it is not a measurement of CPU decoding time. Neither log measures the age of an image inside the camera/RTSP buffer or browser latency. Use these measurements to locate work before replacing a backend.

Live detectors sharing a source and effective frame width now reuse the same resized pixels. Sampling is checked first, and variants are discarded with their decoded frame rather than accumulated in a global cache. Tests compare pixels exactly with the previous resize operation and exercise independent sampling, retention, disconnection and application-level delivery.

A local microbenchmark on Apple M2 Max, OpenCV with 12 threads, resizing a synthetic 2560×1440 frame to width 1280 measured these median times. There were 10 warm-up rounds and 200 measured rounds, alternating comparison order and releasing outputs between rounds:

| Detectors sharing the width | Separate resizes | Shared resize |
| --- | --- | --- |
| 1 | 0.163 ms | 0.164 ms |
| 2 | 0.327 ms | 0.165 ms |
| 4 | 0.649 ms | 0.166 ms |

These are resize timings, not full-application FPS or NVIDIA measurements. The durable result is one resize per width instead of one per detector, with unchanged pixels.

## Compare native CUDA, shape grouping and direct TensorRT

Use a development environment on the target GPU, with the same pinned dependencies as the application's NVIDIA runtime. The tool uses the production YOLO adapter and its predictor initialization. It does not start monitoring, edit settings, open cameras or send notifications. Models and benchmark images must be local files. Package auto-installation is disabled. Optional validation uses the normal Ultralytics dataset loader; supply an existing, trusted, fully downloaded YOLO dataset.

From `detector/`, run a baseline using saved camera images. Keep their order representative of simultaneously active cameras. The optional preset supplies model settings, class thresholds and capture width; `--models` selects the local weight files instead of downloading the preset's model URL:

```sh
python -m tools.benchmark_inference --models /models/detector.pt --images /samples/camera-1.jpg /samples/camera-2.jpg /samples/camera-3.jpg --preset ../config/detector/cow-catcher.json --device 0 --batch 3 --output .reports/cuda-baseline
```

Each model runs the current arrival-order batches and experimental batches grouped by identical image dimensions. Grouping only splits the already-available batch; it never waits for another camera. Ultralytics can use rectangular padding for matching shapes, but extra model calls can erase that saving. Grouping also changes padding and can change predictions. It remains an offline experiment. Tracking is deliberately excluded because it requires a sequential video replay with stable camera slots.

For a direct TensorRT comparison, install a compatible TensorRT runtime in the isolated benchmark environment, following [Ultralytics' integration guide](https://docs.ultralytics.com/integrations/tensorrt). Export a **copy** of the checkpoint on the target GPU with the SDK, using the same `imgsz` as the preset and a batch limit covering the test:

```sh
yolo export model=/benchmark-models/detector.pt format=engine device=0 quantize=16 dynamic=True batch=3 imgsz=640 simplify=True opset=20
python -m tools.benchmark_inference --models /benchmark-models/detector.pt /benchmark-models/detector.engine --images /samples/camera-1.jpg /samples/camera-2.jpg /samples/camera-3.jpg --preset ../config/detector/cow-catcher.json --device 0 --batch 3 --data /validation/data.yaml --output .reports/cuda-tensorrt
```

The export command is the library's existing workflow, not another application installer or downloader. It may require additional export dependencies. This route loads `.engine` directly through Ultralytics; it does not use Windows ML. TensorRT engines depend on the GPU and runtime used to build them, so do not copy them into the portable model cache or distribute one engine to arbitrary PCs. Export/build time is separate from steady-state inference. See also [NVIDIA's performance guidance](https://docs.nvidia.com/deeplearning/tensorrt/latest/performance/best-practices.html).

`report.json` contains model/image hashes, versions, requested settings, actual backend/device/precision, initialization and first-pass times, warmed-up p50/p95 pass times, throughput, process CPU consumption, SDK stage timings and the final mapped boxes for every image. A pass processes the entire supplied image set; its duration is not per-camera latency. `cpu_percent_one_core=100` means one occupied CPU core and may exceed 100 on a multicore machine. Image loading/resizing is reported separately and excluded from inference throughput. Run the comparison again with reversed model order to check for thermal/order effects. Reports are developer artifacts, not a live camera benchmark or a measure of concurrent detectors, video decoding, notifications or browser rendering.

With `--data`, [Ultralytics validation](https://docs.ultralytics.com/modes/val) reports precision, recall and mAP, including per-class results. It uses the same square validation size for both backends and the SDK's validation thresholds, not the application's event thresholds or capture-width preprocessing. This checks model conversion; it does not validate the experimental live batch policy. Without labeled data, the report contains predictions and timings only and cannot establish quality preservation.

Before rolling out the TensorRT optimization beyond testing:

1. Compare the same model and settings on representative daytime, nighttime, crowded and partially occluded footage; include difficult positives and empty/negative scenes.
2. Check recall per relevant class, inspect differences in saved boxes/confidence near configured thresholds, and replay labeled events at the original sampling rate. Detection mAP alone does not prove mounting/calving alert sensitivity.
3. Require a useful speed/CPU improvement on the target machine and an explicitly accepted quality result. TensorRT preparation success alone is not that evidence. Shape grouping remains an offline experiment and is not enabled in monitoring.

The automatic route logs `Inference backend ready: engine` when it loads TensorRT, and records preparation/fallback reasons. Use the cached engine and original checkpoint with the benchmark above. Cached engines are specific to model settings, GPU, driver and runtime versions; do not copy them between arbitrary machines. Preparation tests run blank square/rectangular images at batch one and the configured camera limit. They detect broken exports and execution failures; they cannot measure recall or alert quality.

Local verification covers exact resize parity, a real ONNX benchmark through the adapter and SDK validation on a tiny synthetic dataset, plus engine cache/publication, process failure, timeout and cancellation contracts. It proves the measurement and supervision workflows execute; it does not establish farm-model accuracy. CUDA/TensorRT performance and representative event-level quality have not been measured on this development machine.
