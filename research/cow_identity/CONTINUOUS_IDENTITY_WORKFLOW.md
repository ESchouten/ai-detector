# Farmer workflow for a prospective continuous identity tracker

Status: interface assessment with source-continuity safeguards implemented,
3 October 2026. Live confirmation and continuous Cutie tracking remain research
work. The frozen reserved trial failed precision, and the passage entry test
revealed a name transferring to an uninitialized newcomer. Following a cow after
a person names it is not evidence that the system can recognize it after it
leaves or on another day.

## Smallest honest user journey

Use the existing **Herd** page and camera preview. The primary instruction is
**“Name the cows in this camera.”** Explain once: **“Names follow cows while the
camera can keep track of them. We may ask you again after a lost connection or
when a cow returns.”** Do not promise one-time enrollment or automatic lifelong
recognition. A roster of saved names is useful even without appearance matching.

1. Choose a camera only when more than one is configured. Show the usual live
   view with quiet **Unnamed** labels on safely separated animals. Prepare and
   track anonymous masks before asking for names; an unreviewed animal must not
   inherit another animal's name.
2. Click **Identify** on one animal. Show a still image from the exact detector
   frame used for that object's mask, with the animal highlighted and surrounding
   context visible. Choose an existing tag/name or enter a new one, then
   **Confirm**. Keep the existing photo reference comparison when useful.
3. Apply the confirmation only if that same anonymous object has remained
   continuously valid. Otherwise show **“This cow moved out of view. Choose it
   again.”** Keep the entered name so the farmer does not have to type again.
4. Show the name on the live object and **Change name** on selection. **Not now**
   leaves an animal anonymous without stopping other detections. One named cow
   is sufficient for this tracking workflow; the existing two-cow requirement
   belongs to appearance matching, not manual confirmation.

Do not turn each frame into another task. Group review by current object,
retain a small bounded choice of clear views, and show one count such as
**“2 cows need names.”** Keep the list stable while the farmer is editing.
When crowded or merged masks cannot separate animals, ask for a clearer view
instead of offering an apparently precise clickable label or a drawing tool
as the default flow.

### Entrants and lost animals

An unmatched detector proposal is a candidate for a new anonymous mask, not a
known cow. Its proposed mask must be separated from existing objects and bound
to the same input frame. Keep its name empty until confirmed. The upstream
Cutie API can add new object IDs through `InferenceCore.step(mask, objects)` and
delete objects. The completed continuous runner seeds objects only at frame
zero; a separately frozen passage control is now testing anonymous births.
Dynamic entry, exit, mask correction and memory reclamation remain unvalidated
product behavior, not existing functionality.

If a track becomes ambiguous, hide the name and retain an anonymous object or
an attention state. A later detector box proves only that an animal is present;
it does not by itself establish that the original biological name survived an
occlusion. Any automatic recovery must use the independently validated policy.
For a first farmer trial, unresolved identity continuity should request a new
confirmation. Leaving and returning, appearing on another camera, or recovering
after a reset must never silently reuse a saved numeric tracker ID.

## Source continuity is a prerequisite

Live capture objects now carry an optional `CaptureStamp` with a connection
epoch, decoded-frame sequence and monotonic read time. Reopen, native geometry changes, backward capture time, and raw read gaps above
five seconds create a new epoch, preserved through shared resizing, inference and
snapshot mode. Gallery identity state clears only for the affected camera after
discontinuity; duplicate or delayed frames provide no new naming evidence.
Existing metadata-free finite sources retain timestamp-based continuity.

Relevant source:

- [Frame and Observation](../../detector/src/aidetector/domain/models.py).
- [Capture, reconnect and resize](../../detector/src/aidetector/adapters/sources/streams.py).
- [Persistent YOLO source slots](../../detector/src/aidetector/adapters/inference/yolo.py).
- [Identity agreement and retirement](../../detector/src/aidetector/adapters/inference/identity_observations.py).
- [Live preview run and freshness checks](../../web/src/lib/server/live-preview.ts).

The existing preview `runId` remains the process boundary. An unthrottled capture
epoch event now invalidates queued and in-flight preview results synchronously.
The session heartbeat carries current epochs and disconnected sources; the web
reader rejects old frames. Processing status includes its input epoch, so a late
old inference result cannot restore current readiness. Browser clearing follows
the heartbeat/poll cadence and is not instantaneous. Live confirmations still
need an object-specific target checked against current in-memory source state.

Start a new epoch on camera reopen, process restart, explicit camera replacement,
coordinate-system/resolution change or a declared continuity break. On a break,
clear all name associations, masks, temporal agreements and queued confirmation
commands for that camera. Each subscriber to the shared camera must observe the
same break. Do not reset unrelated cameras. Persist the roster and photos.
Raw capture checks wall and monotonic read times before detector sampling.
A backward clock or a gap above five seconds creates a new epoch even when the
camera socket stays open across sleep. This does not detect old frames buffered
inside camera firmware while reads continue normally.

The current YOLO adapter keeps a last image per source so a batch can preserve
tracker slots. Its inactive-camera placeholders never reach identity as new
evidence. The gallery must establish fresh agreement after a reconnect, even
when YOLO reuses a numeric track ID. A future Cutie adapter must create a fresh
source core on continuity loss, including its object manager and mask memory.

## Minimal interface contract

Keep durable animal records in the existing catalog. Keep live tracking bindings
in the detector process, scoped to one camera epoch. Do not save transient Cutie
state in `app.json`, `config.json`, the reference gallery, or settings backups.
No second configuration wizard is needed.

| Interface | Required meaning |
|---|---|
| Live target | Existing run ID, stable configured camera ID, camera epoch, opaque object handle/generation, frame sequence, exact snapshot/mask, current review state |
| Confirm name | Target token plus existing cow ID or proposed new name, roster revision and idempotent command ID |
| Acknowledgement | Applied target and revision, or an explicit stale/ambiguous/conflicting-target result; HTTP success alone must not imply a running detector accepted it |
| Live update | The same identity and epoch keys; discard events from old epochs before drawing names |
| History record | Immutable photo plus source, capture time and the target/confirmation provenance; history is evidence, not an active binding |

Resolve the opaque target on the owning worker. Do not let a browser select an
arbitrary raw Cutie channel number: object addition/deletion can alter temporary
indices. One animal name cannot be applied to two distinct simultaneous objects
in one camera. Reject the conflicting assignment with a choice to review the
other object, rather than silently moving the name. Renaming a stable cow ID can
update its displayed name without losing a valid association. Deleting the cow
or correcting a mistaken association must invalidate the affected binding and
stale submissions. Two browser tabs must not overwrite each other's confirmation.

The existing live camera feed and inference overlay can have different timing.
Therefore a click should open the exact inference snapshot, not assume the
currently displayed FFmpeg video frame matches an older mask. Track anonymous
objects while the person decides; if continuity becomes unsafe, reject that
target. Do not replay an old mask directly onto a current frame or pretend a
retained photo proves current location.

Use the existing authenticated local management boundary where practical, with
an explicit acknowledgement. The current managed-detector stdin stop command
is not already a complete interactive confirmation API. Avoid rewriting config
and restarting monitoring for every cow confirmation.

### Concrete implementation boundary, after the research gates

Use one optional continuous-tracking implementation of the existing
`ObjectDetector` port, assembled explicitly in `bootstrap.py`. It consumes the
same `StreamPool` subscription and returns ordinary `Observation` records. The
adapter owns the pinned Cutie SDK, model state, proposal model and masks; a small
pure policy owns whether a current object may retain a name. Do not put a second
capture loop, the research scorer, experiment manifests, or dataset-specific
class names into the application. The first supported rule should require
individual-animal proposals and the validated sampling cadence; a mounting-event
rectangle is not an individual identity target. Leave the current appearance
identifier as the separate, explicitly selected path. Do not silently chain its
unvalidated suggestions into persistent track names.

Keep one continuous identity rule per camera for the first trial. Multiple
ordinary detection rules still share capture and continue independently. Share
model weights where the SDK supports it, but own one `InferenceCore` and object
manager per configured camera. Run model operations on that rule's worker under
the existing MPS scope; the source callback and web request never touch tensors.
The measured one-camera memory budget does not establish a multi-camera limit.

An epoch/offline notification immediately marks that camera's live targets
invalid in a small locked map and wakes its worker. The worker clears the old
core, masks, quarantine history, pending births and confirmations before any
next inference or command. This combines immediate rejection with single-thread
SDK ownership. Frames from the previous epoch cannot recreate a disposed core.
Bootstrap owns closing and releasing all cores, including when processing fails.

Bound object state explicitly. Separate anonymous births may add a fresh stable
SDK ID, but can never inherit the previous occupant's name. A validated absence
policy can later call SDK `delete_objects`; retirement must discard its name,
review token and policy history together. Until that policy is measured, reaching
the object budget must stop new naming or reset the camera to anonymous with an
explicit notice. Silently evicting an active animal or recycling a handle is
unsafe. After deletion, resolve probabilities through `ObjectManager`, since
stable IDs and tensor channels are different. Never restore a deleted binding
from a saved numeric tracker ID, embedding suggestion, or persisted photo.

Do not call the pinned upstream retirement API unchanged. The separate
[CPU SDK proof](CUTIE_PACKAGING.md#object-retirement-needs-a-separate-sdk-correction)
found survivor-mask channel misalignment, retained object summaries and incomplete
permanent-memory cleanup. Its isolated patch addresses SDK state ownership, not
when an animal has truly departed. Neither the patch nor a retirement policy is
part of the application or the frozen birth experiments. An empty camera should
dispose its entire core, including historical object bookkeeping; bounded live
object count alone is not a long-running memory guarantee.

The smallest source changes would have these owners:

| Existing boundary | Narrow addition |
|---|---|
| `adapters/inference`, `application/ports.py`, `bootstrap.py` | Concrete continuous detector and a narrow live-confirmation operation wired to its owner; explicit configuration choice, no registry/factory framework |
| `runtime.py` | Small bounded command queue per rule, drained before processing and on existing idle batches; no command work on delivery threads |
| `cli.py`, `adapters/operational_status.py` | Versioned confirmation input and correlated acknowledgement; retain literal `stop` and EOF shutdown semantics |
| `adapters/live_preview.py` | Bounded exact snapshot/target records and source-epoch invalidation; no identity decision on the JPEG thread |
| `web/src/lib/server/managed-detector.ts` | Write to the current child's stdin and resolve only that child's acknowledgement; cancel pending requests on close, stop or deadline |
| Existing Herd action, `identity-catalog.ts`, preview reader and dialog | Revision-checked durable save, one exact-image confirmation flow, and separate live acceptance feedback |

The command can stay small: request ID, preview run ID, rule/source keys, source
epoch, opaque object generation, snapshot ID, cow ID and committed catalog
revision. The detector resolves those keys itself; the browser supplies neither
mask pixels nor arbitrary paths or raw channel numbers. Keep a bounded replay
record for idempotent acknowledgements within that run. A repeated request must
not rename a different object after a reset.

The complete interaction should be one sequence:

1. The existing preview exposes an exact analyzed snapshot with a bounded target
   token. Opening **Identify** pins that image and mask for the dialog; later
   preview polling does not replace the image under the farmer's choice.
2. The Herd action saves the reviewed photo/name through the existing catalog
   transaction and obtains the committed cow ID and revision. This save alone
   means durable evidence was recorded, not that a live object was named.
3. `ManagedDetector` serializes only the short stdin write with lifecycle
   operations. It awaits the acknowledgement outside that queue, so a slow
   detector cannot block **Stop monitoring** or **Quit**.
4. The owning worker validates the current run, source epoch, object generation,
   snapshot ownership, catalog revision, ambiguity and same-camera duplicate
   names before applying a binding. Check the epoch again atomically with the
   binding update so a simultaneous capture disconnect cannot win the race.
5. The status record acknowledges that request with the actual applied target
   and revision, or a clear stale/conflicting result. Only an acknowledgement
   from the same child/run resolves the browser request. On stale rejection say
   **“Photo saved. This cow is no longer current; choose it again.”**

A command queued while inference is running cannot be applied to a superseded
track afterward. A worker blocked in delivery or a native model may miss the
bounded command deadline; report that explicitly and cancel the request rather
than pretending confirmation succeeded. On catalog rename, keep the same stable
cow ID and refresh its label; deletion or reassignment invalidates affected live
bindings before further publication. Catalog and live state are separate
transactions, so report each result honestly rather than attempting a distributed
rollback of a valid photo save.

## Old photos, reconnects and the existing Herd page

[The current catalog](../../detector/src/aidetector/adapters/identity_catalog.py)
stores source hash, timestamp, numeric tracker ID, gallery revision and crop.
[The web assignment](../../web/src/lib/server/identity-catalog.ts) changes the
persistent reference catalog. It does not bind a currently visible track. Keep
that distinction explicit: **“Save this photo for cow 123”** can remain valid for
an old photo; **“Name this visible cow 123”** requires the live target contract.
Old photos and settings imports cannot become Cutie seeds merely because their
source or tracker number matches. Display captured date and camera for saved
evidence and never represent a saved photo as a live animal.

After reconnect, automatically resume camera detection and anonymous tracking.
Show one understandable message: **“Camera reconnected. Please confirm the cows
again.”** Existing animal names remain selectable, and unrelated cameras retain
valid state. This honors automatic monitoring restart without inventing identity
continuity across lost pixels. A settings backup restores names and reference
photos, not the assertion that particular cows are still in view.

## Trial gates before interface integration

- Reconnect in under five seconds with the same raw tracker IDs: no old name or
  pending confirmation survives.
- Sleep/wake, clock reversal, source resize and process restart: epochs change
  or continuity is explicitly invalidated before any new named output.
- Click a still frame, lose or merge its object, then confirm: stale request is
  rejected; another animal is never named by the old click.
- Add and remove an anonymous entrant: existing objects retain their correct
  stable handles despite temporary mask-index changes; memory remains bounded.
- Two tabs confirm, rename or delete a cow concurrently: one coherent revision
  and explicit acknowledgement determine the visible result.
- Import a catalog or review a week-old photo: no live name is created implicitly.
- Camera failure, crowded crossing and genuine animal exit/re-entry: measure
  wrong names, time unnamed and required human confirmations. Report the burden
  alongside accuracy; a system requiring constant relabeling is not an easy
  farmer workflow.

The next meaningful product experiment is a short continuous-camera session
with actual anonymous mask creation, several human-style naming delays, an
entrant and a reconnect. Initial manually supplied perfect masks alone do not
exercise that user journey. Freeze these scenarios before measuring them and
retain unknown output whenever current identity cannot be supported.
