# Measuring inference without trading away detection quality

Speed comparisons are only meaningful when detection settings stay fixed. Raising `detection.interval`, lowering `imgsz`, choosing a smaller model or changing `frames_min` all change which events are found. Live capture reads continuously, and each inference batch scores only the newest retained frame of each camera; older frames are event context.

The automatic TensorRT route has functional checks but has not been benchmarked or qualified for detection quality. Background engine building shares the GPU with monitoring and affects timings, so measure both during and after it.

## Timings in the running application

At the default `INFO` level each detector logs a summary every thirty seconds: frames, batches, average time per frame and the slowest batch. `--log-level DEBUG` adds a line per prediction with total wall time, Ultralytics' preprocessing, inference and postprocessing per image, result mapping (which includes moving boxes to CPU memory) and the input shapes. Wall time includes SDK overhead and need not equal the sum of the stages.

Every thirty seconds each camera logs decoded frames per second, average read time and average resize and publication time. Read time includes waiting for the camera or network; it is not CPU decoding time. None of these lines measures how old an image was inside the camera's buffer, or delay in the browser.

Detectors that share a source and a frame width share one resize per decoded frame, with identical pixels.

To compare Windows ML with CUDA, use the same model, cameras, `detection.interval`, `imgsz` and open previews, and compare the detector process's steady-state CPU use and processed frames per second after preparation. The ONNX startup log lists the session's providers, the device that prepares image tensors and whether I/O binding is active. A CPU provider in that list does not prove the model runs on the CPU, and a GPU provider does not prove every operation runs on the GPU; use ONNX Runtime profiling for that.

## Before relying on TensorRT

1. Compare the same model and settings on representative footage: day, night, crowded, partly hidden, difficult positives and empty scenes.
2. Check recall per relevant class, look at boxes and confidences near the configured thresholds, and replay labeled events at the original sampling rate. Detection mAP alone does not show that mounting or calving alerts are still raised.
3. Require a real improvement in speed or CPU use on the target machine and an explicitly accepted quality result. A successful engine build is neither.

The automated tests show that engine preparation runs, with blank images. They say nothing about a farm model's accuracy or a GPU's speed.
