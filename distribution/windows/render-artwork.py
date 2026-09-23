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


def place_icon(canvas: Image.Image, size: int, position: tuple[int, int]) -> None:
    scaled = icon.resize((size, size), Image.Resampling.LANCZOS)
    canvas.paste(scaled, position, scaled)


header = Image.new("RGB", (192, 192), "white")
place_icon(header, 192, (0, 0))
header.save(assets / "wizard-small.bmp")

# Three times the classic Inno wizard dimensions, for high-DPI displays.
sidebar = Image.new("RGB", (492, 942), "#f1f5f9")
place_icon(sidebar, 360, (66, 192))
sidebar.save(assets / "wizard.bmp")
