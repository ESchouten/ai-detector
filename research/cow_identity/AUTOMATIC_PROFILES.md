# Anonymous evidence accumulation

The next useful automatic step is collecting evidence without requiring a farmer
to label photographs. An observation profile is a scoped camera instance, not a
certified biological cow. A readable ear number may eventually anchor its current
trusted episode; it must not relabel every earlier photograph that reused the
same long-lived segmentation slot.

The fixed prediction-only inventory uses the completed automatic-eight startup
recording and all eight slots equally. It never reads biological annotations,
initial identity anchors, displayed names or recognition scores. Existing mask
quality, reciprocal detection, quarantine and crop-size gates produce 14,706
eligible observations across 1,870 uninterrupted quality episodes. Only 938
episodes reach three consecutive observations. This fragmentation is a reason to
preserve episode boundaries explicitly, not to assume every episode is a new cow
or automatically join every episode from one slot.

The inventory's fixed proposal collects at most once per ten seconds per
instance after three consecutive eligible samples, then retains at most sixteen
geometry-diverse candidates per instance. It selects 128 of 1,546 candidate
observations. The geometry proxy spans aspect, scale and position; it does not
prove coat diversity or identity. No encoder, image inference, cross-profile link
or transitive identity merge is performed. The exact selection and provenance are
in `anonymous_profile_inventory_protocol.json` and
`results/2026-10-03/recognition/anonymous-profile-inventory.json`.

The offline recording lacks runtime UUIDs. Its run/source/epoch/instance keys are
explicit synthetic namespaces bound to the completed source hashes. Actual
operation uses the current run ID, hashed source, capture epoch and opaque
instance UUID plus generation. The wrapper's analyzed-frame index, rather than
native decoded-frame sequence, reveals a missing eligible one-Hz observation.
Any quality gap ends the current episode. A reconnect or generation change starts
a different scoped instance. Neither operation guesses that a returning cow is
an earlier one.

`IdentityProfileStore` is the minimal persistence boundary.
It owns `identities/automatic/profiles.sqlite`, shares a JPEG between instances
observed in the same frame, and stores immutable capture/episode/geometry facts.
The image is the full analyzed-resolution frame, with context for later ear-tag
ownership checks. It may already have been resized by capture. Original BGR and
encoded JPEG hashes are distinct; decoded JPEG pixels are not claimed to match
the original frame. Numeric OCR should inspect the original live pixel callback
or a separately verified lossless crop when available.

Retention is automatic: at most sixteen recent candidates per instance, 500
instances, 256 MiB of persistent database storage and seven days. Expiry applies
on opening, saving, reading or explicit maintenance. SQLite's temporary rollback
journal may use additional space during a write. No manual review is needed to
resume collection, and this namespace cannot delete confirmed herd images or
write `catalog.json`. The store itself has no model, matcher, sampling or
geometric-diversity selector. Its FIFO retention is tested; the inventory's
geometry-diversity proposal is not yet an application policy.

`IdentityProfileCollector` connects the typed tracking evidence to that store.
Each camera owns at most eight small episode records and no retained images or
queue. It waits for three consecutive eligible analyzed samples, then saves at
most once per ten seconds per instance. Missing analysis indices split episodes;
offline/reconnect notifications invalidate the source token, and a worker reset
cannot reuse an earlier generation's evidence. A second currentness check after
JPEG encoding rejects a frame that disconnected or became stale while encoding.
Already accepted historical evidence remains scoped to its original capture; it
does not establish the camera's current state. Expected storage failures produce
a diagnostic and retry after a minute while detection continues. This includes
initial database-open failures: the single-camera collector opens storage lazily
and owns its close; a corrupt or unwritable optional database does not prevent
monitoring from starting. Partially opened SQLite connections are closed before
retry. Idle state
expires after three seconds, and explicit maintenance enforces disk retention.

The collector uses the wrapper's segmentation/reciprocal/quarantine eligibility.
It does not apply the research inventory's additional unclipped 64-pixel crop
gate or geometry-diverse reservoir. Its retained photos therefore have **not**
inherited the inventory's measured purity. Neither component assigns a biological
identity, writes a confirmed animal, reads a tag, or merges visits.

The shared store retains at most one strong immutable frame reference, sharing
its pixel digest and JPEG across animals. Raw frames above 32 MiB are skipped,
and the retained raw-frame-plus-JPEG cache is capped at 48 MiB; temporary encoder
allocations are additional. A local CPU/SSD check of twelve independent synthetic
noise frames, each stored for eight animals, took median 10.76 ms (maximum
11.95 ms) at 1280×720 and median 33.22 ms (maximum 34.66 ms) at 2560×1440.
This supports the simple synchronous ten-second cadence on this machine, not a
general disk-latency guarantee. There is no extra background writer.

Seventeen focused tests use real JPEG/SQLite operations and controlled clocks.
They cover paced eight-animal collection, a real thread-barrier disconnect during
encoding, expiry during encoding, epoch/generation isolation, initial corrupt/unwritable storage recovery, expected I/O retry,
uninterrupted collection past 200 samples, credential omission, reference-safe
eviction and actual disk limits. Reopening with tighter quotas prunes immediately
without waiting for another write. Confirmed manual herd files remain separate.

After the immutable research selection was frozen, the independent geometric
audit matched all 14,706 qualified observations against all visible annotated
animals. It found 144 unmatched observations, two mixed-animal episodes out of
1,870, and 108 episodes containing at least one unmatched observation. The 1,546
proposals include nine unmatched observations and two from a mixed episode.
All 128 geometry-selected photos match an annotated animal (sixteen per animal),
but thirteen belong to episodes that also contain an unmatched observation.
These are box-association results, not proof that each foreground mask contains
only one animal. No ground-truth label influenced collection or seeded an
automatic biological identity. See [the fixed audit](ANONYMOUS_PROFILE_AUDIT.md).

Two long-lived slots associate with more than one animal at least once. A later
ear-number reading therefore cannot label every historical image in that slot.
Re-entry, cross-camera links, safe memory retirement and exact tag ownership
remain separate validation tasks. Zero implemented cross-profile merges is not
evidence that tracking never switches.
