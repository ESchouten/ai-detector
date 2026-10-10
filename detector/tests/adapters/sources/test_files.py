from datetime import datetime

from aidetector.adapters.sources.files import FileSource
from tests.support.media import write_video


def test_file_sampling_uses_media_time_instead_of_sleeping(tmp_path):
    video = tmp_path / "input.avi"
    write_video(video, frames=12, fps=10)
    source = FileSource((str(video),), interval=0.5, started_at=datetime(2026, 1, 1))
    dates = [
        batch.frames[str(video)][0].date for batch in source.batches() if batch.frames
    ]
    assert [date.isoformat() for date in dates] == [
        "2026-01-01T00:00:00",
        "2026-01-01T00:00:00.500000",
        "2026-01-01T00:00:01",
    ]


def test_sampling_at_the_frame_rate_does_not_drop_frames_to_rounding(tmp_path):
    video = tmp_path / "input.avi"
    write_video(video, frames=12, fps=10)
    source = FileSource((str(video),), interval=0.1)
    assert len([batch for batch in source.batches() if batch.frames]) == 12
