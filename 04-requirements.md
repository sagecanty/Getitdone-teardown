# Requirements — Infrastructure Capital-Assessment Track

**Document type:** Lightweight BRD / user stories with acceptance criteria
**Source recommendation:** `03-decision-memo.md`
**Audience:** Get It Done product team + 311 program manager (simulated)

## 1. Business Objective

Separate the four structural infrastructure categories (sidewalk repair,
pavement maintenance, ROW maintenance, street light maintenance) from the
standard 311 flow into a capital-assessment track with honest status language
and district-level capacity targets. Primary goal: eliminate the gap between the
"open" label and the multi-year reality that currently misleads residents and
generates duplicate re-reports. First milestone: sidewalk repair in Districts 2
and 7, where the delay is largest (506 and 666-day medians vs. a 37-day citywide
median).

## 2. Current State (As-Is)

1. All service requests share one intake flow and one status vocabulary
   (Open / Closed / Referred).
2. An infrastructure request queued for multi-year capital work is labeled
   "Open" — identical to a same-day pothole or graffiti report.
3. Residents receive no signal that the work is capital-scale; many re-file the
   same issue months later, reasonably assuming it was dropped.
4. Backlog reporting mixes capital work and operational work, so no metric
   distinguishes "slow because unfunded" from "slow because under-triaged."

## 3. Future State (To-Be)

1. At intake, reports in the four structural categories are classified onto the
   **capital-assessment track**.
2. Their status vocabulary changes from "Open" to honest states:
   **Assessed → Queued for capital planning → Scheduled → Complete**.
3. Residents see the realistic status and an expected-timeline band at
   submission and on any later status check.
4. The schedulable share of the work carries **district capacity targets**;
   D2 and D7 sidewalk repair are the first tracked.
5. Reporting separates capital-track volume/age from operational backlog.

## 4. User Stories

**US-1 — Resident gets an honest expectation at submission**
As a resident reporting a sidewalk or similar infrastructure issue, I want to
know it is capital-scale work with a realistic timeline, so that I am not misled
by an "open" label into thinking action is imminent.

*Acceptance criteria:*
- Given a report in a structural infrastructure category, when it is submitted,
  then the resident sees a capital-assessment status and an expected-timeline
  band rather than a generic "Open."
- Given a non-infrastructure report, when submitted, then the flow and status are
  unchanged.

**US-2 — Resident checking status sees reality, not a placeholder**
As a resident who filed an infrastructure report, I want a status that reflects
where the work actually is, so that I do not re-file the same issue.

*Acceptance criteria:*
- Given an open capital-track report, when the resident checks status, then it
  shows the current honest state (Assessed / Queued / Scheduled), not "Open."
- Given a report already on the capital track, when the same resident attempts a
  duplicate, then existing candidate reports are surfaced as a suggestion for the
  resident to confirm — geospatial-first, assistive not automatic (see §6 for the
  feasibility test that set this design).

**US-3 — Program manager holds district capacity targets**
As the program manager, I want district-level capacity targets for schedulable
infrastructure work, so that the reclassification carries a service commitment
and is not just a relabel.

*Acceptance criteria:*
- Given a reporting period, when the capacity report is generated, then it shows
  sidewalk-repair median resolution by district against target, with D2 and D7
  flagged.
- Given the report, when a district's gap widens, then it is flagged for review
  so the fix is not silently shifting disparity elsewhere.

**US-4 — Hazard escalation survives the honest-but-slow default**
As a triage agent, I want a hazard-flag path on the capital track, so that a
genuinely dangerous defect is not buried by a long default timeline.

*Acceptance criteria:*
- Given a capital-track report flagged as a safety hazard, when it enters the
  queue, then it routes to expedited review outside the standard capital timeline.
- Given an escalation, when it resolves, then it is logged separately so hazard
  volume is measurable.

## 5. Edge Cases and Open Questions

- **Category ambiguity:** some potholes are O&M, some are capital repaving.
  Classification rules need a tie-breaker (severity/scope threshold), TBD with
  the streets team.
- **Existing backlog:** do the 14,786 already-open sidewalk reports get
  reclassified retroactively, or does the track apply only to new intake?
  Proposed: new intake first (phase 1), retroactive relabel as phase 2.
- **Status-language approval:** honest states are politically sensitive; comms
  and council sign-off on the exact wording is a dependency, not an assumption.

## 6. Feasibility test: can duplicate detection (US-2) actually be built?

US-2's second acceptance criterion — "surface the existing report when a
resident attempts a duplicate" — assumes duplicate detection works. Before
committing to it, I ran a feasibility eval against the city's own duplicate
labels (`05-dedup-eval/`, ground truth = `service_request_parent_id`). The
result **changed the requirement**, which is what a feasibility test is for.

**What the eval found** (120 known sidewalk duplicates, LLM matcher shown a
geo-filtered shortlist with the true parent guaranteed present):

| slice | recall | reading |
|---|---|---|
| easy (same address / identical text) | 62% | a string/geo match would also catch these |
| **hard (paraphrased, different wording)** | **22%** | the cases that need real matching — and the real result |
| false-positive on non-duplicates | 12% | the review-burden cost of over-flagging |

**Why it's low — and why that's the finding, not a model failure.** Reading the
misses, the hard pairs are genuinely underdetermined by text: "Sidewalk and
even/hole" vs. "Cracked and bulging sidewalk"; "Lifted City sidewalk repair
request" vs. "uneven lifting making it difficult for a mobility scooter." A
human reviewer couldn't confidently call these duplicates from the descriptions
either — they're the same *generic complaint type* that could be one panel or
two a block apart. The city merged them using a field inspector's location
knowledge the text doesn't carry. Performance tracks whether the **data**
contains the answer (62% when address/text does) not whether the model is clever
(22% when it doesn't). **Sidewalk dedup is a location problem, not a text
problem.**

**What this changes in the requirement:**

- **US-2 duplicate detection is re-scoped from text-similarity to
  geospatial-first.** Cluster candidate duplicates by lat/lng + service type;
  use an LLM only as a secondary tiebreaker *within a tight radius*, where the
  candidate set is small and the 12% false-positive cost is bounded. Do not
  build text-similarity dedup as the primary mechanism — the eval shows text is
  the wrong signal.
- **Duplicate detection is assistive, never autonomous.** At 22% hard-recall and
  12% false-positives, auto-merging would both miss most real duplicates and
  wrongly merge distinct reports (merging two different residents' hazards is a
  worse failure than a missed merge). The feature surfaces *candidates as a
  suggestion* to a human — at intake to the resident ("is this your issue?") and
  in triage to an agent — who confirms. The human stays in the loop *because of*
  these numbers, not as a default.
- **Revised acceptance criterion for US-2 dedup:** given a new structural-infra
  report, when a prior report exists within [radius] filed within [window] for
  the same service type, then up to N candidates are surfaced to the resident as
  a suggestion; the resident's confirm/dismiss is logged to measure real-world
  precision over time. No automatic merge.

*Scope of the test: measures recall against duplicates the city already caught,
single run of ~120 cases, true parent guaranteed in the shortlist (isolating the
match decision from pre-filter recall). Directional, not a certified benchmark —
enough to redirect the design, not to set a final threshold. Full method and the
honest caveats are in [`05-dedup-eval/results.md`](05-dedup-eval/results.md).*

## 7. Out of Scope

- **Securing capital budget** — a council/finance matter this process change
  makes visible but cannot solve.
- **The consumable categories** (illegal dumping, graffiti, missed collection),
  which already resolve same-day and need no change.
- **Cross-channel duplicate detection at submission** — mobile intake is ~26%
  duplicate-or-referred, a real secondary finding. The *sidewalk* dupe case is
  addressed in §6; generalizing dedup across all channels and categories is a
  separate initiative.

## 8. Success Metrics

| Metric | Definition | Baseline (2025) | Target |
|---|---|---|---|
| D2 sidewalk median | median resolution days, sidewalk repair, District 2 | 506 days | narrow gap to citywide |
| D7 sidewalk median | median resolution days, sidewalk repair, District 7 | 666 days | narrow gap to citywide |
| Infra duplicate re-reports | capital-track reports with a non-null parent id | current baseline | reduced (honesty → less re-filing) |
| Capital vs O&M separation | reporting distinguishes the two backlogs | none today | in place |

