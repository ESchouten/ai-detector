# Unknown animals without initial tracking masks

Status: prepared on CPU; no inference or results yet. This is an exposed-video
deployment control, not a new blind evaluation or a physical arrival study.
GPU execution must wait for the parent's current reserved run and an explicit
slot release.

## The smallest credible next experiment

The selected continuous candidate starts with six named masks and two anonymous
masks. Those anonymous masks may materially prevent named objects from absorbing
unknown cows. The control therefore removes only initial masks 7 and 8 and
reruns Cutie from time zero. All pixels owned by named initial masks 1–6 are
verified unchanged. Removing anonymous output boxes from an existing eight-slot
run would not be equivalent: the network's competition and temporal memory would
already have seen those objects.

[The separate protocol](detection_uninitialized_protocol.json) preserves the
selected network, precision, two-frame-per-second cadence, raw YOLO
corroboration, quarantine, recovery, naming gates and resource limits. It uses
only seconds 0–1529 and reports the original three exposed panels 330–629,
930–1229 and 1230–1529. Known cows remain 1–6. The scorer still loads all eight
publisher animals, including unknown 7 and 8, with missed and named-unmatched
boxes retained. One control, no threshold selection and no gallery changes.

The quarantine donor/receiver registry now contains exactly stable slots 1–6.
This omission is intentional: a detector cannot use the missing unknown masks
as collision anchors. Ground truth 7/8 appears only in scoring, never in
quarantine or recovery. Report each panel's precision, known coverage and
unknown naming plus the named-slot-to-biological-cow confusion table. A name
jumping to an unknown cow is an error even if its mask geometry is otherwise
convincing. Compare with the completed eight-slot joint baseline without tuning
the new control.

Both omitted cows are already visible at frame zero. The result can establish
whether **uninitialized unknown animals** destabilize known names in this
recording; it cannot validate a cow physically entering from outside the view.
Such a claim needs a separately selected actual entry event or another video.
No reserved footage is selected for that purpose here.

## Implementation and tests

[detection_uninitialized.py](detection_uninitialized.py) prepares a six-mask
manifest and delegates execution to the unchanged joint streaming runner. It
explicitly requires six contiguous named slots and forbids dynamic addition or
deletion. [The scorer](detection_uninitialized_score.py) reuses the strict source
validation and full annotation metrics without invoking the eight-slot mask
parity comparison.

Three CPU tests pass: initial named pixels remain unchanged; absent seed IDs
remain in unknown denominators and can accrue wrong-name counts; noncontiguous
stable IDs preserve probability summaries after channel compaction. An
additional direct probe of the pinned upstream `ObjectManager` adds IDs 7 and
42, deletes 7, and verifies that surviving object 42 moves from probability
channel 2 to channel 1 without changing its .95 confidence summary.

The original `mask_diagnostics` uses `probabilities[object_id]`, which is valid
for the existing immutable contiguous-slot experiment. It is unsafe for a
future dynamic runner after deletion. The separate tested
[cutie_object_state.py](cutie_object_state.py) requires an explicit
object-ID-to-current-channel mapping obtained from upstream `find_tmp_by_id`.
Upstream `output_prob_to_mask` already remaps tensor channels into stable object
IDs. No frozen inference helper was changed.

## A subsequent dynamic-add experiment, only if needed

Do not add identity prediction to this experiment. Candidate arrivals start
anonymous. Use the same raw YOLO class/confidence settings and current pixels;
never select a candidate by publisher ID, annotation overlap or expected animal
count. A practical fixed next design is:

1. At the existing one-second detector cadence, retain proposals with no current
   reciprocal match to any tracked object using the existing IoU .5 criterion.
   Track candidate boxes through three consecutive observations with unique
   mutual IoU .5 association; reset ambiguity or absence. These constants reuse
   existing corroboration and three-observation confirmation scales, with no
   parameter grid.
2. Candidate persistence authorizes a segmentation attempt, not an animal ID.
   Use the existing pinned SAM model on its latest raw YOLO box and that exact
   source frame. Retain the raw prompt and mask for audit. Refuse a merged or
   overlapping mask rather than overwrite existing animals. Freeze a technical
   mask-overlap acceptance rule before any measured dynamic run; it is not
   selected in this document.
3. Insert an accepted mask with a newly allocated opaque object ID and no name.
   Do not infer that it is one of the original unknown animals. Only a later
   independently verified human-style confirmation could give it a biological
   name. No identity truth participates in deciding which mask to add.
4. Score known-name stability and all unknown-name errors exactly as before.
   Separately report candidate counts, rejected/duplicate masks, anonymous
   discovery latency, false additions, number of SAM calls and incremental
   latency/memory. A correct mask addition is not correct re-identification.

The order of inference needs explicit design. The existing runner first calls
Cutie, then YOLO for the same frame. Calling `core.step` again on that frame to
insert a newly generated mask would increment its time index twice. Applying
that old mask to the next moving frame is also invalid. A dynamic runner must
prepare a pending proposal's SAM mask on a fresh current frame **before its one
Cutie step**, or use an upstream API whose same-frame update semantics have
been verified. This should be unit-tested before GPU measurement.

## Lifecycle work cannot be skipped

- Stable object handles and compact tensor channels are different namespaces.
  Addition/removal must use the tested mapping for probabilities, quarantine and
  published boxes. Persistent cow IDs are a third namespace.
- `CollisionQuarantine` currently freezes its object registry and historic area
  dictionaries at construction. Dynamic objects require a deliberate register/
  retire operation; do not silently clear all established history or assume a
  new ID has past anchor evidence.
- Never recycle an object handle into a previous live name. Deletion clears
  only that object's pending confirmations and masks. Camera epoch changes
  clear the entire camera session as described in
  [the workflow assessment](CONTINUOUS_IDENTITY_WORKFLOW.md).
- Set a fixed active-object and SAM-work limit and retire confirmed absent
  anonymous objects. At the limit, leave new animals unnamed rather than reuse
  live slots or exceed the frozen resource budget. The first bounded control
  can avoid deletion, but that does not validate an unattended 24-hour system.
- The current research PNG masks are uint8. A long-running monotonic object-ID
  allocator must not wrap at 255; storage needs a bounded remapping with an
  explicit epoch or a suitable wider indexed format.

The six-seed control should finish and be independently assessed before this
dynamic branch gains a frozen implementation or consumes GPU time.
