# Policy Gap Analysis: Help Center vs Official v2.1

**Date:** 2026-10-13
**Author:** RydeResolve System Update
**Purpose:** Compare the previously-sourced Help Center policy against the official "Ryde Dispute Resolution Policy v2.1" document, identify gaps, and document what was filled in.

---

## 1. Executive Summary

The system's policy knowledge base was originally built from **10 publicly-accessible Help Center articles** and **1 user-provided sample dataset** (DISP-002). These covered basic fare structure, cancellation/no-show rules, waiting fees, route policy, waiver processes, and service scope — but lacked critical detail on route deviation refund matrices, surge pricing, property damage, safety incidents, and ruling thresholds.

The official **Ryde Dispute Resolution Policy v2.1** (effective 2026-01-01) is a structured 7-section internal document that introduces **23 new policy clauses** across 6 previously-uncovered topics, **3 official precedent rulings**, and **3 direct conflicts** with Help Center values that have now been resolved in favor of v2.1.

| Metric | Before | After | Delta |
|---|---|---|---|
| Sources | 11 | 12 | +1 (POLICY-V21) |
| Policy clauses | 34 | 57 | +23 |
| Precedents | 5 | 8 | +3 |
| Conflicts | 5 | 8 | +3 (all resolved) |
| Active policy IDs in `knowledge.py:seed()` | 5 | 30 | +25 |

---

## 2. What the System Had Before (Help Center Sources)

The following 11 sources were the basis of the original policy knowledge base:

| Source ID | Title | Audience | Key Parameters |
|---|---|---|---|
| HC-FARE | Understanding the Fare Structure | rider | Distance + duration pricing |
| HC-ROUTE | Suggested route by rider | driver | Fixed pickup/dropoff fare; driver may choose fastest GPS route |
| HC-RIDER | Cancellation and Waiting Fee | rider | $6.61 cancellation; 3-min wait; 3-min grace |
| HC-DRIVER | Cancellation and Waiting Time Policy | driver | $4.50 driver receipt; 3-min wait; 3-min grace |
| HC-CANCEL-HOW | How Does the Cancellation Fee Work? | driver | 3-min wait → $4.50 labeled "cancellation" |
| HC-CONTACT | Unable to contact rider | driver | Attempt in-app messaging **or** a call |
| HC-APPEAL | I wish to make an appeal | driver | 3-min wait eligibility; auto-credit |
| HC-WAIT-WAIVER | Waiting Fee Waiver Request | rider | 30-day window; $5 voucher; no cash |
| HC-CANCEL-WAIVER | Cancellation Fee Waiver Request | rider | 30-day window; $6.61 voucher; linked to 2026-02-17 fee change |
| HC-SCOPE | Does Cancellation Policy apply to all services? | rider | All services except RydeTAXI |
| SAMPLE-DISP-002 | DISP-002 No-Show Sample | both | 5-min free wait; 8-min no-show threshold; $5 fee to driver |

### Known Issues with Help Center Sources

1. **No official effective dates** — all Help Center articles lack `effective_from` fields; they reflect whatever was published on the website at retrieval time.
2. **Inconsistent values** — the rider article says $6.61, the sample says $5.00, and the driver article says $4.50. These were treated as separate versions (conflicts C001-C002).
3. **Vague contact obligation** — the driver article says "attempt in-app messaging **or** a call", which is an OR condition. The official v2.1 requires AND (both).
4. **No coverage** of surge pricing, property damage, safety incidents, or ruling thresholds.

---

## 3. What the Official v2.1 Policy Contains

The official document has 7 sections plus 2 appendices:

| Section | Title | Clauses Added |
|---|---|---|
| 1 | Route Deviation Policy | 4 (principle, notification, refund matrix, evidence) |
| 2 | No-Show & Cancellation Policy | 5 (5-min wait, $5 fee, AND contact obligation, driver no-show, repeat flagging) |
| 3 | Fare & Surge Pricing Policy | 4 (quote binding, surge notification, refund, exempt components) |
| 4 | Property Damage Policy | 4 (claim rights, evidence, fee structure, dispute handling) |
| 5 | Safety Incident Policy | 3 (auto-escalation, AI limits, interim measures) |
| 6 | Ruling Thresholds | 3 (monetary, category, confidence calibration) |
| 7 | Precedent Rulings | 3 official precedents added to `precedent_seed.json` |
| App A | Glossary | (reference only, not coded as clauses) |
| App B | Revision History | v1.0 → v2.0 → v2.1 changelog |

**Total: 23 new policy clauses + 3 new precedents.**

---

## 4. Gap Analysis: What Was Missing

### 4.1 Route Deviation (Section 1) — 4 New Clauses

The Help Center only had two route-related clauses: "driver may choose fastest GPS route" and "fare is fixed by pickup/destination." The official v2.1 adds:

| Policy ID | What It Covers | Why It Was Missing |
|---|---|---|
| `V21-ROUTE-PRINCIPLE` | Reroute permitted for traffic, but rider must be informed | HC said driver can reroute; never said rider must be notified |
| `V21-ROUTE-NOTIFY` | MUST inform via in-app chat or verbal (call recording) before or at deviation; brief reason required | No notification requirement existed at all |
| `V21-ROUTE-REFUND-MATRIX` | 5-scenario refund matrix based on rider-informed flag and >1km tolerance | No refund logic existed for route disputes |
| `V21-ROUTE-EVIDENCE` | Traffic verified via historical traffic API; deviation = actual - recommended distance; acknowledgment via chat/call | No evidence verification methodology existed |

### 4.2 No-Show (Section 2) — 5 New Clauses

The Help Center had no-show clauses but with different values. V2.1 introduces:

| Policy ID | What It Covers | Previous Value (HC) | V2.1 Value |
|---|---|---|---|
| `V21-NOSHOW-WAIT` | Free wait time | 3 min | **5 min** |
| `V21-NOSHOW-FEE` | Cancellation fee | $6.61 | **$5.00** |
| `V21-NOSHOW-CONTACT` | Contact obligation | "messaging **or** a call" | **1 message AND 1 call** (both required) |
| `V21-DRIVER-NOSHOW` | Driver fails to arrive | Not covered | Rider cancels free; $5 goodwill if no contact |
| `V21-REPEAT-NOSHOW` | Repeat offender flagging | Not covered | 3+ in 30 days → flag, upfront payment, suspension |

### 4.3 Surge Pricing (Section 3) — 4 New Clauses

**Entirely new topic.** No Help Center article covered surge pricing.

| Policy ID | What It Covers |
|---|---|
| `V21-SURGE-QUOTE` | Upfront quote is binding at quote-time surge multiplier |
| `V21-SURGE-NOTIFY` | Must notify rider if surge increases; include new multiplier, revised fare, cancel option |
| `V21-SURGE-REFUND` | Full refund of surge differential if not notified |
| `V21-SURGE-EXEMPT` | Booking fee is surge-exempt; base/distance/time are subject to surge |

### 4.4 Property Damage (Section 4) — 4 New Clauses

**Entirely new topic.** No Help Center article covered property damage claims.

| Policy ID | What It Covers |
|---|---|
| `V21-DAMAGE-CLAIM` | Driver claim rights for cleaning/repair from rider-caused damage |
| `V21-DAMAGE-EVIDENCE` | Photo within 24h, in-app camera only, GPS+timestamp trip linkage |
| `V21-DAMAGE-FEES` | Cleaning ≤$50 (photo only); repair = cost (certified quote within 7 days) |
| `V21-DAMAGE-DISPUTE` | Rider dispute → human review; insufficient evidence = rejected |

### 4.5 Safety Incidents (Section 5) — 3 New Clauses

**Entirely new topic.** No Help Center article covered safety escalation.

| Policy ID | What It Covers |
|---|---|
| `V21-SAFETY-ESCALATE` | Auto-escalation for reckless driving, harassment, assault, accidents, feeling unsafe |
| `V21-SAFETY-AI-LIMITS` | AI can gather/summarize/prepare; CANNOT rule on safety; MUST flag safety keywords |
| `V21-SAFETY-INTERIM` | Interim account suspension pending review; lifted if no violation |

### 4.6 Ruling Thresholds (Section 6) — 3 New Clauses

**Entirely new topic.** The system had hardcoded `RESOLVED_CONFIDENCE=0.85` but no structured threshold policy.

| Policy ID | What It Covers |
|---|---|
| `V21-THRESHOLD-MONETARY` | <$10 AI final; $10-$50 AI if 80%+ confidence; >$50 always human |
| `V21-THRESHOLD-CATEGORY` | Per-category paths (safety=always human, no-show=AI final, etc.) |
| `V21-THRESHOLD-FRAUD` | Fraud flag ≥1 → 95% confidence required regardless of value |

---

## 5. Direct Value Conflicts Resolved

Three Help Center values directly conflict with v2.1. All are now marked `RESOLVED_V21_PREVAILS` in `policy_seed.json`:

| Conflict ID | Topic | Help Center Value | V2.1 Value | Resolution |
|---|---|---|---|---|
| **C006** | Cancellation fee amount | $6.61 | **$5.00** | V2.1 prevails (effective 2026-01-01) |
| **C007** | Free wait time | 3 minutes | **5 minutes** | V2.1 prevails |
| **C008** | Contact obligation | "messaging **or** a call" (OR) | **1 message AND 1 call** (AND) | V2.1 is stricter |

### Impact on `engines.py`

The deterministic liability engine (`simulation_liability()`) reads policy parameters from bound clauses. With V21 clauses now active:
- The `threshold` parameter is read as **5 minutes** (from `V21-NOSHOW-WAIT`) instead of 3 minutes.
- The `fee` parameter is read as **$5.00** (from `V21-NOSHOW-FEE`) instead of $6.61.
- The `both_required: true` flag in `V21-NOSHOW-CONTACT` enables the engine to void fees when only one contact channel was used.

---

## 6. Precedent Additions

Three official precedents from Section 7 of the v2.1 document were added to `precedent_seed.json`:

| Case ID | Date | Type | Outcome | Refund | Key Fact |
|---|---|---|---|---|---|
| DISP-2026-0089 | 2026-02-12 | Route deviation | refund | $3.20 | Rerouted for traffic, rider not informed, deviation 1.8km |
| DISP-2026-0142 | 2026-04-03 | Surge pricing | refund | $3.20 | Surge 1.0x→1.4x, rider not notified, $3.20 differential |
| DISP-2026-0211 | 2026-05-18 | No-show | refund | $5.00 | Driver waited 6 min but sent 0 messages and 0 calls; fee voided |

These precedents include extended `normalized_fact_features` with new fields: `rider_informed`, `deviation_km`, `traffic_justified`, `surge_increased`, `contact_messages`, `contact_calls`, `both_contact_obligations_met`. The `knowledge.py:retrieve()` function uses these for structured precedent matching.

---

## 7. Impact on Benchmark Data

The 100-case benchmark dataset was regenerated to align with v2.1:

| Parameter | Before (HC-based) | After (V21-based) |
|---|---|---|
| No-show cancellation fee | $6.61 | $5.00 |
| Free wait threshold | 3 min | 5 min |
| Contact obligation | OR (message or call) | AND (both required) |
| No-show upheld wait times | 4-10 min | 6-12 min |
| Total refund amount (100 cases) | $237.70 | $205.50 |
| Cases referencing v2.1 sections | 0 | 8 |
| `policy_binding` label | `public_hc_snapshot` | `official_v21` |

### Specific Scenario Changes

- **BM-NS-016 to BM-NS-025** (simple refund cases): Refund amount changed from $6.61 to $5.00
- **BM-NS-018, 021, 024**: Changed from "no contact attempts" to "messages but no calls" — testing the v2.1 AND requirement specifically
- **BM-NS-026, 030, 034**: Complex uphold cases now reference v2.1 Section 6.3 fraud confidence threshold (95%)
- **BM-NS-046, 049**: Complex human-review cases now reference v2.1 Section 5 safety escalation

---

## 8. Files Modified

| File | Change |
|---|---|
| `backend/data/policy_seed.json` | +1 source (POLICY-V21), +23 clauses, +3 conflicts (C006-C008) |
| `backend/data/precedent_seed.json` | +3 official v21 precedents with extended fact features |
| `backend/app/knowledge.py` | `seed()` now includes 30 policy IDs in `active_ids` (was 5); category mapping extended for new topics |
| `backend/app/simulation.py` | `find()` extended to load BM-* benchmark templates from JSON |
| `scripts/generate_benchmark.py` | Constants updated ($5.00 fee, 5-min wait); `no_show_scenarios()` rewritten; `policy_ids` include V21 IDs; `policy_binding` = `official_v21` |
| `scripts/run_benchmark.py` | `CANCEL_FEE = 5.00` updated to match v2.1 |
| `docs/benchmark-expected-conclusions.md` | Regenerated with v2.1 references and $5.00 amounts |
| `docs/benchmark-templates.json` | Regenerated (100 entries, 2,306 evidence records) |

---

## 9. Remaining Open Items

The following conflicts from the Help Center era remain unresolved (pre-v2.1, not addressed by the official policy):

| Conflict ID | Description | Status |
|---|---|---|
| C001 | Sample uses 8-min no-show threshold; HC uses 3-min | REVIEW_REQUIRED — v2.1 resolves this to 5 min, but the sample's 8-min value is still in the DB as a separate version |
| C003 | Driver articles label no-show fee differently (waiting vs cancellation) | REVIEW_REQUIRED — cosmetic labeling issue |
| C004 | Driver article says "all services"; rider article excludes RydeTAXI | REVIEW_REQUIRED — v2.1 does not address service scope |
| C005 | Distance/duration vs fixed fare pricing context | REVIEW_REQUIRED — requires service-level context to resolve |

### Future Recommendations

1. **Deprecate Help Center fee values** — Now that v2.1 is the authoritative source, the $6.61 and 3-min values in HC clauses should be marked as superseded in their `parameters` to prevent agents from accidentally binding to them.
2. **Implement `V21-THRESHOLD-MONETARY` in the workflow** — The LangGraph StateGraph currently uses a flat `RESOLVED_CONFIDENCE=0.85`; the v2.1 policy specifies tiered thresholds (<$10 any, $10-$50 at 80%, >$50 always human). This requires updating the graph's conditional edges.
3. **Implement `V21-SAFETY-ESCALATE` keyword detection** — The system should scan dispute text for safety keywords and auto-escalate, overriding the filer's selected dispute type.
4. **Implement `V21-SURGE-*` handling** — The `engines.py:facts()` function does not yet extract surge-related fields (upfront_quote, actual_fare, surge_multiplier). This is needed before the system can handle surge disputes.
5. **Implement `V21-DAMAGE-*` handling** — Similar gap for property damage evidence extraction (photo timestamps, in-app camera verification, trip linkage).

---

## 10. Conclusion

The gap analysis identified **23 missing policy clauses** across 6 topics and **3 direct value conflicts** between Help Center articles and the official v2.1 policy. All gaps have been filled in `policy_seed.json`, `precedent_seed.json`, and `knowledge.py`. The benchmark dataset has been regenerated with v2.1-aligned values.

The system's policy knowledge base now covers all 7 sections of the official Ryde Dispute Resolution Policy v2.1. Remaining work is in the workflow layer (LangGraph thresholds, safety keyword detection, surge/damage evidence extraction) rather than the knowledge base.
