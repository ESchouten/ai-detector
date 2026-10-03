# Continuous joint-readout extension through second 2999

The fixed method **does not pass every required panel**. It reproduces the entire earlier 3,059-input development prefix exactly and completes the continuous extension within its resource limits, but the 2700–2999 panel fails the 99% conservative precision requirement. No thresholds, seeds, references, masks, annotations or acceptance gates were changed after these results.

| Scored video seconds | Correct names / visible known | Known coverage | Conservative named precision | Unknown animals named | Named unmatched boxes | Fixed gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1800–2099 | 1135 / 1799 | 63.09% | 99.56% | 0 / 591 | 5 | Pass |
| 2700–2999 | 1331 / 1781 | 74.73% | 97.87% | 0 / 512 | 29 | **Fail precision** |

Both panels have zero wrong names among one-to-one matched known animals. This does not excuse the 34 named unmatched boxes: they remain errors in the conservative metric. Their biological identity and geometric cause require separate visual review; these counts alone do not show that they are harmless annotation differences. Pooling both panels gives 68.88% coverage and 98.64% conservative precision, which cannot replace the failed individual panel.

The runner processes all 5,999 half-second inputs continuously from time zero, producing all 3,000 integer decisions. Only the original six confirmed identities exist; new object IDs 7 and 8 are anonymous and were created at 5.0 and 24.0 seconds. There are two SAM calls, totaling 0.91 seconds, and no later additions, deletion, identity acquisition or reseeding. All eight publisher animals remain in each score denominator, including visible partial animals and all misses.

The full prefix comparison checks every earlier mask, probability summary, box, proposal, name decision, object mapping, SAM decision and quarantine event through second 1529, including the period after both anonymous births. It found zero differences. The same isolated joint-readout SDK, model weights, 2 Hz input, 1 Hz quarantine history, p10/reciprocal gates and eight-object/8 GiB limits are retained.

## Runtime and provenance

The actual MPS FP32 propagation run took **1398.35 seconds** (23 minutes 18 seconds), including initialization, source decoding/hash verification and cache reclamation. Detector predictions were already cached: this is **not measured joint live application performance**. The 1,470 newly needed half-second detector calls took 22.11 seconds of synchronized FP16 MPS inference, with 33.77 seconds total cache-fill elapsed time; 4,529 prior source-bound prediction arrays were reused verbatim.

Peak observed Metal driver allocation was 6.43 GB after reclamation and 7.06 GB before reclamation; process peak RSS was 1.58 GB. No safety cap was reached. The recorded propagation/SAM/decision/mask-write stage averaged 219.4 ms/input, with p95 263.7 ms; that stage excludes source decoding and cache reclamation.

- Cache freeze: `detection_birth_extended_cache_protocol.json`, SHA256 `9537417cf2cfcfc9a533bdcf04cbadc3cbd3e9a17cadf2564b8464d89f8227e8`.
- Complete cache: `.cache/cow-cutie/birth-extended-proposals.json`, SHA256 `200be440cfd8b83b913395087542e112c8f19829a804ff1122ca7efcfa74c363`.
- Execution freeze: `detection_birth_extended_protocol.json`, SHA256 `a4ccf625671acde3115bf8f56276c67310584305ace8a08b66331ed7e2a5fa5a`.
- Immutable run: `.cache/cow-cutie/crowded-joint-extended/streaming.json`, SHA256 `4aaaa8efca1bbe75d5b885ac003d8b285d1e90a6366476e0cc3f45646c5710d5`.
- Strict report: `results/2026-10-03/detection/crowded-joint-extended.json`, SHA256 `c2a1eef350ead52f87cc87665bfb2382c238de169ebc377ef220bfd49ee2eac7`; includes exact full-prefix parity.

Independent preflight verified all 148 bound execution inputs, the fixed method and all 5,999 source/proposal correspondences. Eight focused CPU tests cover cache conflicts, source corruption, preserving raw detector evidence, full closed-loop prefix comparisons and policy-change rejection. The independent final audit, `results/2026-10-03/detection/crowded-joint-extended-independent-audit.json` (SHA256 `54e89fc54e071051f75250df472fb02a330e444755e52b4e17ca86ede336cc42`), reproduced all source/prefix checks, denominators and named counts without calling the original scorer. It confirms the final-panel failure.

These are **previously exposed within-video regression panels**, not a fresh held-out test or an independent farm. The calf detector includes early frames from this same video in its training data. Original names are simulated confirmations linked to publisher identities and AI-reviewed actual detector/SAM proposals, not a farmer field study. Source pixels from second 3000 onward remain unopened. The failure is preserved; no production promotion follows from this experiment.
