"""Read launcher status records by the literal prefix the web application expects."""

import json


def status_records(output: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("AIDETECTOR_STATUS "))
        for line in output.splitlines()
        if line.startswith("AIDETECTOR_STATUS ")
    ]
