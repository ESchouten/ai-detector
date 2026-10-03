# Anonymous initialization prevented this observed wrong name

The single frozen births-only run created one anonymous object at 2.0 seconds,
half a second after the first separate raw detector candidate at 1.5 seconds.
It made one current-frame SAM call. The original reviewed named seed was not
changed. No later identity prompt, gallery lookup, threshold search, rerun or
annotation input was used.

| Same 22 frames and reviewed truth | No additions | Anonymous births |
| --- | --- | --- |
| Correctly named known observations | 7/9 | 7/9 |
| Named precision including unmatched boxes | 7/11, 63.64% | 7/7, 100% observed |
| Unknown observations wrongly named | 4/14 | 0/14 |
| Names on empty frames | 0/5 | 0/5 |
| Last nonempty propagated mask | 8.0 s | 8.0 s |

This is a useful causal result on one exposed, detector-adapted passage. Seven
correct named observations and zero observed errors are not evidence of 99%
field reliability. Both arms keep the uncertain final fragment and all empty
frames. The full counts are in
`results/2026-10-03/purdue-entry-births.json`; the original failed baseline
remains in `purdue-entry-baseline.json`.

The execution protocol is `passage_entry_birth_protocol.json`, SHA256
`b75ede34b6cfe3f9266ad92d2b4c2c794c905fa6a0b67481a954613a07dda89a`.
An independent source audit verified all 63 bindings, original inputs, indexed
upstream insertion, stable ID/channel mapping, and complete scoring before the
parent authorized the one run. Focused CPU tests verify one upstream step per
timestamp, duplicate and ambiguous proposal rejection, and preservation of real
quarantine history when an object is born at a half-second timestamp.

Runtime was 6.678 seconds for all 22 inputs using app Torch 2.12.1, Cutie FP32
MPS, the existing Purdue FP32 MPS detector and SAM CPU. Peak observed MPS driver
allocation was 1,992,638,464 bytes. This short burst does not establish sustained
camera throughput or 24-hour memory behavior.

## What improved, and what remains wrong

The new anonymous mask initially covers the entering animal while the original
mask still follows the departing one. The anonymous slot matches the entrant
from 2.0 through 6.0 seconds. The previous name-inheritance failure at 5.5–7.0
seconds is suppressed by the unchanged confidence gate.

However, later both slots divide the entrant's body into competing fragments.
At 6.5–7.0 seconds the original slot again supplies the best geometric match to
the entrant. Its p10 remains near 0.5, so its old name stays hidden. There are
11 unnamed unmatched boxes across the sequence. Initialization therefore
improves competition and uncertainty; it does **not** establish permanent
ownership or solve deletion and re-entry.

Complete source/proposal and colored two-slot evidence is preserved in
`.cache/cow-passage-entry-births/review/`, with all 22 image hashes listed in
`results/2026-10-03/purdue-entry-birth-review.json`. Green is the original slot;
blue is the new anonymous slot. The 2.0-second and 6.5-second full frames were
visually inspected after scoring. No scores or parameters changed afterward.

The inherited single-slot quarantine description belongs to baseline
provenance. This arm has two slots after birth, but the sequence is shorter than
the quarantine's 30-second history. It cannot validate the dynamic quarantine
mechanism empirically; the real-history CPU test covers its bookkeeping only.

The next separate control uses the same birth rules on the already exposed
crowded calf sequence, with six named initial masks and no anonymous initial
masks. It must retain all eight truth identities, all three original panels,
and the fixed eight-object resource cap. No reserved footage or retrospective
identity labels may choose births. A failed or exhausted-cap run remains a
failure, without tuning this passage's success into a general claim.
