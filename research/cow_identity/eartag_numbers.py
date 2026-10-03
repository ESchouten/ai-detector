"""Research checks for the documented nine-digit Dutch cattle number.

The Ministry's June 2012 reading guide supplies the weights and barcode prefix:
https://www.veehandel.nu/archief/Runder%20Oormerken%20Nederland%20Juni%202012.pdf
This does not validate newer twelve-digit numbers, registration in a database,
tag ownership, or OCR accuracy. It never repairs an observed digit.
"""

import re


def _checked_nl9(digits: str) -> str | None:
    if re.fullmatch(r"[1-9][0-9]{8}", digits) is None:
        return None
    expected = (
        sum(
            int(digit) * weight
            for digit, weight in zip(digits[:8], (9, 3, 1, 7, 9, 3, 1, 7), strict=True)
        )
        % 10
    )
    return digits if int(digits[-1]) == expected else None


def printed_nl9(text: str) -> str | None:
    """Check one complete, explicitly Dutch reading; accept only whitespace layout.

    The caller must establish that these characters belong to one physical tag.
    A four-digit work number is insufficient. Letters resembling digits,
    punctuation and omitted country codes are not guessed or corrected.
    """
    compact = "".join(text.split())
    return _checked_nl9(compact[2:]) if compact.startswith("NL") else None


def barcode_nl9(payload: str, format_name: str, *, country: str) -> str | None:
    """Check a decoder result after independent same-tag country evidence.

    A ten-digit barcode alone does not establish a Dutch animal identifier.
    Code 128 and historical ITF both encode zero followed by the nine digits.
    Pass the library's valid decoded payload, not a fabricated OCR barcode.
    """
    if (
        country != "NL"
        or format_name not in ("Code128", "ITF")
        or len(payload) != 10
        or not payload.startswith("0")
    ):
        return None
    return _checked_nl9(payload[1:])
