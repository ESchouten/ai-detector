"""Human naming of one camera's continuously tracked, temporary instances.

This state is separate from gallery-photo enrollment and appearance matching.
The owning worker supplies opaque instance IDs, not reusable SDK channels. Its
adapter binds an exact retained snapshot to a LiveTarget, validates source/run/
epoch and expiry, and rejects frames that are not currently reviewable. This
module does not decide whether pixels establish tracking continuity.
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class LiveTarget:
    """Instance and state version captured when a review snapshot was published."""

    instance_id: str
    generation: int
    revision: int


@dataclass(frozen=True)
class ConfirmedIdentity:
    """A human's assignment carried through continuity, never an appearance score."""

    identity_id: str
    name: str
    evidence: Literal["human_confirmed_continuity"] = field(
        default="human_confirmed_continuity", init=False
    )


@dataclass(frozen=True)
class ConfirmationResult:
    status: Literal["confirmed", "stale", "identity_in_use"]
    target: LiveTarget | None
    identity: ConfirmedIdentity | None


@dataclass
class _Instance:
    target: LiveTarget
    identity: ConfirmedIdentity | None = None


class LiveIdentityState:
    """Bounded, single-owner naming state for exactly one camera.

    Catalog IDs and labels have already been validated by the adapter. The
    caller owns registration, retirement and declared continuity loss. A
    temporary quality gate may hide a name without invalidating it; deciding
    when continuity is lost is deliberately outside this component.

    Generations never repeat in this state, even after reset or accidental
    reuse of a retired instance ID. Only active instances and one integer
    counter are retained; snapshot storage and request idempotence live at the
    transport boundary. A successful confirmation changes the revision, so
    retries must reuse the transport's result rather than replay the mutation.
    """

    def __init__(self, max_instances: int = 8):
        if max_instances < 1:
            raise ValueError("At least one active instance must be allowed")
        self._max_instances = max_instances
        self._generation = 0
        self._instances: dict[str, _Instance] = {}

    def add(self, instance_id: str) -> LiveTarget:
        """Register an anonymous instance; never evict another animal silently."""
        if instance_id in self._instances:
            raise ValueError("Instance is already active")
        if len(self._instances) >= self._max_instances:
            raise ValueError("Active instance limit reached")
        self._generation += 1
        target = LiveTarget(instance_id, self._generation, 0)
        self._instances[instance_id] = _Instance(target)
        return target

    def target(self, instance_id: str) -> LiveTarget | None:
        state = self._instances.get(instance_id)
        return state.target if state is not None else None

    def identity(self, instance_id: str) -> ConfirmedIdentity | None:
        state = self._instances.get(instance_id)
        return state.identity if state is not None else None

    def confirm(
        self, target: LiveTarget, identity_id: str, name: str
    ) -> ConfirmationResult:
        """Assign or correct a name only while the reviewed target is current."""
        state = self._instances.get(target.instance_id)
        if state is None:
            return ConfirmationResult("stale", None, None)
        if state.target != target:
            return ConfirmationResult("stale", state.target, state.identity)
        if any(
            other.target.instance_id != target.instance_id
            and other.identity is not None
            and other.identity.identity_id == identity_id
            for other in self._instances.values()
        ):
            return ConfirmationResult("identity_in_use", state.target, state.identity)
        state.identity = ConfirmedIdentity(identity_id, name)
        state.target = LiveTarget(
            target.instance_id, target.generation, target.revision + 1
        )
        return ConfirmationResult("confirmed", state.target, state.identity)

    def invalidate(self, instance_id: str) -> LiveTarget:
        """Declare continuity lost, clearing its name and all old review targets.

        This is not a temporary quality/visibility gate. If an ambiguous track
        cannot be linked safely to the same animal, its caller must use this
        transition (or retire it) before publishing new review snapshots.
        """
        state = self._instances[instance_id]
        self._generation += 1
        state.target = LiveTarget(
            instance_id, self._generation, state.target.revision + 1
        )
        state.identity = None
        return state.target

    def retire(self, instance_id: str) -> None:
        """Release an instance and its name when the caller ends its lifecycle."""
        self._instances.pop(instance_id, None)

    def reset(self) -> None:
        """Forget this camera's assignments after an epoch or session reset."""
        self._instances.clear()
