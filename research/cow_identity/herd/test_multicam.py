import multicam


def test_a_walk_is_one_cows_pictures_under_one_camera_in_order(tmp_path):
    folder = tmp_path / "2023Aug14" / "007"
    folder.mkdir(parents=True)
    for name in ("00002_1", "00000_1", "00001_1", "00003_2"):
        (folder / f"{name}.jpg").touch()

    walks = list(multicam.walks(tmp_path, ("2023Aug14", "2023Aug15"), (6, 7)))

    assert [(walk["day"], walk["cow"], walk["camera"]) for walk in walks] == [
        ("2023Aug14", 7, 1),
        ("2023Aug14", 7, 2),
    ]
    assert [file.stem for file in walks[0]["files"]] == ["00000_1", "00001_1", "00002_1"]


def test_every_fourth_cow_is_withheld_and_the_last_two_days_are_the_test():
    assert multicam.WITHHELD[:3] == (4, 8, 12)
    assert len(multicam.WITHHELD) == 22
    assert multicam.TEST == ("2023Aug19", "2023Aug20")
    assert not set(multicam.TEST) & set(multicam.PHOTOGRAPHS + multicam.VALIDATION)


def test_a_folder_page_lists_its_clips_with_their_sizes():
    page = """<tr>
<td><img src="/datasets/images/arrow-up.svg" alt="Up"></td>
<td><a href="..">Up to parent directory</a></td>
<td></td>
<td></td>
</tr>
<tr>
<td><img src="/datasets/images/file.svg" alt="File"></td>
<td><a href="2023-08-18T12-53-40.mp4">2023-08-18T12-53-40.mp4</a></td>
<td>2023-08-18T15:25:50Z</td>
<td>260538408</td>
</tr>"""

    assert multicam.listed(page) == [("2023-08-18T12-53-40.mp4", 260538408)]


def test_the_upright_box_takes_in_the_head_beyond_the_pictures_right_edge():
    # A picture 200 long and 100 wide whose cow walks down the frame.
    corners = [[500, 100], [500, 300], [400, 300], [400, 100]]

    assert multicam.upright(corners, 2560, 1440) == (400.0, 100.0, 500.0, 370.0)


def test_the_upright_box_stays_inside_the_frame():
    corners = [[500, 1300], [500, 1420], [400, 1420], [400, 1300]]

    assert multicam.upright(corners, 2560, 1440)[3] == 1440.0


def test_a_frame_holds_each_cow_once_by_her_closest_picture():
    record = {
        "located": [
            {"cow": 7, "picture": "00003_1.jpg", "clip": "a.mp4", "frame": 50, "difference": 9.0},
            {"cow": 7, "picture": "00004_1.jpg", "clip": "a.mp4", "frame": 50, "difference": 6.0},
            {"cow": 9, "picture": "00001_1.jpg", "clip": "a.mp4", "frame": 50, "difference": 7.0},
        ]
    }

    cows = multicam.found_in(record)["a.mp4", 50]

    assert cows[7]["picture"] == "00004_1.jpg"
    assert sorted(cows) == [7, 9]


def test_every_session_registers_as_a_video_a_day_after_its_photographs():
    import ethz

    assert multicam.SESSIONS["multicam-17-cam2"] == ("2023Aug17", 2)
    assert ethz.gap("multicam-17-cam2").total_seconds() == 12 * 3600


def test_a_pictures_label_holds_the_upright_box_of_each_cow_cut_out_of_its_frame(tmp_path):
    import json
    from types import SimpleNamespace

    frames = tmp_path / "frames" / "multicam-17-cam1"
    frames.mkdir(parents=True)
    index = [{"index": at, "seconds": at / 5, "file": f"{at:06d}.jpg"} for at in range(5)]
    (frames / "frames.json").write_text(json.dumps({"video": "multicam-17-cam1", "frames": index}))
    located = tmp_path / "located.json"
    located.write_text(
        json.dumps(
            {
                # The first clip gave three pictures to the application, the second two.
                "frames_read": {"a.mp4": 3, "b.mp4": 2},
                "located": [
                    {
                        "cow": 7,
                        "picture": "00003_1.jpg",
                        "clip": "b.mp4",
                        "frame": 5,
                        "corners": [[500, 100], [500, 300], [400, 300], [400, 100]],
                        "difference": 5.0,
                    }
                ],
            }
        )
    )

    multicam.labels(SimpleNamespace(frames=frames, located=located, labels=tmp_path / "labels"))

    folder = tmp_path / "labels" / "multicam-17-cam1" / "labels"
    assert sorted(file.name for file in folder.iterdir()) == [
        f"frame_{at:06d}.txt" for at in range(5)
    ]
    assert (folder / "frame_000003.txt").read_text() == ""
    cow, x, y, width, height = (folder / "frame_000004.txt").read_text().split()
    assert cow == "7"
    assert [round(float(x) * 2560), round(float(y) * 1440)] == [450, 235]
    assert [round(float(width) * 2560), round(float(height) * 1440)] == [100, 270]
