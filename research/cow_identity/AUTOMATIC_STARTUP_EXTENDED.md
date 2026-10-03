# Automatic startup through the exposed 50-minute recording

The single-frame containment initializer selected eight anonymous masks from all
raw first-frame proposals. The fixed long control reused those exact masks,
Cutie joint readout at 2 Hz, raw YOLO at 1 Hz, and the existing quality, reciprocal
IoU and quarantine gates. No new births, retirement, thresholds or box geometry
were introduced. Six initial geometry anchors supplied names **for scoring
only**; the two unknown cows stayed in every denominator. This does not test
automatic biological identification or ear-number reading.

The [pre-input protocol](detection_startup_extended_protocol.json) is SHA
`db708d013ee6419a6fb948bb1870df5dc213340174f12bf33af1cca29d46e8aa`.
The [completed report](results/2026-10-03/detection/startup-extended.json) is SHA
`ba4d56f21963692609d12bc228472d30e2cc99c972b2c14f7ff9bd86ed755a4e`.
The [independent recount](results/2026-10-03/detection/startup-extended-independent-audit.json)
reproduces all counts without calling the main scorer. All five windows were
already exposed during development; no 3000+ frames were opened.

| Window start | Correct / visible known | Named-unmatched | Coverage | Conservative precision | Gates |
| --- | --- | --- | --- | --- | --- |
|330|1243/1800|10|69.06%|99.202%|Pass|
|930|1295/1795|7|72.14%|99.462%|Pass|
|1230|1224/1799|6|68.04%|99.512%|Pass|
|1800|1119/1799|7|62.20%|99.378%|Pass|
|2700|1302/1781|27|73.10%|97.968%|**Fail**|

Every window has zero matched wrong-known and unknown-named predictions. All
57 named-unmatched predictions remain errors. The pooled 6183/8974 correct names
and 99.0865% precision do not override the final-window failure. Automatic
initialization therefore did not resolve the late precision limitation seen
with the earlier six-seed/birth control. The experiment is not a promotion or
field-readiness result.

Before any truth was scored, the first 241 source records and 121 integer mask
records matched the short startup run exactly: pixels, model settings, masks,
quality, boxes, detector proposals, reciprocal pairs and quarantine events.
Only the predeclared scoring names differed. A failed prefix would have returned
`FAILED_PREFIX_PARITY` with no scores; the old unexecuted preflight freeze was
preserved. Half-second masks were not stored by the original short run, so no
half-second mask parity is claimed.

The actual MPS run completed 5,999 inputs in 967.69 seconds. Mean timed step was
0.157 seconds, p95 was 0.223 seconds and p99 was 0.238 seconds. Observed driver memory
peaked at 5.91 GB after reclamation and 6.77 GB before reclamation; RSS peaked at
1.23 GB. SAM initialization was reused from its separately verified CPU proof;
these timings are the continuous tracker/detector loop, not fresh camera setup.
They also do not establish behavior under real capture jitter, reconnects or
new animal arrivals.
