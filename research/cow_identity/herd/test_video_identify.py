from video_identify import fewer_confirmations


def test_a_confirmation_keeps_every_crop_of_one_clip():
    rows = [
        {"cow": cow, "clip": f"clip{clip}", "frame": frame}
        for cow in (1, 2)
        for clip in range(5)
        for frame in (1, 230, 1730)
    ]
    kept = fewer_confirmations(rows, 2)
    for cow in (1, 2):
        clips = {row["clip"] for row in kept if row["cow"] == cow}
        assert len(clips) == 2
        assert sum(row["cow"] == cow for row in kept) == 6
