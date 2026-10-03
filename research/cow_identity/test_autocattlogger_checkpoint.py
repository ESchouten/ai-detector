from pathlib import Path

import pytest
from autocattlogger_checkpoint import extract


def test_different_artifact_is_rejected_before_archive_parsing(tmp_path: Path) -> None:
    source = tmp_path / "untrusted.pth"
    source.write_bytes(b"not the pinned author checkpoint")
    destination = tmp_path / "extracted.pt"

    with pytest.raises(AssertionError, match="exactly one artifact"):
        extract(source, destination)

    assert not destination.exists()
