# Dedup Feasibility Eval — Results

Model: claude-sonnet-5. Ground truth: city `service_request_parent_id`. Eval set: 120 known sidewalk duplicates + 40 control non-dupes.

## Can the model find the duplicate it was shown?

| slice | recall@shortlist | n |
|---|---|---|
| overall | 35% | 120 |
| easy (same address / identical text) | 62% | 39 |
| hard (paraphrased, different wording) | 22% | 81 |

- Wrong-match rate (picked a candidate, but the wrong one): 18% of dupe cases.
- False-positive rate on controls (flagged a duplicate where none was injected): 12% of 40.

## Reading this

The hard slice is the real result — easy cases (same address or identical text) a string match would also catch. The gap between easy and hard is the value an LLM matcher adds over exact-match dedup at intake. The false-positive rate is the cost: a matcher that over-flags creates review burden, so the acceptance criterion in the requirements addendum pairs a recall target with an FP ceiling, not recall alone.

## Honest scope

- Recall is measured against duplicates the city already caught (parent_id present) — not missed ones. This is 'of catchable dupes.'
- The true parent is guaranteed present in the shortlist, so this isolates the *match decision* from the pre-filter's own recall. A production system's end-to-end recall is this number times the pre-filter's recall — a separate measurement.
- Single run, ~120 cases. Directional, not a certified benchmark.