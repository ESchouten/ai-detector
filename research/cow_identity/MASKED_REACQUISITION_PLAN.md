# A bounded test of varied, explicitly confirmed reference photos

Status: proposed only. No new reference review, model inference or recognition comparison has run for this control. Seconds 3000 onward remain closed.

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
