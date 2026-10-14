# RydeResolve Benchmark — Expected Conclusions (100 Cases)

**Purpose:** Developer review of expected outcomes for accuracy/recall measurement.
**Important:** These conclusions are NOT stored in the database. The LLM agents
must independently judge each case from the raw evidence records.

**Policy basis:** Official Ryde Dispute Resolution Policy v2.1 (effective 2026-01-01)
**Dataset structure:** DISP-001 (route deviation) + DISP-002 (no-show) samples

| Policy | Key Rule |
|---|---|
| Cancellation fee | $5.00 — no-show after 5 min free wait (v2.1 Section 2.2) |
| Waiting fee | $5.00 — rider boards after 5 min wait, trip continues |
| Free wait | 5 minutes at pickup (v2.1 Section 2.1) |
| Advanced trip | Cancel >15 min before scheduled = no charge; within 15 min = $5.00 |
| Fixed fare | Quoted fare = charged fare (except RydeTAXI); ERP/tolls may be additional |
| Route principle | Driver may reroute for traffic; rider MUST be informed (v2.1 Section 1.1) |
| Route notification | Driver MUST inform rider before/at deviation; 1km tolerance (v2.1 Section 1.2-1.3) |
| Route refund matrix | Informed+agrees=none; not informed+>1km=partial; not informed+≤1km=none; no justification+>1km=full (v2.1 Section 1.3) |
| Route evidence | Traffic verified via historical API; deviation = actual − recommended distance (v2.1 Section 1.4) |
| Driver contact | MUST attempt 1 in-app message AND 1 phone call before no-show cancel (v2.1 Section 2.3) |

---

## Summary Statistics

### No-Show Disputes (25 cases)

| Metric | Value |
|---|---|
| Charge upheld | 9 |
| Refund required | 11 |
| Human review | 5 |
| Simple scenarios | 9 |
| Complex scenarios | 16 |
| Total refund amount | $55.00 |

### Route Deviation Disputes (25 cases)

| Metric | Value |
|---|---|
| Charge upheld | 14 |
| Refund required | 8 |
| Human review | 3 |
| Simple scenarios | 12 |
| Complex scenarios | 13 |
| Total refund amount | $17.12 |

### All Cases (100)

| Metric | Value |
|---|---|
| Charge upheld | 23 |
| Refund required | 19 |
| Human review | 8 |
| Total refund amount | $72.12 |

---

## No-Show Charge Disputes (BM-NS-001 to BM-NS-050)

| Case | Complexity | Expected Liability | Refund | Key Evidence | Reasoning |
|---|---|---|---|---|---|
| BM-NS-001 | simple | charge_upheld | $0.00 | No-show charge dispute (simple scenario). | Driver waited 12 min after the scheduled pickup time (>5 min threshold), contacted rider via message and call, rider did not respond. Cancellation fee $5.00 properly applied. |
| BM-NS-004 | simple | charge_upheld | $0.00 | No-show charge dispute (simple scenario). | Driver waited 8 min after the scheduled pickup time (>5 min threshold), contacted rider via message and call, rider did not respond. Cancellation fee $5.00 properly applied. |
| BM-NS-008 | simple | charge_upheld | $0.00 | No-show charge dispute (simple scenario). | Driver waited 7 min after the scheduled pickup time (>5 min threshold), contacted rider via message and call, rider did not respond. Cancellation fee $5.00 properly applied. |
| BM-NS-016 | simple | refund | $5.00 | No-show charge dispute (simple scenario). | Driver cancelled after only 4 min (<5 min threshold). Cancellation fee not justified. |
| BM-NS-017 | simple | refund | $5.00 | No-show charge dispute (simple scenario). | Driver arrived more than 5 min after the scheduled pickup time (v2.1 Section 2.4). No-show charge not justified. |
| BM-NS-018 | simple | refund | $5.00 | No-show charge dispute (simple scenario). | Driver sent messages but made zero phone calls. Per v2.1 Section 2.3, both 1 message AND 1 call are required. Cancellation fee voided. |
| BM-NS-022 | simple | refund | $5.00 | No-show charge dispute (simple scenario). | Driver cancelled after only 4 min (<5 min threshold). Cancellation fee not justified. |
| BM-NS-023 | simple | refund | $5.00 | No-show charge dispute (simple scenario). | Driver arrived more than 5 min after the scheduled pickup time (v2.1 Section 2.4). No-show charge not justified. |
| BM-NS-024 | simple | refund | $5.00 | No-show charge dispute (simple scenario). | Driver sent messages but made zero phone calls. Per v2.1 Section 2.3, both 1 message AND 1 call are required. Cancellation fee voided. |
| BM-NS-026 | complex | charge_upheld | $0.00 | No-show charge dispute (complex scenario). | Rider has fraud history and multiple past rejected disputes, but the charge is upheld based on current trip evidence (driver waited >5 min, contacted rider via both message and call). Per v2.1 Section 6.3, confidence threshold raised to 95% due to fraud flag. |
| BM-NS-027 | complex | charge_upheld | $0.00 | No-show charge dispute (complex scenario). | Rider claims pickup pin was moved, but the change is only in client log (not server-confirmed). Driver waited >5 min at the original pin. Charge upheld pending server evidence. |
| BM-NS-028 | complex | charge_upheld | $0.00 | No-show charge dispute (complex scenario). | Timing comes from client clock only, but GPS and app events corroborate a wait >5 min. Charge upheld with note about timing source. |
| BM-NS-029 | complex | charge_upheld | $0.00 | No-show charge dispute (complex scenario). | Advanced trip: driver waited >5 min after arrival, rider no-show. Cancellation fee $5.00 properly applied per advanced trip policy. |
| BM-NS-030 | complex | charge_upheld | $0.00 | No-show charge dispute (complex scenario). | Rider has fraud history and multiple past rejected disputes, but the charge is upheld based on current trip evidence (driver waited >5 min, contacted rider via both message and call). Per v2.1 Section 6.3, confidence threshold raised to 95% due to fraud flag. |
| BM-NS-031 | complex | charge_upheld | $0.00 | No-show charge dispute (complex scenario). | Rider claims pickup pin was moved, but the change is only in client log (not server-confirmed). Driver waited >5 min at the original pin. Charge upheld pending server evidence. |
| BM-NS-036 | complex | refund | $5.00 | No-show charge dispute (complex scenario). | GPS telemetry shows driver was NOT at the pickup point (500m away). Rider responded saying they were on the way. No-show charge not justified. |
| BM-NS-037 | complex | refund | $5.00 | No-show charge dispute (complex scenario). | Server confirms rider changed pickup pin before driver arrival. Driver waited at the old pin. No-show conditions not met. Refund $5.00. |
| BM-NS-038 | complex | refund | $5.00 | No-show charge dispute (complex scenario). | Rider responded in chat saying they are coming down, but driver cancelled after only 5 min. Driver did not wait sufficiently after rider responded. |
| BM-NS-042 | complex | refund | $5.00 | No-show charge dispute (complex scenario). | GPS telemetry shows driver was NOT at the pickup point (500m away). Rider responded saying they were on the way. No-show charge not justified. |
| BM-NS-044 | complex | refund | $5.00 | No-show charge dispute (complex scenario). | Rider responded in chat saying they are coming down, but driver cancelled after only 5 min. Driver did not wait sufficiently after rider responded. |
| BM-NS-046 | complex | human_review | $0.00 | No-show charge dispute (complex scenario). | Safety threat detected in driver messages. Per v2.1 Section 5, must be escalated to human review regardless of no-show evidence. |
| BM-NS-047 | complex | human_review | $0.00 | No-show charge dispute (complex scenario). | App events say driver arrived but GPS shows driver 500m away, and timing is from client clock only. Evidence integrity conflict requires human review. |
| BM-NS-048 | complex | human_review | $0.00 | No-show charge dispute (complex scenario). | No chat or call records available. Cannot verify driver met both contact obligations (1 message AND 1 call). Insufficient evidence for automated ruling. |
| BM-NS-049 | complex | human_review | $0.00 | No-show charge dispute (complex scenario). | Safety threat detected in driver messages. Per v2.1 Section 5, must be escalated to human review regardless of no-show evidence. |
| BM-NS-050 | complex | human_review | $0.00 | No-show charge dispute (complex scenario). | App events say driver arrived but GPS shows driver 500m away, and timing is from client clock only. Evidence integrity conflict requires human review. |

---

## Route Deviation Disputes (BM-RD-001 to BM-RD-050)

| Case | Complexity | Expected Liability | Refund | Key Evidence | Reasoning |
|---|---|---|---|---|---|
| BM-RD-001 | simple | charge_upheld | $0.00 | Route deviation dispute (simple scenario). | Driver followed the recommended route. GPS matches. Fixed fare $18.00 unchanged. Charge upheld. |
| BM-RD-003 | simple | charge_upheld | $0.00 | Route deviation dispute (simple scenario). | Driver followed the recommended route. GPS matches. Fixed fare $12.00 unchanged. Charge upheld. |
| BM-RD-006 | simple | charge_upheld | $0.00 | Route deviation dispute (simple scenario). | Driver rerouted due to traffic incident and notified rider. Rider agreed to deviation. Per v2.1 Section 1.3, no refund when rider is informed and agrees. Fare $15.00 unchanged. |
| BM-RD-008 | simple | charge_upheld | $0.00 | Route deviation dispute (simple scenario). | Driver rerouted due to traffic incident and notified rider. Rider agreed to deviation. Per v2.1 Section 1.3, no refund when rider is informed and agrees. Fare $15.00 unchanged. |
| BM-RD-009 | simple | charge_upheld | $0.00 | Route deviation dispute (simple scenario). | Driver rerouted due to traffic incident and notified rider. Rider agreed to deviation. Per v2.1 Section 1.3, no refund when rider is informed and agrees. Fare $15.00 unchanged. |
| BM-RD-011 | simple | charge_upheld | $0.00 | Route deviation dispute (simple scenario). | Deviation of 0.7 km is within the 1km tolerance per v2.1 Section 1.3. No refund applicable. Charge upheld. |
| BM-RD-014 | simple | charge_upheld | $0.00 | Route deviation dispute (simple scenario). | Deviation of 0.9 km is within the 1km tolerance per v2.1 Section 1.3. No refund applicable. Charge upheld. |
| BM-RD-016 | simple | refund | $2.40 | Route deviation dispute (simple scenario). | Driver rerouted for traffic but failed to notify rider per v2.1 Section 1.2. Deviation 3.0 km > 1km tolerance. Partial refund of excess distance fare $2.40. |
| BM-RD-019 | simple | refund | $1.36 | Route deviation dispute (simple scenario). | Driver rerouted for traffic but failed to notify rider per v2.1 Section 1.2. Deviation 1.7 km > 1km tolerance. Partial refund of excess distance fare $1.36. |
| BM-RD-020 | simple | refund | $1.36 | Route deviation dispute (simple scenario). | Driver rerouted for traffic but failed to notify rider per v2.1 Section 1.2. Deviation 1.7 km > 1km tolerance. Partial refund of excess distance fare $1.36. |
| BM-RD-021 | simple | refund | $1.60 | Route deviation dispute (simple scenario). | Driver rerouted without traffic justification. Deviation 2.0 km > 1km tolerance. Per v2.1 Section 1.3, full refund of excess distance fare $1.60. |
| BM-RD-022 | simple | refund | $2.64 | Route deviation dispute (simple scenario). | Driver rerouted without traffic justification. Deviation 3.3 km > 1km tolerance. Per v2.1 Section 1.3, full refund of excess distance fare $2.64. |
| BM-RD-026 | complex | charge_upheld | $0.00 | Route deviation dispute (complex scenario). | Rider suggested shorter route, but driver took fastest route and notified rider. Traffic on direct route justified reroute. Rider agreed. Only excess tolls $1.40 passed through at cost. Charge upheld. |
| BM-RD-027 | complex | charge_upheld | $0.00 | Route deviation dispute (complex scenario). | Rider suggested shorter route, but driver took fastest route and notified rider. Traffic on direct route justified reroute. Rider agreed. Only excess tolls $1.07 passed through at cost. Charge upheld. |
| BM-RD-028 | complex | charge_upheld | $0.00 | Route deviation dispute (complex scenario). | Rider suggested shorter route, but driver took fastest route and notified rider. Traffic on direct route justified reroute. Rider agreed. Only excess tolls $1.39 passed through at cost. Charge upheld. |
| BM-RD-029 | complex | charge_upheld | $0.00 | Route deviation dispute (complex scenario). | Traffic incident on recommended route. Driver rerouted, notified rider, rider agreed. Deviation 2.1 km but excess is tolls only ($1.40) passed through at cost. Per v2.1 Section 1.3, no refund when rider informed and agrees. |
| BM-RD-030 | complex | charge_upheld | $0.00 | Route deviation dispute (complex scenario). | Traffic incident on recommended route. Driver rerouted, notified rider, rider agreed. Deviation 1.7 km but excess is tolls only ($1.81) passed through at cost. Per v2.1 Section 1.3, no refund when rider informed and agrees. |
| BM-RD-031 | complex | charge_upheld | $0.00 | Route deviation dispute (complex scenario). | Traffic incident on recommended route. Driver rerouted, notified rider, rider agreed. Deviation 1.3 km but excess is tolls only ($1.69) passed through at cost. Per v2.1 Section 1.3, no refund when rider informed and agrees. |
| BM-RD-032 | complex | charge_upheld | $0.00 | Route deviation dispute (complex scenario). | Minor deviation 0.4 km is within 1km tolerance per v2.1 Section 1.3. Driver notified rider. Traffic justified small reroute. Charge upheld. |
| BM-RD-036 | complex | refund | $3.52 | Route deviation dispute (complex scenario). | Driver rerouted for genuine traffic incident but failed to notify rider per v2.1 Section 1.2. Rider inquired about route and driver gave dismissive response. Deviation 4.4 km > 1km. Partial refund of excess distance fare $3.52 (tolls excluded, passed through at cost). |
| BM-RD-040 | complex | refund | $2.16 | Route deviation dispute (complex scenario). | GPS trace does not match any recommended route. No traffic evidence to justify deviation. Deviation 2.7 km > 1km. Per v2.1 Section 1.3, full refund of excess distance fare $2.16. |
| BM-RD-043 | complex | refund | $2.08 | Route deviation dispute (complex scenario). | Fare breakdown does not reconcile — base fare appears inflated. Charged $18.38 exceeds quote $15.00. No traffic justification for deviation. Refund excess distance fare $2.08. |
| BM-RD-046 | complex | human_review | $0.00 | Route deviation dispute (complex scenario). | Navigation route records are missing. Cannot determine whether the route taken was the fastest recommended option. Human review required. |
| BM-RD-048 | complex | human_review | $0.00 | Route deviation dispute (complex scenario). | GPS trace conflicts with selected route data. Cannot establish whether route was efficient or if deviation was intentional. Evidence integrity conflict requires human review. |
| BM-RD-050 | complex | human_review | $0.00 | Route deviation dispute (complex scenario). | Safety threat detected in rider messages. Per v2.1 Section 5, must be escalated to human review regardless of route evidence. |

---

## Evaluation Guide

### Metrics to Calculate

| Metric | Formula |
|---|---|
| Accuracy | (correctly ruled cases) / (total cases) |
| Precision (refund) | (correctly refunded) / (all cases agent refunded) |
| Recall (refund) | (correctly refunded) / (all cases that should be refunded) |
| Precision (uphold) | (correctly upheld) / (all cases agent upheld) |
| Recall (uphold) | (correctly upheld) / (all cases that should be upheld) |
| Human review efficiency | (cases correctly routed to human) / (total human-review cases) |
| Business impact (refunds prevented) | (wrong refunds agent would have made) × $6.61 |
| Business impact (correct refunds) | (correct refunds agent made) × refund amount |

### How to Run

```bash
# 1. Seed the benchmark data into the database
python scripts/generate_benchmark.py

# 2. Run each case through the agent workflow
#    (use the existing demo benchmark script as a template)
python scripts/demo_benchmark.py --benchmark

# 3. Compare agent rulings against expected conclusions
#    The expected conclusions are in this document.
```
