# A bounded test of varied, explicitly confirmed reference photos

Status: the frozen two-gallery comparison is complete and fails useful recognition coverage. The 39 independently reviewed references do not improve the pooled result. Further variants of this reference collection are not justified. Seconds 3000 onward remain closed.

The [corrected selection protocol](recognition_masked_pilot_v2_protocol.json) produced 58 of 60 possible bin winners and twelve review questions, two per initial named slot. The [selection](results/2026-10-03/recognition/masked-reference-pilot-v2-selection.json) was frozen before any photo viewing; the [render record](results/2026-10-03/recognition/masked-reference-pilot-v2-render.json) binds exact foreground crops, untouched context and all six initial comparisons. Review sheets omit the suggested name so each candidate can be compared with every known animal. A first preflight confused zero-based tracks with one-based quarantine IDs; the original artifacts are retained, the corrected membership has a regression test, and the [comparison](results/2026-10-03/recognition/masked-reference-pilot-v2-preflight.json) confirms that no selected photo changed. The original twelve-photo selection and its initial review stage remain preserved; the final reviewed package is described below.

The unchanged application's crop policy cannot reach the target on the current ByteTrack queries, regardless of the reference photos. The [production-policy ceiling](results/2026-10-03/recognition/production-policy-ceiling.json) is only 131/1795 (7.30%) and 150/1799 (8.34%) eligible known observations in the 930–1229 and 1230–1529 panels. An idealized replay of the actual `GalleryIdentifier` with perfect known matches confirms 71 and 107 observations after its sampling, conflict and agreement rules. A gallery-only application experiment would therefore answer an already settled question.

A separate masked appearance diagnostic remains distinguishable from that unsuccessful approach. Earlier active enrollment added at most two new photos per cow; the proposed control replaces the complete ten-photo budget with individually confirmed views from a longer period. It neither trains another model nor searches thresholds.

## What the existing cache can and cannot answer

The [cache feasibility report](results/2026-10-03/recognition/masked-cache-feasibility.json) verifies the original MIEW encoder fingerprint and vector dimensions between `.cache/cow-cutie/miew-foreground` and the original sixty masked references in `.cache/cow-farm-evaluation/step-000/gallery`.

Both use unrotated foreground crops with background value 127. The references preserve their publisher-prompt rectangle after single-image SAM masking; the query crops use the tight largest connected component of a propagated Cutie mask. The reference contract mentions principal-axis alignment because that preparation also supported an aligned variant, but these vectors are explicitly the **masked**, unrotated variant.

The query cache comes from the historical Cutie run initialized with publisher-box SAM prompts. It is **not** the newer detector-proposal initialization. This diagnostic may test appearance on these predicted masks, but cannot establish farmer-ready initialization, real departure/re-entry, cross-day recognition or whole-application performance.

| Exposed query panel | All visible known | Matched mask crops | Unclipped crops at least 64 px | Also requiring mask p10 ≥ .7 |
| --- | ---: | ---: | ---: | ---: |
| 930–1229 | 1795 | 1749 (97.44%) | 1615 (89.97%) | 1313 (73.15%) |
| 1230–1529 | 1799 | 1651 (91.77%) | 1591 (88.44%) | 1294 (71.93%) |

These are availability ceilings, not recognition accuracies. Applying the original whole-rectangle overlap rule to these mask boxes leaves only 288 and 173 known observations. A masked diagnostic must therefore explicitly use the isolated foreground pixels instead of silently claiming the unchanged application's crop gate. Adding the old p10 gate and three consecutive perfect rejected/known observations gives only 1063/1795 and 1042/1799 in an idealized replay; that replay is not a mathematical upper bound because unmatched boxes can interrupt a physically correct track.

## Proposed single comparison

1. Freeze every input hash and the following choices before inspecting new recognition outcomes. Keep the original cache, gallery and prior negatives unchanged.
2. Use all existing query crops from 930–1229 and 1230–1529. Ignore every seed name. Reset naming state at each panel, retaining only anonymous track identifiers for three-observation agreement. The masks themselves still carry historical tracking information, which is an explicit limitation.
3. For this **appearance isolation** only, admit uncut masked crops with both sides at least 64 pixels. Do not apply rectangle overlap rejection after other-animal pixels have been removed; do not add a p10 quality sweep. Record mask confidence and overlap descriptively. Preserve every visible known/unknown animal and every unmatched prediction in the denominator.
4. Compare exactly two galleries: the original sixty SAM-masked references versus at most sixty newly confirmed, tight Cutie-masked references from the actual-proposal-seeded run at seconds 0–629. The old and new crop sources differ; this is a practical reference-package comparison, not a claim that chronology alone caused any change.
5. Candidate selection uses only past prediction quality: one candidate for each initial named slot in each fixed 63-second bin; require at least 64-pixel sides, no clipping, p10 ≥ .7 and the existing reciprocal detector confirmation with no recorded quarantine. Rank by p10, then area, then earliest timestamp. No query similarity, truth label or outcome influences selection. A missing or rejected candidate is not backfilled.
6. Before spending the sixty-question budget, independently review at most twelve proposed photos from the latter five bins against the initial confirmed examples and source context. Track names are suggestions, never labels. A photo enters the gallery only after explicit biological confirmation; ambiguity, mixed bodies, severe blur or insufficient identifying coat means rejection. Preserve all reviewed questions, including rejections. If the small review cannot establish useful identities, stop rather than manufacture labels.
7. Encode accepted new crops once with the same pinned original MIEW model and cache their embeddings. Compare all six known cows for **every** query slot, including the two initially anonymous slots. Use unchanged `.65` minimum similarity, `.10` margin, duplicate-name conflict rejection and three-observation agreement. A confident different name may be emitted and must count as wrong; unknown seed slots receive no special protection.
8. Report raw correct, wrong-known, unknown-named and unmatched-named counts; coverage against all visible known animals; conservative precision; per-cow coverage; reference/question counts; and the difference from the original gallery. Do not tune or select a threshold after either panel. No performance gain here becomes an application success claim.

The useful question is whether a bounded set of independently confirmed varied views improves appearance-based reacquisition on already available masked geometry. If it does not, collecting more variants of the same photos or training another small head is not justified by this control.

## A useful interim farmer workflow

Continuous within-camera tracking with explicit confirmation after continuity is lost can be useful in a stable pen, provided the interface clearly distinguishes a confirmed current track from durable recognition. A new camera epoch, departure or uncertain merge must not inherit a previous animal's name automatically. The practical cost must be measured as confirmations per cow-hour and time left unnamed. Frequent passage or cross-day operation may make repeated confirmation too burdensome. This workflow is a limited assisted mode, not completion of autonomous cow identity.

## Completed review and encoding freeze

The three pilot reviewers unanimously accepted seven of twelve photos. The two independent reviewers then assessed the forty remaining preselected noninitial winners, with no backfill, and accepted the same identity for twenty-six. Any uncertainty or disagreement rejected the photo. Six already confirmed initial photos plus these thirty-three new accepted photos produce **39 references**, distributed **10 / 10 / 2 / 2 / 5 / 10** across cows1–6. The weak coverage for cows3/4 remains part of the experiment.

The [final package](results/2026-10-03/recognition/masked-reference-final-package.json) preserves all **52 new photo questions**, including **19 uncertainties/disagreements**, every individual review, and exact foreground/context PNG hashes. This is52 distinct new photos requiring multiple AI judgments, not a measured human click burden or blinded farmer ground truth. No expected track name overrode a biological review.

The [reference encoding recipe](recognition_masked_encoding_protocol.json) binds the local MIEW weights, current app library versions, encoder/cache sources, all reviewed pixels and the package. It uses MPS FP32, batches of at most8, and the existing pixel-plus-encoder SQLite cache. Its required base fingerprint is `af1f90d85f31b9e5721a3606eb990adcb3807626aab573dbe202b51260533d0a`, matching the historical query encoder; the older research virtual environment does not match. No query inference, model training, augmentation or threshold adjustment is part of encoding.

The [encoding evidence](results/2026-10-03/recognition/masked-reference-encoding.json) records 39×2152 finite, normalized vectors and the verified matching fingerprint. Local MPS initialization and encoding took 2.15 seconds; the finished archive is `.cache/cow-masked-reviewed-gallery-v1`. All 197 frozen input hashes were rechecked afterward. This timing excludes live-camera processing.

## Fixed comparison result

The [comparison protocol](recognition_masked_comparison_protocol.json) was frozen with 219 input/source bindings before any new query scores were inspected.

| Gallery | 930–1229 correct / all known | 1230–1529 correct / all known | Both panels |
| --- | ---: | ---: | ---: |
| Original 60 references | 58 / 1795 (3.23%) | 24 / 1799 (1.33%) | 82 / 3594 (2.28%) |
| Reviewed 39 references | 26 / 1795 (1.45%) | 42 / 1799 (2.33%) | 68 / 3594 (1.89%) |

Neither package emitted a wrong-known, unknown, or unmatched name. These very low acceptance counts do not establish reliable identification. Both fail the 60% coverage requirement by a wide margin. The new package names only cows 2 and 6 in the first panel and only cow 2 in the second. The [full report](results/2026-10-03/recognition/masked-reference-comparison.json) retains every frame decision, unmatched detection, missed animal and per-cow denominator.

An [independent recount](results/2026-10-03/recognition/masked-reference-comparison-independent-audit.json) verifies all 219 input bindings, all 600 seconds per gallery, identical query geometry/eligibility and every per-cow denominator. It rematches boxes and counts decisions without calling the original replay matcher or `VideoMetrics`; all counts agree.

The matching function never receives a seed name or publisher label. All six enrolled identities compete for every anonymous query slot, including the two originally withheld animals. Missing, clipped and conflicting observations clear agreement; there is no name persistence. Tests cover arbitrary-slot naming, conflicting candidates, interrupted agreement, cache-row reuse and the full scoring denominator. The original gallery and the new one use different foreground crop construction, so this result does not isolate chronology or reference count as the sole cause.

**Decision:** reject this gallery replacement as a route to useful automatic reacquisition. Do not lower thresholds, add photo variants or train another small head on these outcomes. Continue evaluating continuous camera tracking with explicit human confirmation, while describing it separately from recognition after departure, restart or a change of day.
