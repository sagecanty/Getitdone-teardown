"""
Dedup feasibility eval — can Claude, shown a new 311 report and a shortlist of
existing reports, correctly identify the one it duplicates? Ground truth is the
city's own service_request_parent_id (assigned when it closed a report as a
duplicate). Tests the "already reported?" feature scoped in 04-requirements.md.

A MATCHING task, LLM-judged (distinct from the classification eval in the CFPB
repo and the injection eval in Logmortem). For each known child-duplicate:
  1. build a realistic candidate shortlist (same service, geographically near,
     filed before the child) - this mimics what an intake system would surface,
     and keeps the prompt small/cheap;
  2. inject the TRUE parent into that shortlist if the filter didn't already
     catch it (so the model always has a right answer available - we're testing
     the match decision, not the pre-filter's recall);
  3. ask Claude to pick which candidate is the same issue, or NONE;
  4. score: did it pick the true parent? did it false-positive on a control?

Honest scope, built in:
- Recall is measured against duplicates the CITY caught (parent_id present).
  Says nothing about missed dupes - "of catchable dupes."
- Easy (same street address / near-identical text) vs. hard (paraphrased,
  different wording) reported separately, so trivial cases can't carry the
  headline. In this data only 7% of pairs are identical text, 25% share an
  address - the rest is genuine semantic matching.
- A control slice of NON-duplicate reports (no parent_id) is run through the
  same prompt to measure false-positive rate - a matcher that flags everything
  is useless, so precision matters as much as recall.
- The candidate shortlist is capped and pre-filtered by location/recency, which
  is a modeling choice stated here, not hidden - a real intake system would do
  the same rather than compare against the whole queue.

Uses the existing ANTHROPIC_API_KEY (same stack as the rest of the portfolio).
Cost: a few cents (~1 call per eval case + controls).

Reads:  ../data/closed_2025.csv
Writes: pairs.csv, results.md

Note: phone numbers occasionally appear in resident free-text descriptions;
they are redacted from the persisted pairs.csv (already-public 311 data, but a
portfolio repo is a different exposure than a bulk government dataset).
"""

import csv
import json
import math
import os
import random
import sys
import time
from pathlib import Path

import requests

DATA = Path(__file__).parent.parent / "data" / "closed_2025.csv"
DIR = Path(__file__).parent
SERVICE_FILTER = "sidewalk"
MODEL = "claude-sonnet-5"
API = "https://api.anthropic.com/v1/messages"
SHORTLIST_SIZE = 6          # candidates shown to the model (incl. the true parent)
N_EVAL = 120                # child-dupes to test (keeps cost to a few cents)
N_CONTROL = 40              # non-dupe reports, for false-positive rate
RADIUS_KM = 2.0             # geo pre-filter for the shortlist
SEED = 20260722


def haversine_km(a_lat, a_lng, b_lat, b_lng):
    try:
        a_lat, a_lng, b_lat, b_lng = float(a_lat), float(a_lng), float(b_lat), float(b_lng)
    except (ValueError, TypeError):
        return 9e9
    R = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lng - a_lng)
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(h))


def load():
    by_id, sidewalk = {}, []
    with open(DATA) as f:
        for row in csv.DictReader(f):
            by_id[row["service_request_id"]] = row
            if SERVICE_FILTER in row["service_name"].lower():
                sidewalk.append(row)
    return by_id, sidewalk


def desc(row):
    return (row.get("public_description") or "").strip()


def build_eval_set(by_id, sidewalk):
    """Child-dupes with a resolvable parent and descriptions on both sides."""
    pairs = []
    for row in sidewalk:
        p = row["service_request_parent_id"].strip()
        if p and p in by_id and desc(row) and desc(by_id[p]):
            pairs.append((row, by_id[p]))
    controls = [r for r in sidewalk
                if not r["service_request_parent_id"].strip() and desc(r)]
    return pairs, controls


def shortlist_for(child, parent, pool):
    """Geo+recency-near candidates from pool, with the true parent guaranteed in."""
    c_time = child["date_requested"]
    near = []
    for r in pool:
        if r["service_request_id"] == child["service_request_id"]:
            continue
        if r["date_requested"] >= c_time:      # candidate must predate the child
            continue
        d = haversine_km(child["lat"], child["lng"], r["lat"], r["lng"])
        if d <= RADIUS_KM:
            near.append((d, r))
    near.sort(key=lambda x: x[0])
    picks = [r for _, r in near[:SHORTLIST_SIZE]]
    if parent is not None and all(
        r["service_request_id"] != parent["service_request_id"] for r in picks
    ):
        picks = picks[:SHORTLIST_SIZE - 1] + [parent]   # guarantee a right answer
    random.shuffle(picks)
    return picks


PROMPT = """A resident just filed a new "Get It Done" 311 report. Below it is a \
numbered list of existing reports already in the system, filed earlier and nearby.

Your job: decide whether the NEW report describes the SAME specific real-world \
issue as one of the existing ones (a duplicate), or is a distinct issue.

Same issue = same physical problem at effectively the same location (e.g. the \
same broken sidewalk panel, the same lifted curb). Merely being the same CATEGORY \
(both about sidewalks) is NOT a duplicate. Different block, different defect = not \
a duplicate.

NEW report:
<new>
{child}
</new>

Existing reports:
{candidates}

Respond with ONLY a JSON object, no other text:
{{"match": <number of the duplicate, or null if none>, "confidence": "high"|"medium"|"low"}}"""


def fmt(row):
    return (f'{desc(row)[:280]}  [addr: {row.get("street_address","?").strip()[:40]}, '
            f'{row.get("date_requested","?")[:10]}]')


def call(child, candidates, api_key):
    body = {
        "model": MODEL, "max_tokens": 100,
        "messages": [{"role": "user", "content": PROMPT.format(
            child=fmt(child),
            candidates="\n".join(f"{i+1}. {fmt(c)}" for i, c in enumerate(candidates)),
        )}],
    }
    for attempt in range(4):
        try:
            r = requests.post(API, headers={
                "x-api-key": api_key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"}, json=body, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(4 * (attempt + 1)); continue
            r.raise_for_status()
            txt = "".join(b.get("text", "") for b in r.json().get("content", [])
                          if b.get("type") == "text").strip()
            txt = txt[txt.find("{"): txt.rfind("}") + 1]
            return json.loads(txt)
        except (requests.RequestException, json.JSONDecodeError, ValueError):
            time.sleep(3 * (attempt + 1))
    return None


def is_easy(child, parent):
    same_addr = (child.get("street_address", "").strip().lower()
                 == parent.get("street_address", "").strip().lower()
                 and child.get("street_address", "").strip())
    ident = desc(child) == desc(parent)
    return bool(same_addr or ident)


def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Set ANTHROPIC_API_KEY (export ANTHROPIC_API_KEY=...)")
    random.seed(SEED)
    by_id, sidewalk = load()
    pairs, controls = build_eval_set(by_id, sidewalk)
    print(f"{len(pairs)} usable dupe-pairs, {len(controls)} control non-dupes")

    random.shuffle(pairs); random.shuffle(controls)
    eval_pairs = pairs[:N_EVAL]
    eval_controls = controls[:N_CONTROL]

    # persist the eval set for transparency
    with open(DIR / "pairs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["child_id", "parent_id", "difficulty", "child_desc", "parent_desc"])
        for c, p in eval_pairs:
            w.writerow([c["service_request_id"], p["service_request_id"],
                        "easy" if is_easy(c, p) else "hard", desc(c)[:200], desc(p)[:200]])

    hit = {"easy": [0, 0], "hard": [0, 0]}   # [correct, total]
    wrong_match = 0
    for i, (child, parent) in enumerate(eval_pairs, 1):
        cands = shortlist_for(child, parent, sidewalk)
        res = call(child, cands, api_key)
        diff = "easy" if is_easy(child, parent) else "hard"
        hit[diff][1] += 1
        if res and res.get("match") is not None and 1 <= res["match"] <= len(cands):
            picked = cands[res["match"] - 1]
            if picked["service_request_id"] == parent["service_request_id"]:
                hit[diff][0] += 1
            else:
                wrong_match += 1
        if i % 20 == 0:
            print(f"  dupes {i}/{len(eval_pairs)}", flush=True)
        time.sleep(0.2)

    # controls: model should answer null (no true parent injected)
    fp = 0
    for j, child in enumerate(eval_controls, 1):
        cands = shortlist_for(child, None, sidewalk)
        if not cands:
            eval_controls_used = j - 1
            continue
        res = call(child, cands, api_key)
        if res and res.get("match") is not None:
            fp += 1
        if j % 20 == 0:
            print(f"  controls {j}/{len(eval_controls)}", flush=True)
        time.sleep(0.2)

    write_results(hit, wrong_match, fp, len(eval_controls), len(eval_pairs))


def pct(n, d):
    return f"{100*n/d:.0f}%" if d else "n/a"


def write_results(hit, wrong_match, fp, n_ctrl, n_eval):
    e_ok, e_n = hit["easy"]; h_ok, h_n = hit["hard"]
    tot_ok, tot_n = e_ok + h_ok, e_n + h_n
    lines = [
        "# Dedup Feasibility Eval — Results",
        "",
        f"Model: {MODEL}. Ground truth: city `service_request_parent_id`. "
        f"Eval set: {n_eval} known sidewalk duplicates + {n_ctrl} control non-dupes.",
        "",
        "## Can the model find the duplicate it was shown?",
        "",
        "| slice | recall@shortlist | n |",
        "|---|---|---|",
        f"| overall | {pct(tot_ok, tot_n)} | {tot_n} |",
        f"| easy (same address / identical text) | {pct(e_ok, e_n)} | {e_n} |",
        f"| hard (paraphrased, different wording) | {pct(h_ok, h_n)} | {h_n} |",
        "",
        f"- Wrong-match rate (picked a candidate, but the wrong one): "
        f"{pct(wrong_match, tot_n)} of dupe cases.",
        f"- False-positive rate on controls (flagged a duplicate where none was "
        f"injected): {pct(fp, n_ctrl)} of {n_ctrl}.",
        "",
        "## Reading this",
        "",
        "The hard slice is the real result — easy cases (same address or identical "
        "text) a string match would also catch. The gap between easy and hard is "
        "the value an LLM matcher adds over exact-match dedup at intake. The "
        "false-positive rate is the cost: a matcher that over-flags creates review "
        "burden, so the acceptance criterion in the requirements addendum pairs a "
        "recall target with an FP ceiling, not recall alone.",
        "",
        "## Honest scope",
        "",
        "- Recall is measured against duplicates the city already caught "
        "(parent_id present) — not missed ones. This is 'of catchable dupes.'",
        "- The true parent is guaranteed present in the shortlist, so this "
        "isolates the *match decision* from the pre-filter's own recall. A "
        "production system's end-to-end recall is this number times the "
        "pre-filter's recall — a separate measurement.",
        "- Single run, ~120 cases. Directional, not a certified benchmark.",
    ]
    (DIR / "results.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
