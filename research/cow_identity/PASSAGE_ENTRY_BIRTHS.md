# Anonymous births: proposed causal control

This is a separate research arm, not an application feature or a passing result.
The completed no-additions control and its 22-frame truth remain unchanged. It
showed the original named slot moving to a new animal. The entrant already has
an independent raw detector proposal before that transfer, making an anonymous
new mask a testable intervention.

The source, reviewed original seed, original known name 5676, detector/model
checkpoints, 2 fps input, p10 >= 0.7, reciprocal IoU >= 0.5 and 1 Hz quarantine
remain fixed. Only current detector boxes may prompt new SAM masks. Neither
publisher identities nor annotations enter the inference path. The entrant is
never named by this arm, even though its publisher identity is known to scoring.

## Fixed birth rules

These are conservative engineering constants, not thresholds fitted to query
scores. There will be one execution, no parameter sweep.

1. Before exactly one Cutie step for the current timestamp, obtain fresh raw
   whole-cow proposals using the existing frozen detector settings. Compare
   them with the previous output's active LCC boxes. A current proposal already
   reciprocally paired at IoU >= 0.5 is occupied. Previous boxes and those
   occupied current boxes both protect against duplicate births.
2. A candidate must overlap every occupied box by at most 0.1 of the smaller
   rectangle's area. Suppress **both** candidates when their mutual
   intersection/smaller-area is >= 0.5. This catches nested body fragments that
   can have low IoU. There is no arbitrary winner in an ambiguous pair.
3. Require a unique association to a candidate in the immediately preceding
   half-second using intersection/smaller-area >= 0.5. The containment measure
   allows an entering partial animal's box to grow. One-to-many and many-to-one
   associations abstain. Missing timestamps fail the run; missing proposals
   clear pending evidence. Mature proposals are consumed even if SAM rejects
   them, so a later attempt needs two new observations.
4. Prompt the existing SAM2.1 tiny model with only each mature **current** box,
   at the same CPU FP32/1024 configuration used for the original seed. Require
   nonempty source-sized masks and >= 90% of each mask's pixels inside its
   prompt. Reject when overlap with any previous active object exceeds 0.1 of
   the smaller foreground. Two new masks sharing any foreground pixel both
   abstain. Border contact alone is not a rejection: arrival starts at a border.
5. Sort accepted boxes geometrically for deterministic stable-ID allocation.
   IDs are positive and monotonically increasing, never biological labels.
   The initial slot remains 1; all births are anonymous forever. Stop rather
   than silently changing policy if total live slots would exceed eight, the
   largest cohort already exercised by the resource-bounded runner.
6. Construct an indexed mask containing only new IDs and background zeros.
   Invoke `core.step(image, mask, objects=new_ids, idx_mask=True)` **once**.
   Upstream propagates existing objects from memory and merges the new masks
   during that same step. Without births, call its normal unprompted step.
   Do not propagate first and then invoke a second step for insertion.
7. Read stable ID to temporary probability-channel mapping from upstream
   `ObjectManager` after every step. Do not use a stable ID as an array index.
   Cache indexed masks as uint16, with an explicit range check. There is no
   deletion, compaction, recycling, or biological name acquisition in this arm.

Previous geometry is intentionally conservative. Rapid motion may prevent a
birth or leave a duplicate unrecognized. Record those failures rather than
quietly weakening the separation gate. This short control cannot establish a
general multi-camera birth policy.

## Existing quarantine history

Register new stable IDs before the current naming observation. Extend the
existing quarantine's object-ID tuple. For every historical row, add area zero
and probability zero for each new ID; historical masks already have no pixels
with those IDs. Preserve original masks, history length, old areas,
probabilities, conflicts, restoration counters, and events exactly.

The half-second wrapper still observes quarantine at integer seconds only.
New-object absence before birth cannot supply an anchor. Established objects
must not lose their 30-second context because an anonymous object arrives.
The short passage still lacks a full quarantine warmup; do not claim quarantine
is what prevented any transfer if anonymous segmentation alone changes it.

## Tests and review before model calls

`passage_entry_births.py` is a small model-free policy module. Focused CPU tests
cover nested original-body duplicates, competing pending proposals, vanished
candidates, overlapping SAM masks, prompt containment, and noncontiguous IDs
without resetting historical state. Existing stable-channel compaction tests
also pass. A runner must additionally verify exactly one upstream step per
timestamp, indexed insertion, immutable initial pixels, and unchanged naming
gates. The final execution freeze must bind its implementation and tests.

No model calls or birth outcomes have been produced. The parent reviews the
fixed rules first; a complete source-bound execution protocol and independent
review precede any model run. The original baseline freeze is not rewritten if
production integration changes an otherwise shared domain file.

## Full scoring and unmet gates

Retain all 22 frames, nine known observations, 14 nameless observations including
the uncertain trailing fragment, and five empty frames. Report inherited names,
known coverage, empty-background names, raw mask disappearance, birth latency,
duplicate masks and total slots. Match both named and anonymous geometry to
truth only in the separate scorer. Preserve full-frame counts; definite-only
sensitivity may be reported separately.

Even a successful single-entrant control leaves deletion, long-running memory,
new animals after every slot is full, exit/re-entry, reconnection, identity
confirmation UX, and independent farm validation unmet. Old gallery photographs
must never silently reinstate the name of a new continuous slot.
