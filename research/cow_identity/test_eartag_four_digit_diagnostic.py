from eartag_four_digit_diagnostic import line_score


def row(text, x):
    return {"text": text, "polygon": [[x, 0], [x + 10, 0], [x + 10, 10], [x, 10]]}


def test_four_digit_output_on_longer_number_is_an_extra_not_a_correct_suffix():
    result = line_score(
        [row("0024", 0), row("12024", 20)], [row("0024", 0), row("2024", 20)]
    )
    assert result["target_lines"] == result["correct"] == 1
    assert result["emitted_four_digit_lines"] == 2
    assert result["extra_on_non_four_digit_truth"] == 1


def test_duplicates_wrong_digits_and_omitted_targets_remain_errors():
    result = line_score(
        [row("0024", 0), row("1984", 20), row("9999", 40)],
        [row("0024", 0), row("0024", 0), row("1985", 20)],
    )
    assert result["correct"] == 1
    assert result["extra_unmatched"] == result["wrong_four_digit_target"] == 1
    assert result["targets_not_correctly_read"] == 2
    assert result["target_lines"] == result["emitted_four_digit_lines"] == 3
