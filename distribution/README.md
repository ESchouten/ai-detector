# Complete application downloads

The release boundary is the entire application: one web executable, one native detector directory, FFmpeg, and a small `application.json` recording the exact NVIDIA image digest. The web executable is the user's single entry point.

`application.yml` builds Windows x64, macOS ARM64 and Linux x64 from the same commit as the NVIDIA image. It smoke-tests both ONNX and PT inference in each frozen detector, checks/builds the web app, assembles a ZIP with a SHA-256 checksum, then boots the complete bundle on that runner. `smoke.py` uses a generated BMP and a fresh temporary data folder to verify browser setup, automatic detector startup and a real archived event without cameras, external services or weight downloads. A release is published only after all three native jobs succeed. `workflow_dispatch` produces test artifacts without creating a release.

For local assembly (Python 3.11+):

```sh
python distribution/package.py \
  --detector detector/dist/aidetector \
  --web web/dist/ai-detector-web \
  --ffmpeg web/node_modules/ffmpeg-static/ffmpeg \
  --output application-dist --platform macos-arm64 \
  --image ghcr.io/eschouten/ai-detector@sha256:RELEASE_DIGEST
python distribution/smoke.py application-dist/AI-Detector-macos-arm64
python -m unittest discover -s distribution -p 'test_*.py'
```

Build the detector with PyInstaller `--onedir --name aidetector`; the workflow contains the required hooks. ZIPs keep the executable permissions and include a plain-language `START HERE.txt`. Package output directories must be fresh, preventing an accidental mix of old and new binaries. User data is never put in release archives.

The managed runtime lives in `web/src/lib/server/managed-detector.ts`; platform probes and Docker arguments live in `runtime-platform.ts`. SvelteKit hooks construct the manager only at runtime. The first browser request initializes saved startup state, keeping port binding and SvelteKit build operations free of detector starts. The application's automatic browser opening triggers that request; headless launchers must request `/` once. The home route redirects to Setup on first run and Detections after configuration. Standalone web/Docker installations remain unmanaged unless an executable is explicitly configured.

The parent sends `stop\n` through stdin. EOF also requests shutdown, so closing the parent releases a native detector without maintaining PID files or a separate service installation. The Python runtime observes the stop request alongside worker futures and drains accepted events, including validation and export failures. A failed start stays failed and requires a retry; there is no restart loop. Stopping detection disables automatic resume. Closing the application while detection is enabled preserves that choice for next launch.

## Linux Docker startup

`linux_startup.py` is a separate Python 3.10+ standard-library helper for an existing systemd Docker Engine installation. Run it as the desktop user; it requests sudo for Docker configuration and daemon startup. See the [installation command](../README.md#start-automatically-on-a-jetson-or-linux-desktop). It validates the Compose restart policies, enables Docker's existing service, and starts that same Compose project. Docker remains the container supervisor; no second systemd service competes with it.

The installer copies the launcher to `$XDG_DATA_HOME/ai-detector/startup.py` and writes `$XDG_CONFIG_HOME/autostart/ai-detector.desktop`, using the standard `~/.local/share` and `~/.config` defaults. Desktop Entry arguments are quoted for paths with spaces and escaped field codes. At desktop login, it waits up to five minutes for an HTTP success, follows the home redirect, then calls `xdg-open` once. Reinstalling updates the same files; uninstalling removes only those files. Neither action changes Linux automatic-login settings. A headless Jetson runs the containers without a browser.

The JetPack 6 Compose example selects the existing `latest-jetpack6` release image and `runtime: nvidia`. Generic NVIDIA Compose files keep their GPU device reservation. The helper does not configure browser controls for these separately managed detectors, install prerequisites, or turn the native application into a system service.

## Release limits

- Builds are unsigned. Signing/notarization requires the project's release credentials and remains a release task.
- Windows x64, Apple Silicon macOS and glibc 2.35+ Linux x64 are the initial combined targets. No combined Intel Mac, ARM Windows or Jetson bundle is claimed.
- CI without GPU hardware can establish packaging and CPU inference, not Windows ML acceleration, Core ML GPU execution or NVIDIA compatibility on every driver. Test a release on those target machines before distributing it broadly.
- The manager does not install drivers, Docker, services or startup-at-login tasks. Missing Docker prerequisites have actionable links and an explicit native option. The selected model downloads on first detection startup.
- “Running” means the process is alive. It does not establish camera availability or detection accuracy. Preview the camera and inspect actual detections before relying on the setup.
