# Anonymous startup proposals: two bounded controls

Neither control loads publisher labels, assigns cow names or runs Cutie. Both use all actual cached detector proposals in the exposed first two frames, at0 and0.5seconds. The detector trained on early frames of this same recording, so even a clean-looking result is optimistic startup feasibility, not another-farm validation. Seconds3000 onward remain closed.

The earlier eight-mask initializer is not an automatic baseline: it segmented eight proposals that a reviewer had already selected from twelve. The [new frozen first control](detection_startup_masks_protocol.json) instead ran SAM2.1tiny CPU FP32 at1024 on **all12 and8 proposals**, keeping every original mask and rejection. It required at least90%of mask pixels inside the prompt; removed mask-IoU duplicates at.8 by detector confidence/index; rejected both candidates for remaining intersection exceeding.1of the smaller mask; then required a unique temporal mask-IoU link at.5. It did not remove clipped or small objects simply because they would be unsuitable naming photos.

| Anonymous mask outcome | Original fixed rule | Added containment stage |
| --- | ---: | ---: |
| First frame survivors | 6 | 8 |
| Second frame survivors | 6 | 7 |
| Unique two-frame confirmations | 4 | 6 |

These are candidate-mask counts, not identity accuracy or biological recall. The [original control report](results/2026-10-03/detection/startup-mask-control.json) remains unchanged. Both SAM calls plus saved outputs took1.27seconds on CPU; no GPU or model training was used.

## What independent source review found

Two reviewers inspected every original mask with its clean source context before opening per-proposal selection outcomes or publisher truth. Both were already familiar with the recording, which is disclosed. The frozen [cattle review](results/2026-10-03/detection/startup-mask-review-cattle.json), [audit review](results/2026-10-03/detection/startup-mask-review-audit.json) and [comparison](results/2026-10-03/detection/startup-mask-review-comparison.json) agree on all duplicate-body groups; one moving-animal mask was described as either partial legs or minor leg-boundary loss. Neither reviewer established a clear merged two-torso mask in these20 outputs.

The important duplication was **partial anatomy inside a fuller animal mask**. Such pairs contained93.5–99.2%of the smaller mask, but their union-IoU was only.509–.697. Original.8IoU suppression removed none; subsequent ambiguity rejection removed their useful fuller masks too. This is a causal explanation, not permission to lower thresholds until the count looks right.

## One separately frozen containment control

The [second protocol](detection_startup_containment_protocol.json) and [result](results/2026-10-03/detection/startup-mask-containment.json) retain all original rules, including temporal.5. They add one stage after the original support/IoU suppression:

- A strictly larger mask containing at least.9of a smaller mask may suppress that fragment. Process candidate parents by area, then original confidence/index.
- If a parent contains two candidate children whose mutual intersection is at most.1of the smaller child's area, mark the parent and **all** its contained children ambiguous. This may also reject a real parent with separate head/torso parts; the geometric rule cannot decide whether those are two animals, so there is no scene-specific exception.
- Apply the unchanged remaining-overlap rule afterward, then assign only minor shared pixels in the original deterministic confidence order. Names are never introduced.

Before reporting the new result, the script exactly reproduced both original decision records and both original disjoint-mask arrays. Four new regressions plus the original five passed, including the deliberately ambiguous parent+head+torso case. No SAM call, new pixels or threshold sweep was needed.

The resulting suppression pairs exactly match the independently reviewed partial/full relationships: initial06/08/09yield to07;11yields to05; second-frame07yields to06. The multi-part guard did not trigger on these actual candidates, so its practical behavior is supported only by the explicit synthetic regression, not measured new-farm performance.

Two failures remain unchanged. The central moving animal has mask-IoU **0.495343**, so it fails the fixed.5temporal requirement even though source review identifies a coherent moving body. The top-border animal has no second-frame detector proposal. No extra cutoff adjustment is justified by those two observations.

The next useful decision is whether a **single exact-frame set of anonymous proposals**, visibly reviewed while the farmer supplies names, is a simpler and more useful startup contract. That would need a separate explicit test and stale-frame-safe confirmation. These controls do not yet establish an unattended empty-core initializer, correct multi-object insertion or long-term tracking from the new masks.
