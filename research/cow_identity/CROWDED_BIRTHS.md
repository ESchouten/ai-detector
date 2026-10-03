# Anonymous births in the exposed crowded scene

This is one fixed follow-up to two failures: removing the initial anonymous
calf masks caused 19.60% unknown false naming, and an uninitialized physical
entrant inherited the old name in the Purdue passage. Initializing that passage
entrant anonymously prevented its four wrong names, but left uncertain mask
fragments. The crowded control tests the same birth rules without a new search.

The 3,059 inputs cover only the already exposed 0–1529 seconds at 2 fps. The
same six named masks are initialized at time zero; unknown animals 7 and 8 are
not initialized. All eight publisher identities remain in the original three
1 Hz scoring panels, 330–629, 930–1229 and 1230–1529. The two unknown animals
are already physically present initially, so this is unknown discovery in a
crowd, not a second physical-arrival benchmark. No reserved pixels are used.

## Isolating proposal cadence

The previous baseline inferred raw detector proposals only at integer seconds.
Birth confirmation needs two consecutive half-second observations. A separate
pre-inference freeze, `detection_birth_cache_protocol.json` SHA256
`4a301ccc48edf17ea15031c9e0ede6fa1554e9324371d3e869be98264b494cf4`, bound the
source, original proposals, checkpoint, precision and helper code before filling
the missing half seconds.

The original 1,530 integer proposal arrays were copied verbatim with matching
source hashes. The missing 1,529 half-second arrays were inferred using the
same mixed detector, FP16 MPS, confidence 0.4, image size 640 and NMS IoU 0.7.
This cache stage made no SAM/Cutie calls and evaluated no births. It completed
in 26.598 seconds, of which 23.745 seconds were recorded model inference. The
complete 3,059-row cache SHA256 is
`7ac8a806e07ed21d0102327d16109fb7006d76c59a018662eedbe4d419bf2004`.

An independently written CPU checker replayed the original six-seed masks and
objects using the cached integer proposals, a fresh quarantine and the unchanged
naming decisions. Every box, object summary, proposal, reciprocal pair, name,
conflict and quarantine event matched across all 1,530 integer timestamps.
Its report is `results/2026-10-03/detection/birth-no-op-parity.json`. This proves
logical parity when births are disabled, without pretending to be an additional
full GPU replay. Half-second proposals cannot affect that disabled arm.

## One frozen propagation arm

The final `detection_birth_protocol.json` SHA256 is
`2b07540a4796072968518eda6b6bc93fb97cbe17e787092332090eccb8a0a54f`.
All 49 source bindings and all 3,059 aligned source/cache rows passed independent
review. The prior preflight manifest is archived; its only amendment corrected
the timing description before execution.

The runner uses the unchanged passage birth functions: two uniquely associated
candidate observations, previous/current occupied geometry protection, nested
duplicate rejection, same-frame SAM prompts, foreground overlap checks, new
anonymous stable IDs and exactly one indexed Cutie step per timestamp. Cutie
remains FP32 MPS; SAM tiny remains CPU FP32 at 1024. Quarantine retains its
integer-second history; new objects have zero area/probability in older rows.
All half-second decisions are recorded, but only integer decisions are scored.

There is no deletion, name acquisition or ID reuse. More than eight live slots
immediately stops the control and preserves the triggering attempt. The budget
comes from the previously exercised bounded cohort, not an instruction to find
the expected number of truth animals. An incomplete run is reported as a failed
control, without fabricated full-panel accuracy. Anonymous scoring slots use
`cow=None`; they are never assigned a publisher identity by their slot number.

## Timing and limits

`frame_seconds` measures propagation, same-frame SAM, decisions and mask writes.
It excludes source decode/hash before the loop body and Metal reclamation after
the timer. Total elapsed includes initialization, decode/hash and reclamation,
but is set before the final report write. Detector cache filling is separately
measured. These values must not be presented as measured joint live throughput.

Even if this control improves names, it cannot establish biological identity
after exit/re-entry, reconnect safety, mask retirement, unbounded uptime or
unseen-farm performance. The original and passage failures remain preserved.

## Completed fixed control

The run completed all 3,059 inputs without a resource or object-budget stop.
Anonymous stable IDs 7 and 8 were created at 5.0 and 24.0 seconds. Their IDs
are object bookkeeping, not inferred publisher animal identities. The original
six names were the only names ever allowed.

| Exposed panel | Correct / visible known | Coverage | Conservative named precision | Wrong known / unknown named / unmatched named |
| --- | ---: | ---: | ---: | ---: |
| 330–629 s | 1266 / 1800 | 70.3333% | 99.2163% | 0 / 0 / 10 |
| 930–1229 s | 1100 / 1795 | 61.2813% | 99.4575% | 0 / 0 / 6 |
| 1230–1529 s | 1077 / 1799 | **59.8666%** | 99.3542% | 0 / 0 / 7 |
| Pooled | 3443 / 5394 | 63.8302% | 99.3364% | 0 / 0 / 23 |

The third panel **fails** the frozen 60% coverage requirement; pooled success
does not override it. No unknown was named among 1,796 visible unknown
observations. The prior six-seed no-birth control named 352 unknown observations,
so anonymous discovery materially improves safety on this exposed recording.
This does not replace reserved or independent-farm evaluation.

Propagation, same-frame SAM, decode and cache handling took 750.81 seconds.
There were 54 SAM attempts in 20.21 seconds: two accepted births and 52 rejected
attempts between 1285.5 and 1336.5 seconds. A CPU replay of every saved candidate
mask reproduced the fixed decisions exactly. All 52 were rejected for overlap
with existing foreground, specifically original slot 6; the first overlapped
86.67% of the smaller mask. None failed prompt containment or mutual new-mask
overlap. The rejected attempts therefore did not consume new IDs. See
[birth-attempt-audit.json](results/2026-10-03/detection/birth-attempt-audit.json).

Mean recorded frame processing was 237.4 ms, with p95 285.4 ms and p99 602.6 ms;
the precise timer exclusions above still apply. Peak post-reclamation Metal
driver allocation was 6.42 GB and peak resident memory 1.78 GB. Detector cache
filling remains separate; this is not a measured joint live throughput result.

## Where coverage is lost

[detection_birth_losses.py](detection_birth_losses.py) reuses the original
maximum-cardinality IoU ≥0.5 matching and verifies all per-cow totals against
both official reports. It makes no model calls or threshold selections.
The comparator is the actual joint eight-initial-slot control, including two
anonymous masks from frame zero, not the failed six-slot control.

| Cow | 330–629: eight initial → dynamic | 930–1229: eight initial → dynamic | 1230–1529: eight initial → dynamic |
| --- | ---: | ---: | ---: |
| 1 | 208 → 209 | 270 → 270 | 243 → 202 |
| 2 | 182 → 179 | 198 → 160 | 235 → 208 |
| 3 | 205 → 213 | 214 → 156 | 250 → 203 |
| 4 | 144 → 146 | 254 → 234 | 270 → 245 |
| 5 | 262 → 274 | 238 → 203 | 118 → 106 |
| 6 | 239 → 245 | 119 → 77 | 110 → 113 |
| Total | 1240 → 1266 | 1293 → 1100 | 1226 → 1077 |

Each entry counts correct names, not a percentage. Each cow has 300 visible
observations per panel except cow 6, with 295 and 299 in the last two panels.

For the final panel, 192 formerly correct observations are lost and 43 previously
suppressed observations are gained. Of those 192 losses, 157 fail **only** the
unchanged p10 confidence gate, 22 fail only quarantine, six lose their localization
match, four fail only reciprocal detector confirmation and three fail combined
gates. Cow 4 accounts for the 22 quarantine-only losses. Cows 1, 2 and 3 account
for 46, 32 and 49 p10-only losses, respectively.

Across all correctly owned, geometrically matched known observations in that
panel, low-p10 vetoes increase from 275 to 396, whereas reciprocal-detector
vetoes decrease from 79 to 72. These counts overlap with other vetoes; they must
not be added as independent losses. No-localization observations increase from
157 to 190, and boxes matched to a different original/anonymous slot increase
from 37 to 47. The latter cases receive no inherited name. In the middle panel,
p10 vetoes also rise, 337 → 482; cow 6 additionally has 80 localization misses
versus 25, and the new run has 104 matched observations under quarantine.

Here, a localization miss means no propagated component box obtained the
original strict truth match. It does **not** necessarily mean YOLO produced no
proposal. The complete exclusive combinations and matched-observation deltas
are in [birth-coverage-losses.json](results/2026-10-03/detection/birth-coverage-losses.json).
The result supports investigating changes in mask competition/confidence before
weakening any safety gate.

An implementation difference deserves a separate controlled test: the original
eight masks entered one SDK memory bucket, while six initial masks plus births
at 5 and 24 seconds enter three insertion buckets. Upstream currently performs
pixel/query readout per bucket. Consequently, delayed mask content, missing
early competition and cross-bucket object context are confounded in this run.
The observed confidence losses do not by themselves establish which is causal.

## Could startup initialize every animal anonymously?

Yes as a reviewed workflow; it is not yet an automatic completeness claim.
The saved first frame has twelve actual proposals in both the original CPU
FP32 pass and the current MPS FP16 pass. Eight visually reviewed proposals
`[4, 7, 2, 3, 1, 0, 5, 10]` cover all eight visible animals; rejected duplicates
are `[6, 8, 9, 11]`. Their eight existing SAM masks are mutually disjoint.
Initializing those masks anonymously before assigning six explicit names is
consistent with the successful eight-slot control. Name entry need not decide
whether an animal has a tracking object.

However, the existing automatic birth duplicate rule cannot initialize this
frame completely. With an empty scene it retains only proposals `[1, 2, 3, 10]`.
Alongside the real duplicate clusters, it rejects proposals 0 and 4, which are
**two different adjacent foreground calves**, because their boxes overlap 55.9%
of the smaller box. Keeping all twelve would create duplicate objects and exceed
the eight-object budget. Choosing the highest confidence in each overlap group
would also discard a real animal and need not choose the best complete crop.

A minimal honest workflow would therefore show proposed anonymous masks for
one-time single-animal/duplicate review, then let the farmer name the animals
they recognize while leaving the rest anonymous. A fully automatic mask-based
initializer requires a separate test: masks for the rejected duplicate proposals
were not produced in this control, and overlapping boxes alone do not distinguish
neighbors from duplicates. The first frame was included in detector training,
and reviewed CPU bounds differ slightly from live MPS bounds. These limitations
remain explicit in [startup-proposal-audit.json](results/2026-10-03/detection/startup-proposal-audit.json).
