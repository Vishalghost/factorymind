# FactoryMind Sustainability Playbook — Aerospace CNC Titanium Milling

This document is the source of truth for the Bedrock Knowledge Base used by
the Sustainability Manager and the GenAI Assistant in PLANT-001 (Chennai,
50 CNC machines, Ti-6Al-4V).

It contains plant-specific benchmarks, energy targets, and remediation
playbooks. The Bedrock retrieval pipeline chunks this file and surfaces the
most relevant sections back to Claude when an operator asks an energy or
ESG question.

---

## 1. Plant baseline (PLANT-001)

| Metric                              | Baseline             | Target               | Source                       |
|-------------------------------------|----------------------|----------------------|------------------------------|
| Plant connected load                | 1,200 kW             | 1,050 kW             | 50 × 24 kW machines          |
| Average per-machine consumption     | 18 kWh/h (running)   | 14 kWh/h             | DDB EnergyBaselines          |
| Idle-state consumption              | 1.2 kWh/h per asset  | < 0.4 kWh/h          | Auxiliary cooling + control  |
| Carbon intensity (TN grid, 2026)    | 0.82 kg CO₂ / kWh    | n/a                  | TANGEDCO disclosure          |
| Energy cost (HT industrial, 2026)   | ₹8.5 / kWh           | n/a                  | TNERC tariff                 |
| Off-peak window                     | 22:00 – 06:00 IST    | n/a                  | TANGEDCO tariff              |
| Off-peak discount                   | 20% on energy charge | n/a                  | TANGEDCO tariff              |

Off-peak shifting is the highest-leverage saving lever — moving 18 % of
discretionary CNC load into the 02:00 – 05:00 window saves ≈ ₹1.2 L/month
plant-wide at current duty cycle.

---

## 2. Industry benchmarks for CNC titanium milling

Source: ASME MFG-2024 sustainability survey + Indian Aerospace Manufacturing
Council (IAMC) 2025 working group.

- **Spindle-load efficiency**: best-in-class 5-axis Ti milling cells run at
  62 – 68 % spindle utilisation. Below 45 % is a strong signal of poor
  process planning (oversized fixtures, dry cycles).
- **Coolant pump duty**: leaders run pumps on demand-based VFDs with average
  duty 38 %. Constant-on pump runtime indicates an integration gap.
- **Vacuum / chip-evac**: typical waste — the chip conveyor stays on during
  tool changes. Conditional on M-codes, expect 15 – 22 % reduction.
- **Shop-air leakage**: industry studies show 20 – 30 % of compressed-air
  energy is lost to leaks. Ultrasonic detection finds 80 % within 4 hours.
- **HVAC interlock**: chiller setpoint should rise 2 °C between shifts; at
  PLANT-001 this saves 4.2 kWh/hour per zone.

---

## 3. Anomaly → action playbook

The Sustainability Manager combines `energy_monitor` (DDB MachineState +
EnergyBaselines) with `waste_detector` (idle-while-on signature) and asks
Claude to produce 3-5 prescriptive recommendations. Use these patterns as
worked examples.

### 3.1 Idle-while-on (top priority)

**Signal**: status == IDLE for > 5 min AND current_amps > 1.5 A.
**Action**: trigger the auxiliary-power timeout (M30 + spindle off + coolant
off) via the digital twin's `setMachineMode` shadow update.
**Saving**: 0.8 – 1.2 kWh/h per asset. At 50 machines and 8 hour idle/day,
this saves 36 – 48 kWh/day plant-wide.

### 3.2 Spindle-load drift (efficiency degradation)

**Signal**: rolling 7-day current_amps mean shifts > 12 % above baseline
without a corresponding throughput gain.
**Action**: flag for spindle-bearing inspection — usually a precursor to
mechanical failure. The Predictive Maintenance manager will already have
opened a P2 work order; Sustainability adds the energy estimate to the
business case.
**Saving**: replacing a degraded spindle assembly typically saves 9 – 14 %
on that machine's energy footprint.

### 3.3 Coolant flow without cut

**Signal**: coolant_lmin > 4 AND vibration_mms < 0.6 (machine is up but not
cutting).
**Action**: enable conditional-coolant macro (M9 between blocks). Audit the
post-processor for stale program templates that hardcode flood-coolant.
**Saving**: 6 – 10 % of pump energy and proportional reduction in coolant
disposal volume.

### 3.4 Compressor short-cycling

**Signal**: ultrasonic anomaly + > 12 starts/hour on the central compressor.
**Action**: leak survey on the zone fed by the affected manifold.
PLANT-001 has a leak on Line B near CNC-AERO-21 noted 2026-04-22.
**Saving**: 4.2 kWh/h while the leak persists.

### 3.5 After-hours auxiliary load

**Signal**: plant total > 12 kWh/h between 23:30 – 05:30 with zero parts
produced.
**Action**: review HVAC and lighting interlocks; the Tier-2 PCV usually
remains on via local override.
**Saving**: 8 – 14 kWh/h during the affected window.

---

## 4. Carbon accounting (Scope 1 + 2)

PLANT-001 reports Scope 2 only (no on-site combustion). The conversion
factor (0.82 kg CO₂ / kWh) covers grid emissions per the 2026 TNERC
disclosure. Updates land in `FactoryMind_EnergyBaselines` annually.

The Sustainability Manager surfaces the **avoidable** carbon — kWh above
baseline × CARBON_KG_PER_KWH — not the absolute footprint, because the
absolute number is dominated by inevitable Ti-machining demand and is not
actionable for the operator.

For ESG reporting, see Annual disclosure SOP (separate doc, not in KB).

---

## 5. ESG ranking (carbon score)

| Score | Avoidable kWh / day  | Comments                                |
|-------|----------------------|-----------------------------------------|
| A+    | 0 – 25               | Best-in-class — zero idle waste.        |
| A     | 26 – 80              | On target; spot anomalies only.         |
| A-    | 81 – 160             | Default state — typical week.           |
| B     | 161 – 280            | Action plan needed within 7 days.       |
| C     | > 280                | Operator escalation; tariff impact.     |

Today's score is recomputed every 30 minutes by `kpi_calculator`.

---

## 6. Recommendation tone

When the GenAI Assistant or Sustainability Manager generates
recommendations:

- Lead with the action verb ("Power down …", "Shift … to off-peak", etc.).
- Cite the affected asset by ID where possible.
- Quantify the saving in either kWh/h, ₹/month, or kg CO₂/day — pick the
  unit the operator will care about for that recommendation.
- Stay under 25 words per recommendation. The operator reads this on a
  shop-floor dashboard, not a desktop browser.
- Never speculate on capex; capex is owned by the manufacturing engineering
  team, not the sustainability agent.

---

## 7. Glossary

- **OEE** — Overall Equipment Effectiveness; product of availability,
  performance, and quality. Reported by the Digital Twin manager, not
  Sustainability.
- **Idle-while-on** — the machine shows status IDLE but is still drawing
  current_amps > 1.5 A.
- **Avoidable kWh** — measured kWh above the per-machine baseline; the only
  number Sustainability acts on.
- **Off-peak** — TANGEDCO HT-3 industrial slab between 22:00 and 06:00
  with a 20 % discount on energy charge.
- **Spindle utilisation** — ratio of cutting time to spindle-on time;
  measured by the IoT ingestion manager from current_amps signature.
