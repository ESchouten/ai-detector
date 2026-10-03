"""Synthetic ownership changes test quarantine without cow labels or video data."""

import json
from pathlib import Path

import numpy as np
import pytest
from detection_cutie_quarantine import CollisionQuarantine


def tracker():
    rules = json.loads(
        Path(__file__).with_name("detection_cutie_quarantine_protocol.json").read_text()
    )
    return CollisionQuarantine(rules, (3, 7))


def separated():
    mask = np.zeros((8, 8), dtype=np.uint8)
    mask[:4, :4] = 3
    mask[:4, 4:] = 7
    return mask


def initialized():
    subject = tracker()
    for second in range(30):
        assert subject.observe(second, separated(), {3: 0.9, 7: 0.9}) == set()
    return subject


def test_disappearance_requires_neighbor_ownership_not_just_a_missing_object():
    subject = initialized()
    mask = separated()
    mask[mask == 3] = 0
    assert subject.observe(30, mask, {7: 0.9}) == set()
    assert subject.events == []


def test_absorption_blocks_both_original_ids_without_changing_pixels():
    subject = initialized()
    mask = separated()
    mask[mask == 3] = 7
    mask[0, 0] = 3
    original = mask.copy()
    assert subject.observe(30, mask, {3: 0.95, 7: 0.95}) == {3, 7}
    assert np.array_equal(mask, original)
    event = subject.events[0]
    assert event["anchor_second"] == 29
    assert event["reference_area"] == 16
    assert event["receiver_anchor_fraction"] == 15 / 16
    # A prolonged missing slot cannot erase the saved reference by aging its median.
    for second in range(31, 64):
        assert subject.observe(second, mask, {3: 0.95, 7: 0.95}) == {3, 7}
    assert subject.observe(64, separated(), {3: 0.9, 7: 0.9}) == {3, 7}
    assert subject.observe(65, separated(), {3: 0.9, 7: 0.9}) == {3, 7}
    assert subject.observe(66, mask, {3: 0.9, 7: 0.9}) == {3, 7}
    assert subject.observe(67, separated(), {3: 0.9, 7: 0.9}) == {3, 7}
    assert subject.observe(68, separated(), {3: 0.9, 7: 0.9}) == {3, 7}
    assert subject.observe(69, separated(), {3: 0.9, 7: 0.9}) == set()
    assert subject.events[-1] == {"second": 69, "kind": "restored", "pair": [3, 7]}


def test_anchor_uses_past_quality_and_collapse_boundary_is_strict():
    subject = tracker()
    for second in range(30):
        probability = 0.95 if second == 10 else 0.8
        subject.observe(second, separated(), {3: probability, 7: 0.8})
    mask = separated()
    mask[:3, :4] = 7
    # Four remaining pixels are exactly25% of16; only a strict collapse triggers.
    assert subject.observe(30, mask, {3: 0.99, 7: 0.99}) == set()
    mask[3, 0] = 7
    assert subject.observe(31, mask, {3: 0.99, 7: 0.99}) == {3, 7}
    # The recent tiny high-confidence mask cannot replace an adequate past anchor.
    assert subject.events[0]["anchor_second"] == 10
    with pytest.raises(ValueError, match="consecutive"):
        subject.observe(33, mask, {3: 0.9, 7: 0.9})
