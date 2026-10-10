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
