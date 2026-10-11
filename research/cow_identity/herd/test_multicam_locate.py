import cv2
import numpy as np

from multicam_locate import corners, details, difference, fitted, followed, moved

FRAME_DETAILS = cv2.SIFT_create(nfeatures=3000)


def frame_and_picture():
    """A frame of blotches, and a picture cut out of it at a quarter turn."""
    generator = np.random.default_rng(0)
    blotches = cv2.GaussianBlur(generator.random((600, 800)).astype(np.float32), (0, 0), 6)
    frame = cv2.normalize(blotches, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    # A picture's corner (0, 0) lies at (500, 150) in the frame, its width running downward.
    laid = np.array([[0.0, -1.0, 500.0], [1.0, 0.0, 150.0]])
    picture = cv2.warpAffine(frame, cv2.invertAffineTransform(laid), (300, 160))
    return frame, picture, laid


def test_a_picture_is_laid_back_where_it_was_cut_from_its_frame():
    frame, picture, laid = frame_and_picture()

    transform = fitted(details(picture), details(frame, FRAME_DETAILS))

    assert np.allclose(transform, laid, atol=1)
    assert difference(frame, picture, transform) < 2
    assert np.allclose(corners(laid, 300, 160), [[500, 150], [500, 450], [340, 450], [340, 150]])


def test_a_picture_does_not_fit_a_frame_it_was_not_cut_from():
    frame, picture, _ = frame_and_picture()
    other = cv2.flip(frame, 1)

    assert fitted(details(picture), details(other, FRAME_DETAILS)) is None


def test_a_walk_is_followed_both_ways_through_frames_that_were_skipped():
    frame, picture, _ = frame_and_picture()
    seen = details(frame, FRAME_DETAILS)
    nothing = (np.empty((0, 2), np.float32), np.empty((0, 128), np.uint8))
    # The walk's three pictures are the same cut-out; a cow fills frames 0, 15 and 20 only.
    frames = {0: seen, 5: nothing, 10: nothing, 15: seen, 20: seen}

    tried = followed(["first", "second", "third"], 1, 15, frames, lambda _: details(picture))

    assert sorted((position, number) for position, number, _ in tried) == [(0, 0), (2, 20)]


def test_only_something_as_large_as_a_cow_counts_as_movement():
    passage = np.full((180, 320), 100.0)
    frame = np.full((1440, 2560), 100, np.uint8)
    # A cow in a pen shows 20 by 20 points of the shrunk frame, a cow that walks by 30 by 60.
    frame[80:240, 80:240] = 200
    assert moved(frame, passage) is None

    blotches = frame_and_picture()[0]
    frame[480:960, 1200:1440] = cv2.resize(blotches, (240, 480))
    points, described = moved(frame, passage)

    assert len(points) == len(described) > 0
    assert points[:, 0].min() >= 1100 and points[:, 1].min() >= 380
    assert points[:, 0].max() <= 1540 and points[:, 1].max() <= 1060
