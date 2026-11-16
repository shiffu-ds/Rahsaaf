import numpy as np
import pytest

from worker.plates import PlateRead, PlateVoter, crop_vehicle, looks_like_plate, normalise


def read(text, confidence=0.95):
    return PlateRead(normalise(text), confidence)


@pytest.mark.parametrize(
    "raw, clean",
    [("lea-1234", "LEA1234"), (" ABC 123 ", "ABC123"), ("A·1234", "A1234"), ("", "")],
)
def test_normalise(raw, clean):
    assert normalise(raw) == clean


@pytest.mark.parametrize("text", ["LEA1234", "ABC123", "A1234", "PSR12", "AB1234", "LEA1234A"])
def test_real_plate_shapes_are_accepted(text):
    assert looks_like_plate(text)


@pytest.mark.parametrize("text", ["", "12", "1234", "ABCDEF", "1234LEA", "ABCDE123", "LEA12345", "L3A1234"])
def test_non_plates_are_rejected(text):
    assert not looks_like_plate(text)


def test_agreeing_reads_give_a_plate():
    voter = PlateVoter()
    for _ in range(3):
        voter.add(read("LEA 1234", 0.9))
    result = voter.result()
    assert result.readable
    assert result.text == "LEA1234"
    assert result.confidence == 0.9
    assert (result.reads, result.agreeing) == (3, 3)


def test_a_single_read_is_never_enough():
    voter = PlateVoter()
    voter.add(read("LEA1234", 0.99))
    result = voter.result()
    assert not result.readable
    assert result.reason == "reads did not agree"


def test_majority_wins_over_a_misread():
    voter = PlateVoter()
    for text in ["LEA1234", "LEA1234", "LEA1284", "LEA1234"]:
        voter.add(read(text))
    result = voter.result()
    assert result.text == "LEA1234"
    assert (result.reads, result.agreeing) == (4, 3)


def test_a_tie_is_unreadable_not_a_coin_toss():
    voter = PlateVoter()
    for text in ["LEA1234", "LEA1234", "LEA1284", "LEA1284"]:
        voter.add(read(text))
    result = voter.result()
    assert not result.readable
    assert "equally common" in result.reason


def test_low_confidence_is_unreadable():
    voter = PlateVoter(min_confidence=0.7)
    for _ in range(3):
        voter.add(read("LEA1234", 0.5))
    result = voter.result()
    assert not result.readable
    assert result.reason == "reader was not confident enough"


def test_agreed_text_that_is_not_a_plate_is_unreadable():
    voter = PlateVoter()
    for _ in range(3):
        voter.add(read("TOYOTA", 0.99))  # a badge, not a plate
    assert voter.result().reason == "text does not look like a plate"


def test_no_reads_and_empty_reads():
    voter = PlateVoter()
    voter.add(None)
    voter.add(read("", 0.9))
    result = voter.result()
    assert not result.readable
    assert result.reason == "no plate found"
    assert result.reads == 0


def test_settled_once_agreement_is_clear():
    voter = PlateVoter()
    voter.add(read("LEA1234"))
    voter.add(read("LEA1234"))
    assert not voter.settled
    voter.add(read("LEA1234"))
    assert voter.settled


def test_unreadable_result_still_keeps_the_clearest_picture():
    voter = PlateVoter()
    blurry, clear = np.zeros((2, 2, 3), np.uint8), np.ones((2, 2, 3), np.uint8)
    voter.add(PlateRead("LEA1234", 0.3, blurry))
    voter.add(PlateRead("LEA1284", 0.6, clear))
    result = voter.result()
    assert not result.readable
    assert result.image is clear


def test_crop_scales_box_to_the_full_frame_and_adds_margin():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    crop = crop_vehicle(frame, (100, 100, 300, 200), scale=2.0, margin=0.1)
    # Box becomes 200..600 x 200..400 at full size; 10% margin each side.
    assert crop.shape[:2] == (240, 480)


def test_crop_stays_inside_the_frame_and_rejects_tiny_boxes():
    frame = np.zeros((100, 100, 3), np.uint8)
    assert crop_vehicle(frame, (-20, -20, 60, 60)).shape[:2] == (64, 64)
    assert crop_vehicle(frame, (10, 10, 15, 15)) is None


# --- two-line plates: the year badge must not be read as part of the number ---

import numpy as np  # noqa: E402

from worker.plates import combine_two_line, split_row  # noqa: E402


def chars(text, score=1.0):
    return [(c, score) for c in text]


def test_year_badge_is_removed_using_the_bottom_line():
    # "ABC·17" over "357", read whole as ABC1735.
    assert combine_two_line(chars("ABC1735"), "ABC17", "357", 0.97) == ("ABC357", 0.97)


def test_agreeing_readings_are_left_alone():
    full = [("L", 0.9), ("E", 0.95), ("F", 0.99), ("3", 0.8), ("5", 1.0), ("0", 1.0), ("3", 1.0)]
    assert combine_two_line(full, "LEF12", "3503", 1.0) == ("LEF3503", 0.8)


def test_unsure_bottom_line_that_disagrees_gives_no_reading():
    text, confidence = combine_two_line(chars("MN3101"), "MN", "5101", 0.82)
    assert confidence == 0.0


def test_confidence_comes_from_the_letters_and_the_bottom_line():
    full = [("A", 0.75), ("B", 0.9), ("C", 0.9), ("1", 0.2), ("7", 0.2), ("3", 0.2), ("5", 0.2)]
    assert combine_two_line(full, "ABC17", "357", 0.95) == ("ABC357", 0.75)


def test_dropped_letter_gives_no_reading():
    # Whole plate read as LE85242 (B taken for 8); the top line shows 3 letters.
    text, confidence = combine_two_line(chars("LE85242"), "LEB15", "4524", 1.0)
    assert confidence == 0.0


def test_one_line_plates_are_not_touched():
    # Bottom half reads as a city name, not a number.
    assert combine_two_line(chars("ACD946"), "ACD946", "SINDH", 0.9) is None
    assert combine_two_line(chars("BF373"), "ICT", "BF373", 0.9) is None
    assert combine_two_line(chars("AEW731"), "AEW731", "", 0.0) is None


def test_trailing_letter_on_the_bottom_line_is_kept():
    assert combine_two_line(chars("LEA175989A"), "LEA17", "5989A", 0.95) == ("LEA5989A", 0.95)


def test_reading_with_no_letters_is_not_touched():
    assert combine_two_line(chars("1632"), "AB", "1632", 1.0) is None


def test_split_row_finds_the_gap_between_two_lines():
    plate = np.full((100, 200, 3), 255, np.uint8)
    plate[10:42, 60:180] = 0   # top line of text
    plate[58:92, 60:180] = 0   # bottom line of text
    assert 42 <= split_row(plate) <= 58


def test_split_row_works_on_a_dark_plate_with_light_text():
    plate = np.zeros((100, 200, 3), np.uint8)
    plate[10:42, 60:180] = 255
    plate[58:92, 60:180] = 255
    assert 42 <= split_row(plate) <= 58
