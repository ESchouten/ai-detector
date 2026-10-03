# Ear-tag reader adaptation and numerical checks

The first fixed TrOCR experiment **did not beat the existing OCR reader**. Its
results remain unchanged. Subsequent checks found two concrete problems in the
training path: a CPU/MPS backward discrepancy and a second shift of the target
labels in the installed Transformers loss. A separately frozen CPU run with the
corrected loss improved TrOCR, but the complete detected-line pipeline still
falls short. Calibration and reserved images remain closed.

This study measures text recognition, not safe automatic cow naming. It does not
establish which printed field is the cow's identifier, tag-to-animal ownership,
reliability across independent video frames, or safe profile merging.

## Model and data

The selected library model is
[`microsoft/trocr-small-printed`](https://huggingface.co/microsoft/trocr-small-printed),
loaded with Transformers `VisionEncoderDecoderModel` and `TrOCRProcessor`.
The [TrOCR paper](https://arxiv.org/abs/2109.10282) describes adapting the architecture
to different text domains. This particular checkpoint was fine-tuned on SROIE
printed text lines; good handwriting performance is not assumed.

The official revision is `04e994ab854b0089d4929f48c2b4dbe2ce78a340`. Only its
safetensors weights and configuration/tokenizer files were downloaded, without
remote code or pickle weights. The weights occupy 245,839,136 bytes and have SHA-256
`49350a39968df83e5a1adc90fc0ede02ff247671aed70b842af350fd4a7103f3`.
All model assets total 247,203,503 bytes; the cumulative ear-tag study remains
inside the approved 550 MB download budget. The exact inventory is
[trocr-model-download.json](results/2026-10-03/ear-tags/trocr-model-download.json).

Training excludes **every image in any of the 64 pilot groups**. Removing those
303 images from the development split leaves 1,347 images in 478 groups, with
3,243 original annotated text lines. All their polygons and literal strings are
included. No invalid polygon, blank string or `#` placeholder was found in this
training subset. Labels have at most 7 characters and 5 tokenizer tokens including
special tokens. This does not authorize a character allowlist or output correction.
The 656 calibration and 597 reserved images remain unused.

The fixed data preparation uses the original SDK quadrilateral warp and the same
orientation classifier as the earlier OCR control. It saves each corrected line
as a PNG, then applies the official RGB 384-pixel processor with center cropping
disabled. It preserves leading zeros and punctuation, with no augmentation,
roster, relabeling or truncation. The two evaluation lists contain 157 oracle
lines and 118 original small-detector line crops; their reader inputs contain no
transcripts. See [data protocol](eartag_trocr_data_protocol.json).

## Original fixed experiment

The original [training and evaluation protocol](eartag_trocr_protocol.json), SHA-256
`1a3850e2095ba117f8e7bb3202706065af3c7a0975266078d8369d8e72388b57`, binds 3,541
files including weights, prepared crops, library source, code and tests.
Its settings were:

- Original weights, full-model FP32 training on MPS, two epochs, fixed seed and
  sample ordering, physical batch size 4 and gradient accumulation over 2 batches.
- AdamW with learning rate 0.00002, gradient clipping at 1, and the final checkpoint
  only. No checkpoint selection, model search or validation-based tuning.
- A training-only 20-step timing preflight, followed by a new process that reloads
  the original weights and creates a fresh optimizer.
- Greedy generation with one beam and at most 32 new tokens. No sampling,
  allowlist, roster or cleanup beyond the scorer's outer-whitespace strip.
- Tokenizer BOS/EOS/PAD IDs of 0/2/1 and checkpoint decoder-start/EOS/PAD IDs of
  2/2/1, asserted before execution. Padding is masked; labels are never truncated.

The preflight took 12.87 seconds and used at most 3.45 GiB of Metal driver memory.
The full run completed 812 optimizer steps, processing exactly 6,486 examples
(two passes over all 3,243 lines), in 381.83 seconds. Peak Metal driver allocation
was 3.63 GiB. No finiteness or resource stop occurred. The final safetensors hash is
`b03f142a9c50f6b5713fb219ed00421fc42787ff3add0b12c51299c5ff050238`.

The original checkpoint lacks the encoder pooling-layer weights. Transformers
initializes those unused parameters and warns about them. The bound model's
forward path consumes the encoder sequence features, not its pooled output;
the later diagnostic explicitly confirmed that both pooling parameters have no
gradient. This is separate from the material loss and backward issues below.

## Immutable accuracy result

All rows are raw, unthresholded results. TrOCR token evidence was not treated as
calibrated confidence or thresholded on the RapidOCR scale.

| Reader and localization | Correct lines / 157 | Wrong matched text | Missed lines | Extra predictions | Exact whole tags / 64 |
|---|---:|---:|---:|---:|---:|
| Original TrOCR, oracle polygons | 86 | 71 | 0 | 0 | 14 |
| Adapted TrOCR, oracle polygons | 115 | 42 | 0 | 0 | 29 |
| Original TrOCR, original small detector | 41 | 53 | 63 | 24 | 2 |
| Adapted TrOCR, original small detector | 56 | 38 | 63 | 24 | 5 |
| Existing small RapidOCR, oracle polygons | 116 | 41 | 0 | 0 | 31 |
| Existing small RapidOCR, its own detector | 74 | 20 | 63 | 24 | 12 |

Adaptation improved TrOCR relative to its own starting weights, but not relative
to the existing reader. Oracle character error fell from 24.41% to 11.37%; with
the fixed detector's missed and extra text included, it fell from 64.21% to 57.19%.
Replacing the reader cannot recover the 63 lines already missed by the detector.
Even perfect reading of every correctly localized line would therefore cover
only 94/157, or 59.87%, of the original lines. The 24 extra predicted regions also
remain in the evaluation; they are not removed by using oracle crops elsewhere.
Original and adapted reader inference on all 275 crops took 9.26 and 5.46 seconds,
including model initialization but excluding earlier crop preparation.

The complete result is [trocr-development-score.json](results/2026-10-03/ear-tags/trocr-development-score.json).
Both raw outputs and the training/preflight reports are stored alongside it. An
[independent pre-score audit](results/2026-10-03/ear-tags/trocr-score-independent-preflight.json)
verified all 3,541 top-level bindings, 162 nested source bindings and the exact
truth manifest. The frozen scorer does not itself recurse into the nested truth
hash, so that independent hash check was repeated immediately before scoring.
No source or truth was changed.

### Exact reader agreement

A separate [agreement protocol](eartag_reader_agreement_protocol.json) was frozen
before either TrOCR output was read. It accepts an original small RapidOCR
prediction only when its score is at least 0.95 and TrOCR returns exactly the same
stripped text for that crop. It performs no digit correction.

Adapted TrOCR agreement retained 56 predictions: 48 correct, 2 wrong matched and
6 extra texts. That is **85.71% precision and 30.57% coverage** of all 157 lines,
with 107 missed lines. Original TrOCR agreement retained 50 predictions with
39 correct, or 78% precision. Neither supports automatic naming. The result is
[reader-agreement.json](results/2026-10-03/ear-tags/reader-agreement.json).

## Numerical findings

### Different backward results after a fresh start

The preflight and full training process loaded the same original weights,
configuration and seed, and used identical first-20 sample ordering. All 3,541
bound inputs remained unchanged. Their first loss was identical, at
5.4397265911, but the first pre-clipping gradient norm was **247.84 versus
8,879,785**. Their first-20 losses later differed by as much as 2.57.

This is much larger than rounding. Finiteness alone did not establish reliable
training. No restart or retrospective checkpoint selection was used to replace
the result. See [fresh-reset audit](results/2026-10-03/ear-tags/trocr-fresh-reset-audit.json).

### CPU/MPS boundary and isolated matrix multiplication

A separately frozen [backward diagnostic](eartag_trocr_backward_protocol.json)
used the exact first eight training examples and original weights, with dropout
disabled but gradients enabled. All initial parameters matched exactly. Forward
logits differed by about 0.000005 in relative L2, but the full gradient difference
was 1.626 relative to CPU. The CPU-recomputed norm was 177.925 versus 288.186 on
both MPS runs. Native and independently recomputed norms agreed, ruling out a
misleading norm display alone. Repeated MPS gradients were close in this
particular dropout-disabled diagnostic. This does not explain all cross-process
training variation. The [full report](results/2026-10-03/ear-tags/trocr-backward.json)
retains every parameter comparison.

The subsequent [operator proof](eartag_trocr_operator_protocol.json) retained the
actual output-projection and last-normalization tensors from four training
examples. Projection output gradients agreed with CPU to 0.0000184 relative L2,
but projection input gradients differed by 5.36. Thus the discrepancy was already
present before the preceding normalization layer's backward operation.

The saved CPU inputs then reproduced the discrepancy in a plain FP32 matrix
multiplication: **16 × 64044 multiplied by 64044 × 256**. CPU differed from a
float64 reference by 0.0000291 relative L2; MPS differed by 1.70. This isolated
operation has no model loss, dropout or optimizer. A native 3-D explicit-gradient
form also disagreed, by 0.154, whereas its forward result and weight gradient
matched CPU for the same supplied tensors.

The host is an Apple M2 Max running Torch 2.12.1, with float32 matmul precision
`highest` and no MPS fast-math, prefer-Metal or fallback environment flags. A
[primary PyTorch report](https://github.com/pytorch/pytorch/issues/195163) describes
large-inner-dimension failures on M1/M2 hardware, consistent with this shape and
hardware. That is supporting evidence, not proof of the exact underlying kernel
cause. No workaround or library upgrade was applied. See
[trocr-operator.json](results/2026-10-03/ear-tags/trocr-operator.json), which binds
saved tensors and records strides. No claim is made that all MPS models or earlier
experiments share this failure.

### Target labels shift twice

The installed Transformers 4.57.6 implementation has the documented
[VisionEncoderDecoder loss regression](https://github.com/huggingface/transformers/issues/40111).
It right-shifts decoder inputs, then its default causal loss shifts target labels
left again. A fixed positional check gives loss **0.000136 for correct aligned
predictions versus 10.000136 for the installed default**. Explicit aligned targets
recover the correct loss exactly, and padded positions have zero gradient.
[trocr-loss.json](results/2026-10-03/ear-tags/trocr-loss.json) records the CPU proof.

## Separately frozen correctness repair

The [corrected CPU protocol](eartag_trocr_cpu_protocol.json) changes only the two
identified computational boundaries: CPU FP32 training and explicit aligned
cross-entropy after the public decoder-input preparation method. It keeps the
original weights, all 3,243 training lines, two epochs, optimizer, batch sizes,
seed/order and final-only checkpoint selection. No calibration/reserved images
or model grid are introduced.

Its 20-step CPU preflight completed in 28.51 seconds. The steady mean of 1.408
seconds per step projects about 19.1 minutes for 812 steps, within the fixed
25-minute cap. Gradients were finite, with a maximum pre-clipping norm of 188.76.
The fresh full run completed all 812 steps and 6,486 examples in **1,170.63 seconds
(19.51 minutes)**, within the cap. Every first-20 sample index, epoch, loss and
gradient norm matched the separate CPU preflight exactly. All gradients remained
finite; the largest pre-clipping norm was 321.38. The final safetensors hash is
`a8dbcad3c8f2f05586690e24f4e87cd9d34090215b807a6738bcbbcc0af4858a`.
See [training report](results/2026-10-03/ear-tags/trocr-cpu-training.json) and
[completion audit](results/2026-10-03/ear-tags/trocr-cpu-completion-audit.json).

The separate [evaluation protocol](eartag_trocr_cpu_evaluation_protocol.json)
was frozen before corrected-reader outputs existed. Its independent review
verified all 3,555 file bindings, exact final-training ordering, unchanged crops
and direct truth-manifest hash. It reuses the same greedy generation and original
baseline, with no threshold or checkpoint selection. Training was CPU FP32;
generation remained **MPS FP32**, taking 5.72 seconds for all 275 crops with peak
Metal driver allocation of 1.15 GiB. This is not an all-CPU inference result.

| Corrected CPU-trained reader | Correct lines / 157 | Wrong matched text | Missed lines | Extra predictions | Exact whole tags / 64 |
|---|---:|---:|---:|---:|---:|
| Oracle polygons | 124 | 33 | 0 | 0 | 33 |
| Original small detector | 70 | 24 | 63 | 24 | 13 |

Oracle character error is 7.19%; detected-line character error, including misses
and extra text, is 56.86%. The unchanged original-reader baseline reproduced its
earlier counts exactly. The corrected reader improves on the earlier TrOCR
adaptation and exceeds RapidOCR's 116 oracle-correct lines, but still trails
RapidOCR's 74 correct lines with the real detector. Its 13 exact whole tags versus
RapidOCR's 12 are a small development-panel difference, not evidence of reliable
automatic identity attachment. All wrong readings remain in the report.

See [corrected raw output](results/2026-10-03/ear-tags/trocr-cpu-corrected-raw.json),
[strict score](results/2026-10-03/ear-tags/trocr-cpu-corrected-score.json), and
[independent preflight](results/2026-10-03/ear-tags/trocr-cpu-evaluation-independent-preflight.json).
Both earlier results remain immutable. The two numerical repairs were applied
together, so this experiment does not quantify their separate contributions.

The unchanged literal agreement rule was also frozen for the corrected reader
before its outputs existed. It retained 64 predictions: **56 correct, 1 wrong
matched text and 7 extras**, giving 87.5% precision and 35.67% coverage of all 157
lines, with 100 missed lines and 7 exact whole tags. Agreement still does not
support automatic naming. See [agreement protocol](eartag_reader_cpu_agreement_protocol.json)
and [result](results/2026-10-03/ear-tags/reader-cpu-agreement.json).
