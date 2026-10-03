import pytest

from aidetector.domain.live_identity import ConfirmedIdentity, LiveIdentityState


def test_confirmation_is_human_evidence_and_old_browser_cannot_overwrite_correction():
    state = LiveIdentityState()
    first_snapshot = state.add("instance-a")
    first = state.confirm(first_snapshot, "cow-1", "Bella")

    assert first.status == "confirmed"
    assert first.identity is not None
    assert first.target is not None
    assert first.identity == ConfirmedIdentity("cow-1", "Bella")
    assert first.identity.evidence == "human_confirmed_continuity"
    corrected = state.confirm(first.target, "cow-2", "Daisy")
    assert corrected.status == "confirmed"
    assert corrected.target is not None
    assert corrected.target.revision == first_snapshot.revision + 2
    stale = state.confirm(first_snapshot, "cow-1", "Bella")
    assert stale.status == "stale"
    assert stale.identity == ConfirmedIdentity("cow-2", "Daisy")
    assert state.identity("instance-a") == corrected.identity


def test_same_cow_cannot_name_two_instances_and_rejected_correction_preserves_both():
    state = LiveIdentityState()
    a = state.add("a")
    b = state.add("b")
    named_a = state.confirm(a, "cow-1", "Bella")
    named_b = state.confirm(b, "cow-2", "Daisy")
    assert named_b.target is not None

    blocked = state.confirm(named_b.target, "cow-1", "Renamed Bella")
    assert blocked.status == "identity_in_use"
    assert blocked.target == named_b.target
    assert state.identity("a") == named_a.identity
    assert state.identity("b") == named_b.identity

    # A failed correction did not consume the target's revision.
    changed = state.confirm(named_b.target, "cow-3", "Molly")
    assert changed.status == "confirmed"
    assert state.confirm(state.add("c"), "cow-2", "Daisy").status == "confirmed"


def test_continuity_loss_invalidates_snapshot_and_name_without_touching_another_cow():
    state = LiveIdentityState()
    a = state.confirm(state.add("a"), "cow-1", "Bella")
    b = state.confirm(state.add("b"), "cow-2", "Daisy")
    replacement = state.invalidate("a")
    assert a.target is not None

    assert replacement.generation != a.target.generation
    assert state.identity("a") is None
    assert state.identity("b") == b.identity
    assert state.target("b") == b.target
    assert state.confirm(a.target, "cow-1", "Bella").status == "stale"
    assert state.confirm(replacement, "cow-1", "Bella").status == "confirmed"


@pytest.mark.parametrize("end_lifecycle", ["retire", "reset"])
def test_instance_id_reuse_never_revives_old_snapshot_after_lifecycle_end(
    end_lifecycle,
):
    state = LiveIdentityState()
    before = state.confirm(state.add("reused"), "cow-1", "Bella")
    assert before.target is not None
    if end_lifecycle == "retire":
        state.retire("reused")
    else:
        state.reset()

    assert state.target("reused") is None
    assert state.identity("reused") is None
    assert state.confirm(before.target, "cow-1", "Bella").status == "stale"
    replacement = state.add("reused")
    assert replacement.generation > before.target.generation
    assert state.confirm(before.target, "cow-1", "Bella").status == "stale"
    assert state.confirm(replacement, "cow-1", "Bella").status == "confirmed"


def test_capacity_failure_never_evicts_active_names_and_retirement_releases_capacity():
    state = LiveIdentityState(max_instances=1)
    named = state.confirm(state.add("a"), "cow-1", "Bella")
    with pytest.raises(ValueError, match="limit"):
        state.add("b")
    with pytest.raises(ValueError, match="already active"):
        state.add("a")
    assert state.target("a") == named.target
    assert state.identity("a") == named.identity

    state.retire("a")
    assert state.confirm(state.add("b"), "cow-1", "Bella").status == "confirmed"


def test_independent_camera_owners_may_each_confirm_the_same_cow():
    first = LiveIdentityState()
    second = LiveIdentityState()
    a = first.confirm(first.add("a"), "cow-1", "Bella")
    b = second.confirm(second.add("b"), "cow-1", "Bella")
    assert a.status == b.status == "confirmed"
    first.reset()
    assert second.identity("b") == b.identity
