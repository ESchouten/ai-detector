from event_names import stretches


def test_events_are_whole_stretches_that_do_not_overlap():
    present = [True, True, True, False, True, True, True, True, True]

    assert stretches(present, 2) == [[0, 1], [4, 5], [6, 7]]
    assert stretches(present, 4) == [[4, 5, 6, 7]]
    assert stretches(present, 6) == []
