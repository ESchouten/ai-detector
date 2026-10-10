from held_back import split


def photograph(cow, time):
    return {"cow": cow, "date": "20230825", "time": time}


def test_the_latest_fifth_of_each_cows_photographs_is_held_back():
    rows = [photograph(1, f"1{minute}0000") for minute in range(10)]
    rows += [photograph(2, f"0{minute}0000") for minute in (5, 1, 4, 2, 3)]

    earlier, later = split(rows)

    assert [row["time"] for row in later if row["cow"] == 1] == ["180000", "190000"]
    assert [row["time"] for row in later if row["cow"] == 2] == ["050000"]
    assert len(earlier) == 12
