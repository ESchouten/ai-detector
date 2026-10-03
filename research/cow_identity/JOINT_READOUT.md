# Joint readout across insertion-time memory buckets

This is an isolated research control, not an application change or an established
upstream defect. The completed [crowded birth control](CROWDED_BIRTHS.md) reduced
wrong names but failed the last panel's coverage requirement: 1077/1799,
59.8666%. Many lost names failed the unchanged mask-probability gate. This
motivates checking the SDK's handling of objects inserted at different times;
it does not establish the cause of those losses.

## The single behavior change

Upstream `MemoryManager.read` groups objects by insertion time, retaining a
separate affinity/readout for each memory history. It also runs pixel fusion and
the object-query transformer separately for each group. Consequently, the
fuser's previous-frame `last_others` masks and the transformer's auxiliary
foreground competition include only that group. Final decoder soft aggregation
already includes every object; upstream objects are not entirely independent.

[cutie_joint_readout.patch](cutie_joint_readout.patch) preserves each group's
affinity, visual memory readout and usage updates, then stacks those readouts in
the current `ObjectManager` order for one joint fusion/query call. Unequal memory
lengths remain separate before that stack. The control uses `chunk_size=-1` and
rejects positive chunk sizes. No weights, detector settings, masks, naming
thresholds, birth policy or scoring rules are changed. The changed predictions
can naturally change subsequent birth decisions and memory contents.

This is **not cross-object self-attention**: the transformer still treats
batch×object as separate attention batches. The paper describes standard mask
and soft-aggregation interaction and reports that its early additional
transformer-interaction experiments did not improve results. It does not promise
an improvement from this specific control. See
[Cutie, Appendix E.1](https://arxiv.org/html/2310.12982v1#A5.SS1).

The patch cannot fix identity after re-entry, provide a biological name to a new
object, or replace the separately identified retirement fixes. No deletion is
used in this experiment.

## Pinned source and real SDK proofs

| Artifact | SHA256 / commit |
| --- | --- |
| Upstream base commit | `ec5cdd4cf16f75c73ad785a2f96fb97dbad4125a` |
| Isolated local candidate commit | `da31fdb10f5ce4b02bbf023f912d082f0929cbb5` |
| Patch SHA256 | `fae5cec51533a059e13163effa6fd9ae9e31cdc4c092fc6ce0aed695f86befee` |
| Official Cutie base-mega checkpoint | `9c05402ee36d3a356fb72715d263ba7e1ea06ad3bada48c1306491792da43023` |
| Proof protocol | `ea3a6a28bf079fbfb16661e4dcf052b19c1b044ab06d05c221132a3d716802ed` |
| CPU report | `c8f7f9f8b38669f5f133983891ecc42d85efe8e0a57f56c42d35850a3e9e31f9` |
| MPS report | `2e91d21feb027ee379141824d5e3d51f038f4f2f237e0b84b8627a6ac31d96c2` |

The candidate is `/tmp/cow-cutie-joint-readout`; the original
`/tmp/cow-identity-cutie` is untouched. The candidate commit is a local synthetic
snapshot for reproducibility, not an upstream release. Only
`cutie/inference/memory_manager.py` differs in SDK behavior; the separate runtime
packaging and retirement patches are not included.

[The proof recipe](cutie_joint_readout_proof_protocol.json) was frozen before
execution and binds the script, patch, both SDK source trees/configurations,
checkpoint and library versions. [The executable](cutie_joint_readout_proof.py)
strictly loads one shared network, disables network access and runs both real
SDK memory implementations. No animal images or annotations enter this proof.

Both [CPU](results/2026-10-03/detection/cutie-joint-readout-cpu.json) and
[Metal](results/2026-10-03/detection/cutie-joint-readout-mps.json) passed the same
recipe with application Torch 2.12.1 and actual FP32 parameters:

- All twelve 96×128 single-bucket outputs, including initialization, are
  bit-exact between the original and candidate **within each backend**.
- IDs 7, 42 and 91 inserted at steps 0, 2 and 4 produce three distinct memory
  histories of 288, 240 and 192 tokens. Their temporary channel mapping remains
  correct and outputs remain finite and normalized.
- Real network hooks observe one joint fusion/query call with all active
  objects and global other-object masks, versus three original calls after all
  three insertions.
- Identical copies of the same post-birth state yield bit-exact per-bucket
  affinities, visual readouts and usage updates. Stable-ID output mapping is
  exact; positive chunk sizes are rejected.

CPU completed the whole instrumented proof in 2.31 seconds with process peak
RSS 601,849,856 bytes. MPS completed it in 3.55 seconds with process peak RSS
846,413,824 bytes and maximum sampled Metal driver allocation 218,382,336 bytes.
The proof enforced an 8 GiB RSS/driver limit after steps. Driver samples are
outside individual kernels and do not measure transient activation peaks.
No reclamation was needed in this small run. Timing includes model setup and
both variants with instrumentation, so it is not a speed comparison.

Long-term mode is enabled, but these twelve steps do not trigger memory
consolidation. The proof does not establish full-resolution memory limits,
long-run stability, retirement, camera throughput or cattle accuracy. Joint
activation batches and the additional stack can increase peak memory even
when they reduce neural call count. MPS and CPU predictions were not asserted
equal to each other.

## Fixed animal controls

The following progression was specified in draft protocols before either
candidate animal run. Each final protocol must bind its completed prerequisites
and all exact inputs before launch. Results remain separate from the original
failed/successful controls; no thresholds are selected from these reruns.

1. **Exposed Purdue passage first:** same 22 inputs, original named mask and
   anonymous birth policy; all nine known and fourteen unknown observations,
   uncertain cases and empty frames retained. Require at least seven correct
   names; zero wrong-known, unknown, unmatched or empty-frame names; no inherited
   name on the entrant; zero mask pixels on empty frames and the final frame.
   A failure stops progression. Planned freeze:
   `passage_entry_joint_readout_protocol.json`; report:
   `results/2026-10-03/purdue-entry-joint-readout.json`.
2. **Crowded control only after that passage passes:** same 3,059 inputs at
   2 fps through 1529 seconds, six named initial masks and anonymous births;
   all eight truth animals and 1,530 integer observations retained. Each original
   panel (330–629, 930–1229, 1230–1529) independently requires ≥60% known coverage,
   ≥99% conservative named precision and ≤1% unknown false naming. Named
   unmatched boxes remain errors. Keep the eight-object and 8 GiB limits; no
   deletion, cap relaxation or replacement of failed panels by pooled scores.
   Planned freeze: `detection_birth_joint_readout_protocol.json`; report:
   `results/2026-10-03/detection/crowded-joint-readout.json`.

## Completed development results

The unchanged [passage scorer](results/2026-10-03/purdue-entry-joint-readout.json)
records eight correct names among nine visible known-animal observations, up
from seven. None of fourteen unknown-animal observations receives a name, and
there are no wrong-known, unmatched or empty-frame names. All five empty frames
contain zero foreground pixels. The anonymous birth still occurs at 2 seconds.
The four inputs before that birth match the original run exactly, including
probabilities and masks. This small regression passes, but the old object's
unnamed geometry still drifts onto the entrant later in the sequence. Suppressed
output does not prove that biological ownership remained correct internally.

The [full crowded control](results/2026-10-03/detection/crowded-joint-readout.json)
also passes every original development panel:

| Panel, seconds | Correct / visible known | Coverage | Conservative precision | Named unmatched boxes |
| --- | ---: | ---: | ---: | ---: |
| 330–629 | 1287 / 1800 | 71.50% | 99.15% | 11 |
| 930–1229 | 1346 / 1795 | 74.99% | 99.34% | 9 |
| 1230–1529 | 1413 / 1799 | 78.54% | 99.30% | 10 |

There are no wrong-known or unknown-animal names across 1,796 visible unknown
observations. Pooled coverage is 4046/5394, 75.01%, and conservative precision is
4046/4076, 99.26%. The thirty unmatched named boxes remain errors. These are
correlated observations of a few animals in already exposed footage, not
independent trials or an unseen-farm estimate.

An [independent CPU recount](results/2026-10-03/detection/crowded-joint-readout-independent-audit.json)
verified all 3,059 source/counter records, the exact 1,530 integer-row subset,
the original six-name mapping and all eight animals' denominators. Explicit
outcome accumulation reproduced every panel's named counts and acceptance gates
without calling the main scorer; it retained the same frozen one-to-one IoU
matcher. This checks accounting independently, not the biological truth labels.

All 3,059 inputs completed, with the same anonymous births at 5 and 24 seconds.
The ten pre-birth inputs are bit-exact against the original control. SAM was
invoked twice, both accepted, instead of 54 times. Working/long-term memory
reached 30,000/29,696 tokens without exceeding the eight-object or 8 GiB limits.
Elapsed time fell from 750.81 to 682.94 seconds; recorded input time was 215 ms
mean, 262 ms p95 and 284 ms p99. Observed peak process RSS was 1.79 GB and
post-reclamation Metal driver allocation reached 6.43 GB. These timings use cached
detector proposals, exclude some per-input bookkeeping, and are not complete
live-camera throughput. The two SAM invocations took 0.945 seconds altogether.

The original failed reserved test remains unchanged. Later exposed panels still
need this exact candidate, and seconds 3000 onward remain closed. The candidate
has not yet established actual departure/re-entry, cross-day recognition,
human confirmation burden or application integration. Passing development alone
does not complete the identity goal.
