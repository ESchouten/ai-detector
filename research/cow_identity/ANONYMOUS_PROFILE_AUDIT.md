# Anonymous profile purity audit

This audit follows the already frozen, prediction-only photo selection. It does
not change that selection, tune a threshold, read a new video segment, or assign
any biological identity. The exposed 0–2999 second recording is development
evidence. The 3000+ second reserve remains closed.

`anonymous_profile_audit_protocol.json` binds the selection, complete tracking
recording, numeric publisher annotations and scorer before execution. Every
same-frame tracked box participates in the existing maximum-cardinality,
one-to-one IoU ≥ 0.5 association before selecting qualified observations. Thus a
qualified box cannot take the annotation of a better competing box merely
because that competitor failed a quality gate. Unmatched boxes remain errors.
The original publisher pickle is not deserialized.

| Evidence | Count |
| --- | ---: |
| Qualified observations | 14,706 |
| Unmatched qualified observations | 144 |
| Uninterrupted quality episodes | 1,870 |
| Episodes with at least three observations | 938 |
| Entire episode matched to one animal with no misses | 1,761 |
| Episodes containing unmatched observations | 108 |
| Episodes containing more than one matched animal | 2 |
| Observations in those two mixed episodes | 12 |
| Proposed photos matched / unmatched | 1,537 / 9 |
| Proposals from a mixed episode | 2 |
| Proposals from an episode with unmatched observations | 130 |
| Final retained photos matched / unmatched | 128 / 0 |
| Retained photos from an episode with unmatched observations | 13 |

The final set has sixteen geometrically matched photos per animal and none from
the two mixed episodes. This is useful evidence for bounded collection, not a
claim of perfect photo purity or automatic recognition. Box overlap does not
certify every foreground pixel. In addition, the final sixteen-photo reservoir
is chosen over a complete 50-minute history; it cannot retroactively make an
ear-number assignment at an earlier moment safe.

Two of the eight long-lived segmentation slots contain another animal at least
once. Slot 7 has mixed episodes at 428–433 and 444–449 seconds, associated with
animals 1 and 8. The six fixed frames at 428, 430, 433, 444, 446 and 449 seconds
were subsequently inspected with prediction and publisher boxes. The predicted
box spans adjacent calves at the feed rail. Therefore this is not simply a
missing name or a number-reader problem: a broad foreground region can contain
more than one possible owner. This limited image review does not replace the
publisher annotations or certify individual mask pixels.

The implication for automatic enrollment is explicit: an ear number must be
associated with one animal in the same pixels, with ambiguity rejected. Neither
a common slot nor an uninterrupted quality episode alone certifies ownership.
The number may anchor supported observations, but cannot relabel every earlier
photo in that slot. Appearance-based cross-episode links still need their own
evaluation. The audit's dominant-animal fractions are diagnostic upper bounds,
not model predictions or automatic names.

The complete counts and per-episode evidence are in
`results/2026-10-03/recognition/anonymous-profile-audit.json`. Three small tests
verify that unmatched evidence remains an error, an apparently clean retained
photo cannot hide a mixed episode, and shared slot IDs do not erase episode
boundaries. No inference or new model download was needed for this audit.
