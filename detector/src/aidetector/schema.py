import argparse
import json
from pathlib import Path

from aidetector.adapters.exporters.archive_metadata import EventMetadata
from aidetector.configuration import Config


def schemas() -> dict[str, dict]:
    return {
        "config.schema.json": Config.model_json_schema(),
        "metadata.schema.json": EventMetadata.model_json_schema(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate or check detector JSON schemas."
    )
    parser.add_argument("--output-directory", type=Path, default=Path("../config"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    changed = []
    for name, schema in schemas().items():
        path = args.output_directory / name
        content = json.dumps(schema, indent=2) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                changed.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"Generated {path}")
    if changed:
        print(f"Schemas need regeneration: {', '.join(changed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
