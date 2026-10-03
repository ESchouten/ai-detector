# Joint live-object readout: a bounded inference hypothesis

Status: source-level rationale, not an accuracy result. The parent experiment owns the isolated patch and its freeze. No weight training, threshold selection or new source frames were used for this review.

Cutie is designed to process objects independently as a batch, with shared image features and limited interactions through other-object masks and segmentation aggregation. Appendix G.1 also reports that the authors did not obtain positive results from adding further interaction inside the object transformer. That cautions against inventing a new cross-object attention architecture here. [Cutie paper, Appendix G.1](https://arxiv.org/html/2310.12982v2#A7.SS1)

The proposed change retains the existing network. It changes which live objects participate together in its existing fusion and attention-mask construction. It should be described as a research inference modification, **not an established upstream bug**, a new trained architecture or a demonstrated improvement.

## What the pinned implementation does

Reviewed upstream revision: `ec5cdd4cf16f75c73ad785a2f96fb97dbad4125a`, also available in the local read-only checkout `/tmp/cow-identity-cutie`.

- Pixel keys and values are grouped by insertion time. Objects added in the same frame share a memory bucket; later arrivals may have different memory lengths and affinities. Those separate affinity computations are necessary and can stay separate. [`KeyValueMemoryStore`](https://github.com/hkchengrex/Cutie/blob/ec5cdd4cf16f75c73ad785a2f96fb97dbad4125a/cutie/inference/kv_memory_store.py)
- `MemoryManager.read` currently performs pixel readout, `pixel_fusion` and `readout_query` inside each bucket and optional object chunk. The returned dictionary reunites the per-object results afterward. [`MemoryManager.read`](https://github.com/hkchengrex/Cutie/blob/ec5cdd4cf16f75c73ad785a2f96fb97dbad4125a/cutie/inference/memory_manager.py#L111)
- `pixel_fusion` computes `last_others` from the mask channels supplied to that call. With bucket-local inputs, masks belonging to another bucket do not enter this sum. [`CUTIE.pixel_fusion`](https://github.com/hkchengrex/Cutie/blob/ec5cdd4cf16f75c73ad785a2f96fb97dbad4125a/cutie/model/cutie.py#L142)
- The transformer itself flattens batch and object dimensions, so putting more objects in the same call does not make their learned queries attend directly to one another. However, `_get_aux_mask` aggregates all supplied object probabilities before determining per-pixel foreground winners. Bucket-local invocation therefore restricts this existing competition to that bucket. [`ObjectTransformer`](https://github.com/hkchengrex/Cutie/blob/ec5cdd4cf16f75c73ad785a2f96fb97dbad4125a/cutie/model/transformer/object_transformer.py#L110)

## Why this is worth one comparison

Our automatic-arrival control can create several buckets in one crowded scene. Keeping the affinity/readout stage per bucket, then collecting its results in the canonical live-object order for one fusion/transformer call, would make existing non-target context and foreground competition independent of insertion time. This is a causal hypothesis for separating newcomers from old tracks; it is not evidence that the current failures were caused by bucketing.

The change may also reduce repeated launch overhead. It does not eliminate the per-object transformer computation or each bucket's affinity work, so “three calls become one” must not be advertised as a threefold speedup. A single larger live-object batch can increase peak memory relative to chunking. Resource measurements belong in the same-process experiment.

## What could go wrong

A poor new mask could suppress a correct older object through the expanded competition. Strong exclusion can fragment partly occluded animals. Different insertion histories remain legitimate distinct memories; merging their keys or inventing older values for a newcomer would change a second mechanism and should be avoided. Object IDs, temporary channel indices, retirement, sensory state and object summaries must retain their exact mapping.

The useful control keeps all existing detector proposals, birth rules, seeds, weights, memory limits and naming gates fixed. Before any birth, a one-bucket sequence should reproduce the baseline. After births, compare all original strict outcomes and runtime/resource totals, including anonymous animals and unmatched named masks. Preserve failures and use only already exposed footage. A successful exposed comparison would justify a later frozen validation, not a claim that cross-day cow recognition has been solved.
