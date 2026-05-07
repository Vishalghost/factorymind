# FactoryMind Maintenance Playbook — Aerospace CNC Titanium Milling

Used by: GenAI Assistant + Brain Agent. Provides decision rules for
predictive-maintenance recommendations.

---

## 1. Severity tiers

| Tier | Trigger                                                  | SLA      | Owner                |
|------|----------------------------------------------------------|----------|----------------------|
| P1   | Health < 50 OR vibration > 6.0 mm/s OR critical alert    | 8 h      | Maintenance lead     |
| P2   | Health 50-69 OR vibration 4.0-6.0 mm/s OR warning alert  | 36 h     | Maintenance team     |
| P3   | Health 70-84 OR scheduled preventive interval reached    | 5 d      | Operator next shift  |
| P4   | Routine — lubrication, fluid check                       | 30 d     | Operator             |

Vibration thresholds follow ISO 10816-3 zone-D for medium machines on rigid
foundations.

---

## 2. Failure-mode catalogue

### Spindle bearing wear
**Signature**: vibration_mms creeping above 2.5 mm/s with spectral peak
near bearing-defect frequency (computed offline).
**Remediation**: replace bearings within 36 h; do NOT continue to run a
critical Ti job past this signature — chatter wrecks the part.
**Energy impact**: 9-14 % consumption increase before failure.

### Hydraulic seal degradation (Press, conveyor)
**Signature**: load > 90 % AND temp > 95 °C for > 5 min.
**Remediation**: replace seal kit; pre-stage parts by querying
`FactoryMind_MachineSpecs` for the asset's seal SKU.
**LSTM forecast confidence**: > 90 % at 8 h horizon.

### Coolant-flow restriction
**Signature**: coolant_lmin < 6 with vibration > 1.5 mm/s during cut.
**Remediation**: clear filter; reverse-flush manifold. 30 min job.

### Tool flute breakage
**Signature**: acoustic_db spike > 95 dB plus a step change in current_amps.
**Remediation**: pause job, tool change, abandon current part as scrap.
The Quality Vision manager flags the affected serial automatically.

---

## 3. Work-order routing

When the Predictive Maintenance manager opens a work order, it lands in
SQS `factorymind-workorder-queue`. Routing logic:

1. P1 — page on-call SRE via SNS `factorymind-maintenance-alerts` and open
   the order with `status=OPEN`, `due=now+8h`.
2. P2 — open with `status=SCHEDULED`, `due=now+36h`. Maintenance lead picks
   up at the start of the next shift.
3. P3/P4 — open with `status=SCHEDULED`, `due=now+5d`. Reviewed in the
   weekly maintenance huddle.

The Brain Agent only escalates to a human (`escalate_to_human=true`) when:
- the same machine has produced two P1 alerts in the last 4 h, OR
- a P1 affects a machine on the critical path of a P&W order, OR
- the failure-mode catalogue does not match (unknown failure pattern).

---

## 4. Spare-parts cache

Maintained in `FactoryMind_MachineSpecs` under `spare_parts_sku`. The
Predictive Maintenance manager preloads parts into the work-order
description so the maintenance team doesn't have to look them up.

If the SKU is missing, request it from manufacturing engineering — do not
fabricate a SKU; the work order will be rejected by the ERP integration.

---

## 5. Reporting

Daily fault report (PDF, exported from the Predictive Maintenance tab) is
sent to the manufacturing manager mailing list at 06:30 IST. Generated
client-side from the same `FactoryMind_MachineState` snapshot that powers
the dashboard, so it is always consistent with the live UI.
