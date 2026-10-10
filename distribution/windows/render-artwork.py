"""Reuse the macOS camera artwork for Windows. Requires Pillow at build time only."""

from pathlib import Path

from PIL import Image

assets = Path(__file__).parent / "artwork"
assets.mkdir(exist_ok=True)
with Image.open(assets.parent.parent / "macos" / "AI Detector.icns") as source:
    icon = source.convert("RGBA")

icon.save(
    assets / "app.ico",
    sizes=[(size, size) for size in (16, 20, 24, 32, 40, 48, 64, 128, 256)],
)
