"""Literal four-digit reading candidates for the automatic identity study.

A candidate is a display label, not a unique animal ID or an accepted OCR result.
The caller must still establish that this is the work-number region of a tag,
that the reading is reliable, and which animal owns it. In particular, a year
also has four digits; syntax alone cannot distinguish it from a work number.
"""

import re


def work_number(text: str) -> str | None:
    """Keep one complete four-digit reading, including its leading zeros.

    Do not infer digits, extract substrings of longer numbers, join separate
    lines, or require a national registration number or country prefix.
    """
    value = text.strip()
    return value if re.fullmatch(r"[0-9]{4}", value) else None
