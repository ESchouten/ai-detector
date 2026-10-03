"""Real ZXing integration on generated symbols, not an ear-tag accuracy trial."""

import argparse
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path

import numpy as np
import zxingcpp
from eartag_numbers import barcode_nl9


def run(output: Path) -> None:
    if output.exists():
        raise FileExistsError("Preserve the original smoke report")
    libraries = {
        name: importlib.metadata.version(name)
        for name in ("zxing-cpp", "numpy", "pillow")
    }
    if libraries != {"zxing-cpp": "3.1.1", "numpy": "2.5.3", "pillow": "12.3.0"}:
        raise ValueError("Use the isolated pinned barcode environment")
    # Expected number acceptance is fixed before generating or decoding pixels.
    cases = (
        ("0194625043", "NL", "194625043"),
        ("0123456814", "NL", "123456814"),
        ("0123456815", "NL", None),  # Valid symbol, invalid cattle checksum.
        ("0123456814", "", None),  # A symbol alone supplies no country evidence.
    )
    started = time.perf_counter()
    rows = []
    for format_name in ("Code128", "ITF"):
        format_value = getattr(zxingcpp.BarcodeFormat, format_name)
        for payload, country, expected in cases:
            encoded = zxingcpp.create_barcode(payload, format_value)
            image = np.asarray(encoded.to_image(scale=3))
            for rotation in (0, 1):
                pixels = np.ascontiguousarray(np.rot90(image, rotation))
                decoded = zxingcpp.read_barcodes(pixels, formats=format_value)
                if len(decoded) != 1 or not decoded[0].valid:
                    raise ValueError("Synthetic symbol was not decoded exactly once")
                reading = decoded[0]
                if reading.text != payload:
                    raise ValueError("Decoder changed the synthetic payload")
                number = barcode_nl9(reading.text, reading.format.name, country=country)
                if number != expected:
                    raise ValueError("Number acceptance differs from the fixed case")
                rows.append(
                    {
                        "format": format_name,
                        "payload": payload,
                        "country": country,
                        "rotation_degrees": 90 * rotation,
                        "pixels_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
                        "shape": list(pixels.shape),
                        "decoded": reading.text,
                        "accepted_number": number,
                    }
                )
    if zxingcpp.read_barcodes(np.full((128, 256), 255, np.uint8)):
        raise ValueError("Blank image unexpectedly produced a barcode")
    sources = (Path(__file__), Path(__file__).with_name("eartag_numbers.py"))
    result = {
        "scope": "Synthetic Code128/ITF decoder and NL9 checksum integration only. No farm pixels, detection coverage, animal association or calibrated confidence claim.",
        "libraries": libraries,
        "files": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources
        },
        "rows": rows,
        "blank_has_no_reading": True,
        "seconds": time.perf_counter() - started,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps({"passed": len(rows), "blank_passed": True, "output": str(output)})
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    run(parser.parse_args().output)
