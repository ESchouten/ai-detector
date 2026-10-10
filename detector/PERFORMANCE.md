# Measuring inference without trading away detection quality

Speed comparisons are only meaningful when detection settings stay fixed. Raising `detection.interval`, lowering `imgsz`, choosing a smaller model or changing `frames_min` all change which events are found. Live capture reads continuously, and each inference batch scores only the newest retained frame of each camera; older frames are event context.

The automatic TensorRT route has functional checks but has not been benchmarked or qualified for detection quality. Background engine building shares the GPU with monitoring and affects timings, so measure both during and after it.

## Timings in the running application

At the default `INFO` level each detector logs a summary every thirty seconds: frames, batches, average time per frame and the slowest batch, and on the Apple GPU the memory held by PyTorch and by the whole process. `--log-level DEBUG` adds a line per prediction with total wall time, time spent waiting for the shared MPS lock, Ultralytics' preprocessing, inference and postprocessing per image, result mapping (which includes moving boxes to CPU memory) and the input shapes. Wall time includes SDK overhead and need not equal the sum of the stages.

Every thirty seconds each camera logs decoded frames per second, average read time and average resize and publication time. Read time includes waiting for the camera or network; it is not CPU decoding time. None of these lines measures how old an image was inside the camera's buffer, or delay in the browser.

Detectors that share a source and a frame width share one resize per decoded frame, with identical pixels.

To compare Windows ML with CUDA, use the same model, cameras, `detection.interval`, `imgsz` and open previews, and compare the detector process's steady-state CPU use and processed frames per second after preparation. The ONNX startup log lists the session's providers, the device that prepares image tensors and whether I/O binding is active. A CPU provider in that list does not prove the model runs on the CPU, and a GPU provider does not prove every operation runs on the GPU; use ONNX Runtime profiling for that.

## Compare CUDA, shape grouping and TensorRT offline

`tools/benchmark_inference.py` uses the production YOLO adapter and its predictor setup. It opens no cameras, changes no settings and sends nothing. Models and images must be local files. Run it on the target GPU with the same pinned dependencies as the application's NVIDIA runtime.

From `detector/`, with saved camera images in an order that represents cameras active together. The preset supplies model settings, class thresholds and capture width; `--models` selects local weights instead of the preset's download URL:

```sh
python -m tools.benchmark_inference --models /models/detector.pt --images /samples/camera-1.jpg /samples/camera-2.jpg /samples/camera-3.jpg --preset ../config/detector/cow-catcher.json --device 0 --batch 3 --output .reports/cuda-baseline
```

Each model runs the current arrival-order batches and an experimental variant that groups images of identical dimensions. Grouping changes padding and can change predictions, and its extra model calls can cancel the saving; it is an offline experiment and is not used in monitoring. Tracking is excluded because it needs a sequential replay.

For TensorRT, install a compatible runtime in the benchmark environment following [Ultralytics' guide](https://docs.ultralytics.com/integrations/tensorrt), then export a copy of the checkpoint on the target GPU with the preset's `imgsz` and a batch limit that covers the test:

```sh
yolo export model=/benchmark-models/detector.pt format=engine device=0 quantize=16 dynamic=True batch=3 imgsz=640 simplify=True opset=20 workspace=2
python -m tools.benchmark_inference --models /benchmark-models/detector.pt /benchmark-models/detector.engine --images /samples/camera-1.jpg /samples/camera-2.jpg /samples/camera-3.jpg --preset ../config/detector/cow-catcher.json --device 0 --batch 3 --data /validation/data.yaml --output .reports/cuda-tensorrt
```

An engine belongs to the GPU and runtime that built it; do not copy it to another machine. The application's own cached engines are in `models/prepared/tensorrt/` and can be benchmarked the same way. Run the comparison again with the models in reverse order to rule out thermal and ordering effects.

`report.json` holds model and image hashes, versions, the actual backend, device and precision, initialization and first-pass times, warmed-up p50 and p95 pass times, throughput, process CPU use, SDK stage timings and the mapped boxes of every image. A pass is the whole image set, not per-camera latency. `cpu_percent_one_core=100` is one busy core. Image loading is reported separately.

With `--data`, [Ultralytics validation](https://docs.ultralytics.com/modes/val) adds precision, recall and mAP per class on a labeled dataset you supply. That checks the model conversion with the SDK's validation thresholds, not the application's event thresholds. Without labeled data the report cannot say whether quality was preserved.

## Before relying on TensorRT

1. Compare the same model and settings on representative footage: day, night, crowded, partly hidden, difficult positives and empty scenes.
2. Check recall per relevant class, look at boxes and confidences near the configured thresholds, and replay labeled events at the original sampling rate. Detection mAP alone does not show that mounting or calving alerts are still raised.
3. Require a real improvement in speed or CPU use on the target machine and an explicitly accepted quality result. A successful engine build is neither.

The automated tests show that the benchmark and the engine preparation run, with a synthetic dataset and blank images. They say nothing about a farm model's accuracy or a GPU's speed.
