# FactoryMind — 7-Day "Near-Real Product" Design

**Date:** 2026-05-31
**Deadline:** 2026-06-07 (7 days)
**Author:** vishal.i.m (with Claude)
**Status:** Approved design — pending spec review → implementation plans

---

## 1. Purpose & Success Criteria

FactoryMind already has a sound hierarchical multi-agent spine (Brain → 6 Managers → Workers, EventBridge choreography, CDK across 6 stacks, real ONNX + LSTM artifacts, a polished React dashboard, working AgentCore Runtime). The gap is the **last mile**: several leaf workers and the dashboard present *synthesized or stubbed* data as if it were live.

This effort closes that gap and pushes FactoryMind from "impressive demo" to **near-real product**:

- **Genuinely real, end-to-end on AWS** — nothing shown on the dashboard is faked or synthesized. If a number is on screen, it came from a real AWS data path.
- **Richer multivariate sensing + ML** — more CNC parameters and a retrained RUL/anomaly model.
- **Full maintenance lifecycle + immutable audit timeline.**
- **A closed control loop** — sense → decide → **act on the machine** (auto-stop) → **notify a human** (dispatch + agent voice) → **document** (repair receipt).
- **Product polish** — operations analytics, real Cognito auth/RBAC, an action-taking assistant.

**Success = a recorded video on Day 7 in which every capability shown is real**, against the live AWS deployment, with the closed loop demonstrated end to end.

### Non-goals (explicitly out of scope)
- Real physical CNC hardware — the simulator is the machine (it obeys IoT stop commands, exactly as a PLC would).
- Real sensor datasets — telemetry is a **richer synthetic** set, fully reproducible.
- Real Lookout for Equipment model (training takes days) — the "dual-detector consensus" is presented honestly as LSTM + statistical-process-control, not two opaque models.
- Multi-tenant / multi-plant. Single plant PLANT-001.
- Production-grade security hardening beyond Cognito + least-privilege IAM scoping where cheap.

---

## 2. Known defects this design fixes (verified in current code)

1. **Push path is a silent no-op.** `agents/iot_ingestion/workers/data_router.py:route_data` calls `publish_to_appsync`, but the iot-ingestion Lambda is **never given `APPSYNC_URL`/`APPSYNC_API_KEY`** env vars (deploy script only patches `REDIS_*` onto edge-ai/digital-twin). So `publish_to_appsync` returns at line 166 and the `onMachineStateUpdated` subscription never fires.
2. **The push lies about state** — it hardcodes `status:"RUNNING", health_score:1.0` (`data_router.py:197-198`).
3. **Two divergent publishers** — `data_router.publish_to_appsync` (env `APPSYNC_URL`) vs `digital_twin/workers/dashboard_worker.publish_to_appsync` (env `APPSYNC_API_URL`). Mismatched names, duplicated logic.
4. **Dashboard synthesizes most tiles** — `dashboard/lib/useLiveMachines.ts:toMachine()` invents temp/rpm/load/energy from formulas; only 4 sensors are real.
5. **Silent 4s mock fallback** — `useLiveMachines.ts:209-225` swaps in `mockData` with no indication.
6. **Energy is a constant** — `agents/sustainability/workers/energy_monitor.py:79` runs the Timestream query then returns `[{"machine_id":"CNC-AERO-01","power_kwh":12.5}]`; baselines return `{}`. (Stub existed only because the old workshop account blocked Timestream — now unblocked.)
7. **Maintenance hygiene** — work-order IDs from a non-atomic module-global counter; `except Exception: pass` swallowing EventBridge failures; vision preprocessing a no-op; defect-rate divides by default `batch_size=1`.

---

## 3. Environment & Constraints

- **AWS account:** personal/full access. Timestream, SageMaker, Lookout, Bedrock, Polly, Connect all available. Cost matters → scale-to-zero where possible, tear down between sessions (~$5/day idle).
- **Dev host:** Windows 11 + PowerShell + Git Bash. `scripts/deploy.ps1` + `build_layers.sh` are Windows-safe (pip manylinux wheels, no Docker).
- **Region:** us-east-1 (matches prior outputs); confirm at deploy.
- **Redeploy from scratch** — stacks currently torn down.

---

## 4. Phased Plan (each day ships a real, demoable increment)

Dependencies flow downward. **Floor = Days 1–4** (must land). Days 5–6 are individually droppable upside.

### Phase 1 (Day 1) — Foundation & Honesty
**Outcome:** clean redeploy; dashboard shows 100% real data for the existing sensors; no synthesis, no silent fallback.

- **Push wiring:** add `APPSYNC_URL` + `APPSYNC_API_KEY` env vars to the iot-ingestion Lambda in `compute_stack.py` (or the deploy patch step). Reconcile the two `publish_to_appsync` functions into one shared helper in `agents/shared/utils/appsync.py`; standardize env var names.
- **Real state in push:** derive `status` and `health_score` from the anomaly detector output already computed in the ingestion manager (not hardcoded). Map: ANOMALY/compound→FAULT + low health; WARNING→degraded; else RUNNING + health from a documented telemetry→health function.
- **Dashboard honesty:** in `useLiveMachines.ts`, drop synthesized tiles (temp/rpm/load/energy) OR mark any derived value with a visible "derived" affordance; show the real sensor set. Remove the 4s mock fallback; replace with an explicit `LIVE` / `NO DATA` indicator driven by `live`.
- **Real energy:** rewrite `energy_monitor._query_energy_readings` to parse the Timestream response (delete the placeholder return); implement `_get_baselines` against `FactoryMind_EnergyBaselines`. Re-enable Timestream in `storage_stack.py`.
- **Hygiene:** replace `except: pass` with structured logging on EventBridge/AppSync failures.
- **Deploy + smoke test:** full `deploy.ps1`, then `simulate_aerospace_cnc.py --mode optimal --publish` and confirm the dashboard reflects real telemetry within one poll/push cycle.

### Phase 2 (Day 2) — Richer Sensing & ML
**Outcome:** richer real telemetry flowing; a real multivariate model producing RUL on a live endpoint; a real trained vision model for quality (no managed-API hand-waving).

- **Expanded telemetry schema** — extend `agents/shared/models/sensor.py` `Telemetry` with: `spindle_temp_c`, `tool_rpm`, `feed_rate_mm_min`, `axis_load_pct`, `ambient_temp_c`, `power_factor`, `tool_life_count`. Add physical-range validators. Keep the original 4 for backward compatibility.
- **Propagate** through `stream_validator`, `anomaly_detector` (new thresholds), `data_router` (Timestream measures + DynamoDB attrs), edge classifier, and the simulator (`scripts/simulate_aerospace_cnc.py` — emit new params with correlated noise; tool wear increments `tool_life_count` and degrades feed/axis-load).
- **Retrained model** — new training script under `models/rul/` producing a multivariate model that outputs **anomaly probability + estimated_rul_hours** from the richer feature vector (synthetic training data generator included, reproducible). Package + deploy a new SageMaker serverless endpoint (`factorymind-rul`). Replace/augment the LSTM worker; wire predictive-maintenance manager and the dashboard maintenance page to the **real** prediction (kill the client-side "ARIMA-ish" forecast).
- **Real vision model (replaces Amazon Rekognition)** — **remove** `quality_vision/workers/rekognition_worker.py` and all `rekognition:*` IAM. Fine-tune **YOLOv8** (Ultralytics) on a real **public** metal-surface-defect dataset (default **NEU-DET**; GC10-DET alternative) — real images, real bounding boxes, reproducible, zero data cost. New `models/vision/` (dataset prep, `inference.py`, `metrics.json`, packaging). **Training runs offline on Colab (free GPU)** via `models/vision/train_yolov8_colab.ipynb` — I prepare the notebook, you run it (~15 min), download the resulting `best.pt` weights into `models/vision/`. Then package + deploy SageMaker serverless endpoint `factorymind-yolov8-quality` + artifact upload from those weights. Make `vision_preprocessor.py` actually resize-to-640 + normalize (currently a no-op); new `yolov8_worker.py` is the **primary** detector; `defect_analyser.py` consumes real detections + boxes and fixes the `batch_size=1` defect-rate bug. Note: vision is the one place we use **real** data (public images), in contrast to synthetic telemetry — a credibility win. (Vision train+deploy is parallelizable; dashboard rendering lands in Phase 5.)
- **Tests:** model I/O shape, validator ranges, simulator output schema, vision detection parsing + box mapping.

### Phase 3 (Day 3) — Maintenance Lifecycle & Audit Timeline
**Outcome:** full maintenance history, manageable work orders, immutable decision/audit trail.

- **`FactoryMind_MaintenanceLogs` table** — work-order lifecycle events (status transitions, technician, parts, downtime, notes), keyed by work_order_id + timestamp.
- **WO lifecycle state machine** — OPEN→IN_PROGRESS→COMPLETED (+CANCELLED); enforce transitions; atomic WO-ID via DynamoDB counter (replace module-global).
- **Sensor snapshot at event** — persist the raw richer telemetry snapshot with each anomaly/work-order for "what did it look like when it failed" replay.
- **Audit/decision timeline** — `FactoryMind_AuditTimeline` table (append-only) capturing every Brain decision, escalation, and closed-loop action with correlation IDs; fed from EventBridge.
- **Tool-life tracking** — cycles per tool, predicted replacement from `tool_life_count` + RUL; replacement history.
- **WO-management UI** — dashboard actions (assign/advance/close) via real AppSync mutations; maintenance-history view per machine.
- **Audit timeline view** — new `dashboard/routes/dashboard.audit.tsx` showing linked incident chains by `incident_id`.
- **`incident_id` threading** — single correlation ID carried through anomaly → brain decision → work order (and Phase-4 closed-loop actions) so the audit timeline reconstructs each incident as one story. Audit entries written by a new `audit_logger` Lambda fed by an EventBridge rule matching all `factorymind.*` events (event-sourced — never hand-written).
- **Realistic backfill seed** — `scripts/seed_history.py` generates ~weeks of plausible past work orders, completions, tool replacements, and audit entries (clearly-labeled synthetic timestamps) so history/OEE views look like a real running plant on day one.

### Phase 4 (Day 4) — 🔥 Closed-Loop Autonomous Response
**Outcome:** the hero feature — sense → act → notify → document, fully logged.

- **Orchestration (DECIDED: Brain-orchestrated):** Edge detects → Brain assesses CRITICAL → publishes `BrainDecision` → EventBridge rule → new **Response/Actuation service** (`agents/response/`) orchestrates stop + dispatch + voice + receipt together under one `incident_id`. **Idempotent** (dedup on `incident_id` — EventBridge is at-least-once; must not double-stop/double-dispatch).
- **Pre-flight (sandbox):** SES + SNS SMS are in sandbox → verify the demo technician email + phone first; recipient config in Secrets Manager (not hardcoded).
- **Auto-stop actuation:** the Response service publishes a stop command to IoT topic `factory/aerospace/cnc/command/{machine_id}` (+ device shadow desired=STOPPED). The **simulator subscribes and obeys** — halts publishing / emits STOPPED state. Logged to audit timeline + reflected on dashboard (machine → STOPPED/red).
- **Auto-dispatch technician:** SNS SMS + SES email to the on-call technician with the diagnosis, machine, severity, work-order link.
- **Agent voice:** Amazon Polly synthesizes a spoken diagnosis ("CNC-AERO-07 spindle vibration exceeded 8 mm/s with coolant loss — machine stopped, tool replacement dispatched"). Store clip in S3; dashboard plays it; attach to dispatch.
- **Repair receipt:** generate a PDF (incident summary + sensor snapshot + action taken + work order + technician + cost) → S3 `factorymind-receipts` → downloadable from the dashboard + linked in audit timeline.
- **Stretch (only if Phase 1–4 land early): real Amazon Connect outbound call** playing the Polly diagnosis to the technician's phone. Requires claimed number + sandbox exit — attempt last.

### Phase 5 (Day 5) — Operations & Analytics
**Outcome:** product-grade operational views.

- **Machine drill-down page** — per-machine historical charts from Timestream (all richer params), maintenance history, tool life, health trend. Timestream is queried via a **Lambda resolver** (`agents/analytics/history_worker.py`) since AppSync can't hit Timestream directly. New route `dashboard/routes/dashboard.machine.$id.tsx`.
- **OEE analytics** — `agents/analytics/oee_worker.py` computes real Availability × Performance × Quality (ideal cycle time per part type seeded as a documented constant); exposed via `getOEE(machine_id, window)` AppSync query.
- **Alert/notification center** — `FactoryMind_Alerts` table; alert rows created on anomaly/escalation events; AppSync `listAlerts`/`acknowledgeAlert`/`resolveAlert`; new route `dashboard/routes/dashboard.alerts.tsx` with severity filtering + history.
- **Quality page (real vision)** — render the actual inspected image with the YOLOv8 bounding boxes + real confidences; replace the hardcoded `96.4%` accuracy with the model's real eval metrics. Seed a few real defect/OK images into the `product-images` S3 bucket to trigger the live S3 → Quality Vision flow on camera.

### Phase 6 (Day 6) — Intelligence & Auth
**Outcome:** secure, conversational, action-taking product.

- **Acting AgentCore assistant** — read tools (query maintenance/audit/telemetry via Bedrock KB) + action tools (`createWorkOrder`, `acknowledgeAlert`, `stopMachine`). **DECIDED: always-confirm** — assistant proposes, human confirms in UI, then it fires. Safety-critical autonomy stays with the deterministic P4 closed-loop; the chat assistant is human-in-the-loop. **Action tools call the SAME audited, RBAC-checked backend as the dashboard buttons** (no parallel path); every action lands on the audit timeline with its `incident_id`.
- **Real Cognito auth + RBAC** — replace `dashboard/lib/auth.ts` localStorage fake with Amplify + Cognito user pools; switch AppSync `defaultAuthMode` to `AMAZON_COGNITO_USER_POOLS` (this also deletes the browser-exposed API key — the Ring-4 secret fix). Groups Operator/Manager/CXO. **DECIDED: server-side enforced** — Cognito groups gate sensitive mutations (`stopMachine`, `createWorkOrder`) at the AppSync/resolver level, not just hidden in the UI; can't be bypassed via devtools. New `auth_stack` (or extend frontend).

### Phase 7 (Day 7) — Harden, Record, Ship
- E2E test the full kill-chain + closed loop on live AWS.
- Polish, fix rough edges, scope-cut gracefully if needed.
- Record the video. Tear down to control cost.

---

## 5. New / Changed AWS Resources

| Resource | Stack | Purpose |
|---|---|---|
| Timestream DB + tables (re-enabled) | storage | real time-series energy + telemetry history |
| `FactoryMind_MaintenanceLogs` (DynamoDB) | storage | WO lifecycle history |
| `FactoryMind_AuditTimeline` (DynamoDB) | storage | immutable decision/action log |
| `FactoryMind_Alerts` (DynamoDB) | storage | alert center state |
| WO-ID atomic counter item (DynamoDB) | storage | unique sequential WO IDs |
| `factorymind-receipts` (S3) | storage | repair-receipt PDFs + Polly clips |
| SageMaker endpoint `factorymind-rul` | ml | multivariate RUL/anomaly inference |
| SageMaker endpoint `factorymind-yolov8-quality` | ml | real defect detection (YOLOv8, replaces Rekognition) |
| ~~Amazon Rekognition~~ (REMOVED) | — | replaced by trained YOLOv8 vision model |
| IoT command topic + rule `factory/aerospace/cnc/command/+` | iot | auto-stop actuation |
| Polly (managed) IAM grant | compute | agent voice |
| SES identity + SNS SMS | iot/compute | technician dispatch |
| Cognito user pool + identity pool | frontend/auth | real auth + RBAC |
| Amazon Connect instance + claimed number (stretch) | (manual/out-of-band) | outbound voice call |
| Lambda env: `APPSYNC_URL`, `APPSYNC_API_KEY` on iot-ingestion | compute | fix push path |

IAM: scope wildcard policies (Bedrock/SES/SageMaker/Polly/AppSync) to specific ARNs where it costs little time.

---

## 6. Data Flow — Closed Loop (Phase 4)

```
simulator (catastrophic) ─MQTT─> IoT Core ─> Edge AI (compound rule: vib>8 AND coolant<30)
   └─> EventBridge (EDGR- CRITICAL) ─> Brain (assess CRITICAL, escalate_to_human)
        ├─> Predictive Maintenance ─> Work Order (consensus) ─> MaintenanceLogs
        ├─> Actuation worker ─> IoT command topic ─> simulator STOPS  ──┐
        ├─> Dispatch: SES email + SNS SMS (+ Connect call stretch)      │ all logged to
        ├─> Polly: synthesize diagnosis ─> S3 clip                      │ AuditTimeline
        ├─> Receipt: render PDF ─> S3 factorymind-receipts              │ + pushed to
        └─> Digital Twin ─> AppSync updateMachineState ─> dashboard ────┘ dashboard (red, audio, receipt link)
```

---

## 7. Error Handling & Observability
- No silent swallows: every external-call failure logs structured context (no secrets) and, where it affects safety (auto-stop, escalation), publishes to a DLQ + CloudWatch alarm.
- Closed-loop actions are **idempotent + correlation-ID tagged** end to end so the audit timeline reconstructs each incident.
- The auto-stop path must be observable: if the stop command fails to deliver, that is itself a CRITICAL alert.

## 8. Testing Strategy
- Unit: new validators, model I/O, WO state machine, health-derivation function, receipt rendering.
- Integration (moto + fakeredis): push path sets real status; closed-loop sequence produces all five artifacts (stop cmd, dispatch, voice, receipt, audit entries).
- E2E (Day 7): live AWS catastrophic run → assert machine stops, technician notified, receipt in S3, dashboard reflects within SLA.
- TDD for the health-derivation and RUL-wiring logic (behavior with multiple valid approaches).

## 9. Risks & Mitigations
| Risk | Mitigation |
|---|---|
| Scope too big for 7 days | Floor = Days 1–4; Days 5–6 droppable; daily demoable increments |
| SageMaker endpoint cold start / shape mismatch | Validate shape in Phase 2; keep rule-based fallback labeled honestly |
| Amazon Connect sandbox/number provisioning | Stretch only; Polly+SMS+email is the reliable primary |
| Redeploy time / cost | Scripted deploy; tear down nightly; ~$5/day idle |
| Windows layer build | Already mitigated (manylinux pip, no Docker) |
| IoT auto-stop round-trip in sim | We own the simulator; subscribe + obey is straightforward |

## 10. Cost & Teardown
~$5/day idle (ElastiCache Serverless + NAT + SageMaker + misc) plus negligible Polly/SMS. Tear down between work sessions per DEPLOY_STEPS.md Part E. Connect (if attempted) — release the number after recording.

## 11. Deliverable
A Day-7 video against live AWS: optimal run (real telemetry) → trigger tool-wear (real RUL prediction + scheduled WO) → trigger catastrophic failure → **closed loop**: machine auto-stops, technician dispatched (voice + SMS/email, Connect call if landed), repair receipt generated, every step on the audit timeline and dashboard. Narrated as a real product.

---

## Appendix A — Full Change Manifest

Approx **~20 new files, ~30 changed, ~4 removed**, plus cloud resources. Bulk of must-haves are Phases 1–4.

### Backend agents (`agents/`)
- **ADD:** `shared/utils/appsync.py` (P1), `shared/utils/health.py`+test (P1), `predictive_maintenance/workers/rul_worker.py` (P2), `.../spc_worker.py` (P2), `.../tool_life_worker.py` (P3), `predictive_maintenance/work_order_lifecycle.py`+test (P3), `quality_vision/workers/yolov8_worker.py` (P2), `audit_logger/handler.py` (P3), `response/handler.py`+`workers/{actuator,dispatcher,voice,receipt}.py` (P4), `analytics/{oee_worker,history_worker}.py` (P5)
- **CHANGE:** `shared/models/sensor.py` (P2), `iot_ingestion/workers/{data_router,stream_validator,anomaly_detector}.py` (P1/P2), `sustainability/workers/energy_monitor.py` (P1), `digital_twin/workers/dashboard_worker.py` (P1), `edge_ai/workers/edge_classifier.py` (P2), `predictive_maintenance/workers/{workorder_worker,scheduler_worker}.py` + `manager/handler.py` (P2/P3), `quality_vision/workers/{vision_preprocessor,defect_analyser}.py` + `manager/handler.py` (P2), `brain/{graph,handler}.py` (P3/P4), `assistant_gateway/handler.py` (P6)
- **REMOVE:** `quality_vision/workers/rekognition_worker.py`, `predictive_maintenance/workers/lookout_worker.py`, `.../lstm_worker.py` (all P2)

### ML (`models/`)
- **ADD:** `models/rul/*` (synthetic_data, train_rul, inference, feature_config.json, metrics.json, package_rul.sh) (P2); `models/vision/*` (prepare_neu_det, inference, train_yolov8_colab.ipynb, metrics.json, package_vision.sh, best.pt) (P2)
- **CHANGE:** `models/edge/train_edge_classifier.py` → v3 (P2)
- **REMOVE/DEPRECATE:** `models/lstm/*` (superseded by `models/rul/`)

### Infra (`infrastructure/cdk/`)
- **ADD:** `stacks/auth_stack.py` (P6), KMS CMK construct
- **CHANGE:** `stacks/storage_stack.py` (Timestream re-enable; +MaintenanceLogs/AuditTimeline/ToolLife/Alerts tables + WO counter; receipts S3; SSE-KMS everywhere; ElastiCache TLS), `stacks/iot_stack.py` (command topic+rule; audit/response EventBridge rules), `stacks/compute_stack.py` (new Lambdas; AppSync env on ingestion; Polly/SES/SNS/Secrets IAM; scope wildcards; drop rekognition), `stacks/ml_stack.py` (rul + yolov8 endpoints; resolvers; AppSync→Cognito), `schema/factorymind.graphql`, `app.py`

### Dashboard (`dashboard/`)
- **ADD:** `routes/dashboard.{audit,alerts}.tsx`, `routes/dashboard.machine.$id.tsx`, GraphQL ops, box-overlay/receipt-viewer/voice-player components
- **CHANGE:** `lib/useLiveMachines.ts`, `lib/auth.ts`, `routes/login.tsx`, `main.tsx`, `components/DashboardLayout.tsx`, `routes/dashboard.{maintenance,quality,index,sustainability,edge,twin}.tsx`, `lib/mockData.ts`
- **REMOVE:** client-side "ARIMA-ish" forecast + hardcoded metrics (247 sensors / 7ms / 96.4%)

### Scripts (`scripts/`)
- **ADD:** `seed_history.py` (P3)
- **CHANGE:** `simulate_aerospace_cnc.py` (richer params + obey stop), `seed_dummy_data.py`, `deploy.ps1`/`deploy.sh`, `build_layers.sh` (+fpdf2)

### Security (cross-cutting)
- **ADD:** KMS CMK, Secrets Manager secrets, `.pre-commit-config.yaml`+gitleaks
- **CHANGE:** scope wildcard IAM → ARNs, SSE-KMS on all stores, AppSync→Cognito, ElastiCache cert verify

### New AWS resources (cloud)
KMS CMK · Secrets Manager · Timestream (re-enabled) · 4 DynamoDB tables + counter · `factorymind-receipts` S3 · 2 SageMaker endpoints (`factorymind-rul`, `factorymind-yolov8-quality`) · IoT command topic+rule · Polly · SES identity · SNS SMS · Cognito user+identity pools + 3 groups · 2 EventBridge rules · Amazon Connect (stretch)

### Manual / out-of-band (you run)
Train edge+RUL locally · Colab YOLOv8 → download `best.pt` · verify SES email + SNS phone (sandbox) · (stretch) claim Connect number · run deploy + seed + smoke tests at each gate
