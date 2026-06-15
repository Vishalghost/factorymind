# Phase 1 — Foundation & Honesty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard show 100% real data end-to-end on AWS — real-time AppSync push working, real machine status/health derived from telemetry, real energy from Timestream, and zero synthesized tiles or silent mock fallback.

**Architecture:** The ingestion Lambda already computes anomalies and already has AppSync env-var slots — we thread the real anomaly severity into the AppSync push (replacing hardcoded `RUNNING`/`1.0`), reconcile the two duplicate publishers into one helper, re-add Timestream for real energy, and make the dashboard honest (real fields + LIVE/NO-DATA indicator).

**Tech Stack:** Python 3.11 (Pydantic, boto3, structlog, pytest, moto), AWS CDK (Python), React/TypeScript (Vite, Amplify, AppSync), PowerShell deploy.

**Reference spec:** `docs/superpowers/specs/2026-05-31-factorymind-near-real-product-design.md` (Phase 1 section).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `agents/shared/utils/appsync.py` | Single AppSync `updateMachineState` publisher used by all agents | Create |
| `agents/shared/utils/health.py` | Pure function: telemetry + anomaly severity → (status, health_score) | Create |
| `agents/iot_ingestion/workers/data_router.py` | Route to Timestream + DynamoDB + AppSync push (now with real status/health) | Modify |
| `agents/iot_ingestion/manager/handler.py` | Thread per-machine worst severity into `route_data` | Modify |
| `agents/iot_ingestion/workers/anomaly_detector.py` | Replace silent `except: pass` with structured log | Modify |
| `agents/digital_twin/workers/dashboard_worker.py` | Delegate to shared `appsync.py` | Modify |
| `agents/sustainability/workers/energy_monitor.py` | Real Timestream energy query + real baselines | Modify |
| `infrastructure/cdk/stacks/storage_stack.py` | Re-add Timestream DB + SensorReadings/EnergyReadings tables | Modify |
| `infrastructure/cdk/stacks/compute_stack.py` | Grant Timestream write/read to ingestion + sustainability | Modify |
| `scripts/deploy.ps1` | Post-deploy: patch ingestion Lambda APPSYNC_URL/KEY from ML outputs | Modify |
| `dashboard/lib/useLiveMachines.ts` | Show real fields only; LIVE/NO-DATA; remove silent mock fallback | Modify |
| `tests/unit/test_appsync_helper.py` | Tests for the shared publisher | Create |
| `tests/unit/test_health.py` | Tests for status/health derivation | Create |
| `tests/unit/test_energy_monitor.py` | Tests for real energy query parsing | Create |

---

## Task 1: Shared AppSync publisher helper

Reconcile the two divergent `publish_to_appsync` functions (`data_router.py` uses `APPSYNC_URL`; `dashboard_worker.py` uses `APPSYNC_API_URL`) into one helper with one env convention: `APPSYNC_URL` + `APPSYNC_API_KEY`.

**Files:**
- Create: `agents/shared/utils/appsync.py`
- Test: `tests/unit/test_appsync_helper.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_appsync_helper.py
import json
from unittest.mock import patch, MagicMock
from agents.shared.utils.appsync import publish_machine_state


def test_publish_machine_state_posts_mutation(monkeypatch):
    monkeypatch.setenv("APPSYNC_URL", "https://example.appsync-api.us-east-1.amazonaws.com/graphql")
    monkeypatch.setenv("APPSYNC_API_KEY", "da2-test")
    captured = {}

    class FakeResp:
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["headers"] = req.headers
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    with patch("urllib.request.urlopen", fake_urlopen):
        ok = publish_machine_state(
            machine_id="CNC-AERO-01", plant_id="PLANT-001",
            status="FAULT", health_score=0.12,
            telemetry={"vibration_mms": 9.1, "current_amps": 20.0,
                       "coolant_lmin": 12.0, "acoustic_db": 80.0},
            updated_at="2026-05-31T10:00:00Z",
        )
    assert ok is True
    assert captured["body"]["variables"]["input"]["status"] == "FAULT"
    assert captured["body"]["variables"]["input"]["health_score"] == 0.12
    assert captured["headers"]["X-api-key"] == "da2-test"


def test_publish_machine_state_noop_without_env(monkeypatch):
    monkeypatch.delenv("APPSYNC_URL", raising=False)
    monkeypatch.delenv("APPSYNC_API_KEY", raising=False)
    assert publish_machine_state(
        machine_id="CNC-AERO-01", plant_id="PLANT-001",
        status="RUNNING", health_score=1.0, telemetry={}, updated_at="x"
    ) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/unit/test_appsync_helper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.shared.utils.appsync'`

- [ ] **Step 3: Write minimal implementation**

```python
# agents/shared/utils/appsync.py
"""Single AppSync publisher for machine-state updates.

Fires the `updateMachineState` mutation so the dashboard's
`onMachineStateUpdated` subscription pushes to clients. Best-effort:
a no-op (returns False) if APPSYNC_URL / APPSYNC_API_KEY are unset.
"""
import json
import os
import urllib.request
from typing import Any

import structlog

logger = structlog.get_logger()

_MUTATION = (
    "mutation UpdateMachineState($input: MachineStateInput!) {\n"
    "  updateMachineState(input: $input) {\n"
    "    machine_id plant_id status health_score updated_at\n"
    "    last_telemetry { vibration_mms current_amps coolant_lmin acoustic_db }\n"
    "  }\n"
    "}"
)


def publish_machine_state(
    machine_id: str,
    plant_id: str,
    status: str,
    health_score: float,
    telemetry: dict[str, Any],
    updated_at: str,
    timeout: float = 2.0,
) -> bool:
    """Publish one machine-state update. Returns True on success, False on no-op/failure."""
    url = os.environ.get("APPSYNC_URL")
    api_key = os.environ.get("APPSYNC_API_KEY")
    if not url or not api_key:
        logger.warning("appsync_skip_no_env", machine_id=machine_id)
        return False

    body = json.dumps({
        "query": _MUTATION,
        "variables": {"input": {
            "machine_id": machine_id,
            "plant_id": plant_id,
            "status": status,
            "health_score": health_score,
            "updated_at": updated_at,
            "last_telemetry": {
                "vibration_mms": telemetry.get("vibration_mms"),
                "current_amps": telemetry.get("current_amps"),
                "coolant_lmin": telemetry.get("coolant_lmin"),
                "acoustic_db": telemetry.get("acoustic_db"),
            },
        }},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "x-api-key": api_key},
    )
    try:
        urllib.request.urlopen(req, timeout=timeout).read()
        logger.info("appsync_published", machine_id=machine_id, status=status)
        return True
    except Exception as e:
        logger.warning("appsync_publish_failed", machine_id=machine_id, error=str(e)[:200])
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/unit/test_appsync_helper.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add agents/shared/utils/appsync.py tests/unit/test_appsync_helper.py
git commit -m "feat(ingestion): single AppSync machine-state publisher helper"
```

---

## Task 2: Status & health derivation (USER CONTRIBUTION)

A pure function turning the anomaly severity + telemetry into `(status, health_score)` — replacing the hardcoded `RUNNING`/`1.0`.

> **Learning-mode note — this is yours to shape.** The mapping from telemetry to a 0.0–1.0 health score is a genuine domain judgment with multiple valid approaches (linear distance-from-threshold? worst-channel? weighted blend?). I've written the test + signature + the unambiguous status mapping; **you implement the `_telemetry_health` body** (~5–8 lines). Trade-offs to weigh: a simple worst-channel score is explainable on camera; a weighted blend is smoother but harder to justify. Keep it monotonic (worse telemetry → lower score) and clamped to [0,1].

**Files:**
- Create: `agents/shared/utils/health.py`
- Test: `tests/unit/test_health.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_health.py
from agents.shared.utils.health import derive_status_health


def test_critical_severity_is_fault_and_low_health():
    status, health = derive_status_health("CRITICAL", {
        "vibration_mms": 9.5, "current_amps": 20, "coolant_lmin": 12, "acoustic_db": 80})
    assert status == "FAULT"
    assert 0.0 <= health <= 0.3

def test_high_severity_is_warning():
    status, health = derive_status_health("HIGH", {
        "vibration_mms": 8.6, "current_amps": 20, "coolant_lmin": 45, "acoustic_db": 80})
    assert status == "MAINTENANCE"
    assert 0.3 <= health <= 0.7

def test_no_anomaly_is_running_high_health():
    status, health = derive_status_health(None, {
        "vibration_mms": 3.4, "current_amps": 18, "coolant_lmin": 45, "acoustic_db": 78})
    assert status == "RUNNING"
    assert health >= 0.85

def test_health_is_clamped():
    _, health = derive_status_health(None, {
        "vibration_mms": 0, "current_amps": 0, "coolant_lmin": 50, "acoustic_db": 70})
    assert 0.0 <= health <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/unit/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement (status mapping given; health body is the user contribution)**

```python
# agents/shared/utils/health.py
"""Derive dashboard machine status + health from telemetry and anomaly severity."""
from typing import Any, Optional

# Normal-operation reference points for titanium milling (see constants.py).
_NOMINAL = {"vibration_mms": 3.5, "current_amps": 18.0, "coolant_lmin": 45.0, "acoustic_db": 78.0}
_ANOMALY = {"vibration_mms": 8.0, "current_amps": 35.0, "coolant_lmin": 30.0, "acoustic_db": 95.0}

_STATUS_BY_SEVERITY = {"CRITICAL": "FAULT", "HIGH": "MAINTENANCE", "MEDIUM": "MAINTENANCE"}


def derive_status_health(severity: Optional[str], telemetry: dict[str, Any]) -> tuple[str, float]:
    """Map (severity, telemetry) → (status, health_score 0..1)."""
    status = _STATUS_BY_SEVERITY.get(severity or "", "RUNNING")
    health = _telemetry_health(telemetry)
    # Floor health for explicit anomalies so the badge matches the status.
    if severity == "CRITICAL":
        health = min(health, 0.2)
    elif severity in ("HIGH", "MEDIUM"):
        health = min(health, 0.6)
    return status, round(max(0.0, min(1.0, health)), 3)


def _telemetry_health(telemetry: dict[str, Any]) -> float:
    """TODO(you): return a 0..1 health score from telemetry.

    Suggested approach (worst-channel distance): for each channel compute how
    far the value has moved from _NOMINAL toward _ANOMALY (0 = nominal, 1 = at
    anomaly threshold), take the worst channel, and return 1 - worst.
    Note coolant is inverted (lower is worse). ~5-8 lines. Keep it monotonic + clamped.
    """
    raise NotImplementedError("Implement the telemetry→health score")
```

- [ ] **Step 4: Run tests to verify they pass after your implementation**

Run: `PYTHONPATH=. pytest tests/unit/test_health.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agents/shared/utils/health.py tests/unit/test_health.py
git commit -m "feat(ingestion): derive real machine status/health from telemetry"
```

---

## Task 3: Thread real severity into the AppSync push

Make the manager pass each machine's worst anomaly severity to `route_data`, and have `route_data` use `derive_status_health` + the shared publisher (deleting the hardcoded `status:"RUNNING", health:1.0` and the inline duplicate `publish_to_appsync`).

**Files:**
- Modify: `agents/iot_ingestion/manager/handler.py:117-127`
- Modify: `agents/iot_ingestion/workers/data_router.py:128-226`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_iot_ingestion.py  (add this test)
from unittest.mock import patch
from agents.iot_ingestion.workers.data_router import route_data
from agents.shared.models.sensor import SensorReading

def _reading(coolant):
    return SensorReading(
        reading_id="ING-x", machine_id="CNC-AERO-01",
        timestamp="2026-05-31T10:00:00Z",
        telemetry={"vibration_mms": 9.1, "current_amps": 20.0,
                   "coolant_lmin": coolant, "acoustic_db": 80.0},
        metadata={"part_id": "P", "material": "Ti-6Al-4V", "spindle_rpm": 8400},
    )

def test_route_data_pushes_real_status(monkeypatch):
    sent = {}
    def fake_pub(**kw): sent.update(kw); return True
    with patch("agents.iot_ingestion.workers.data_router.write_to_timestream"), \
         patch("agents.iot_ingestion.workers.data_router.update_machine_state"), \
         patch("agents.iot_ingestion.workers.data_router.publish_machine_state", fake_pub):
        # severity map: machine is CRITICAL (compound: vib>8 AND coolant<30)
        route_data([_reading(12.0)], "PLANT-001", severity_by_machine={"CNC-AERO-01": "CRITICAL"})
    assert sent["status"] == "FAULT"
    assert sent["health_score"] <= 0.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/unit/test_iot_ingestion.py::test_route_data_pushes_real_status -v`
Expected: FAIL (`route_data() got an unexpected keyword argument 'severity_by_machine'`)

- [ ] **Step 3: Rewrite `route_data` + inline publisher in `data_router.py`**

Replace the existing `route_data` (lines 128-148) and the inline `publish_to_appsync` (lines 151-226) with:

```python
from agents.shared.utils.appsync import publish_machine_state

def route_data(
    readings: list[SensorReading],
    plant_id: str,
    severity_by_machine: dict[str, str] | None = None,
) -> None:
    """Route validated readings to Timestream + DynamoDB, then push real state to AppSync."""
    severity_by_machine = severity_by_machine or {}
    try:
        write_to_timestream(readings, plant_id)
    except Exception as e:
        logger.warning("timestream_write_skipped", error=str(e)[:200])
    update_machine_state(readings, plant_id)

    # Latest reading per machine → derive real status/health → push.
    from agents.shared.utils.health import derive_status_health
    latest: dict[str, SensorReading] = {}
    for r in readings:
        cur = latest.get(r.machine_id)
        if cur is None or r.timestamp > cur.timestamp:
            latest[r.machine_id] = r
    for machine_id, r in latest.items():
        tel = r.telemetry.model_dump()
        status, health = derive_status_health(severity_by_machine.get(machine_id), tel)
        publish_machine_state(
            machine_id=machine_id, plant_id=plant_id,
            status=status, health_score=health,
            telemetry=tel, updated_at=r.timestamp,
        )
```

- [ ] **Step 4: Update the manager to collect + pass severities**

In `agents/iot_ingestion/manager/handler.py`, change the loop (lines 117-127) to record the worst severity per machine and pass it:

```python
        valid_readings.append(reading)
        records_processed += 1

        anomaly = detect_anomalies(reading, ingestion_id)
        if anomaly:
            anomaly_events.append(anomaly.model_dump())
            # Keep the highest-severity per machine (CRITICAL > HIGH).
            prev = severity_by_machine.get(reading.machine_id)
            if prev != "CRITICAL":
                severity_by_machine[reading.machine_id] = anomaly.severity

    # Route valid data to storage (Timestream + DynamoDB + AppSync push)
    if valid_readings:
        route_data(valid_readings, plant_id, severity_by_machine)
```

Add `severity_by_machine: dict[str, str] = {}` alongside the other accumulators (near line 104).

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=. pytest tests/unit/test_iot_ingestion.py -v`
Expected: PASS (existing tests + the new one)

- [ ] **Step 6: Commit**

```bash
git add agents/iot_ingestion/workers/data_router.py agents/iot_ingestion/manager/handler.py tests/unit/test_iot_ingestion.py
git commit -m "feat(ingestion): push real status/health to AppSync (drop hardcoded RUNNING/1.0)"
```

---

## Task 4: Reconcile the Digital Twin publisher

Point `dashboard_worker.publish_to_appsync` at the shared helper so there's one publisher and one env convention.

**Files:**
- Modify: `agents/digital_twin/workers/dashboard_worker.py`

- [ ] **Step 1: Replace the body of `publish_to_appsync` to delegate**

```python
from agents.shared.utils.appsync import publish_machine_state

def publish_to_appsync(plant_id, machine_id, state_update, client=None, api_url=None) -> bool:
    """Delegate to the shared publisher (kept for the manager's existing call signature)."""
    return publish_machine_state(
        machine_id=machine_id,
        plant_id=plant_id,
        status=state_update.get("status", "RUNNING"),
        health_score=float(state_update.get("health_score", 1.0)),
        telemetry=state_update.get("last_telemetry", {}),
        updated_at=state_update.get("updated_at", ""),
    )
```

- [ ] **Step 2: Run digital twin tests**

Run: `PYTHONPATH=. pytest tests/unit/test_digital_twin.py -v`
Expected: PASS (adjust the test's patch target to `agents.digital_twin.workers.dashboard_worker.publish_machine_state` if it asserts on the publisher)

- [ ] **Step 3: Commit**

```bash
git add agents/digital_twin/workers/dashboard_worker.py tests/unit/test_digital_twin.py
git commit -m "refactor(twin): use shared AppSync publisher"
```

---

## Task 5: Re-add Timestream (DB + tables)

Timestream was removed for the workshop SCP. Re-add it for the unblocked personal account so energy + history are real.

**Files:**
- Modify: `infrastructure/cdk/stacks/storage_stack.py:218-219`

- [ ] **Step 1: Replace the "Timestream removed" comment with the construct**

```python
        # ---------------------------------------------------------------
        # Timestream — real-time sensor + energy time-series (personal acct)
        # ---------------------------------------------------------------
        from aws_cdk import aws_timestream as timestream

        ts_db = timestream.CfnDatabase(self, "SensorsDb", database_name="FactoryMindSensors")
        for tbl in ("SensorReadings", "EnergyReadings"):
            t = timestream.CfnTable(
                self, f"Ts{tbl}", database_name="FactoryMindSensors", table_name=tbl,
                retention_properties={
                    "MemoryStoreRetentionPeriodInHours": "24",
                    "MagneticStoreRetentionPeriodInDays": "30",
                },
            )
            t.add_dependency(ts_db)
        self.timestream_db_name = "FactoryMindSensors"
```

- [ ] **Step 2: Verify synth**

Run: `cd infrastructure/cdk && cdk synth FactoryMindStorage --context region=us-east-1 > /dev/null && echo OK`
Expected: `OK` (no synth errors)

- [ ] **Step 3: Commit**

```bash
git add infrastructure/cdk/stacks/storage_stack.py
git commit -m "feat(infra): re-add Timestream DB + SensorReadings/EnergyReadings tables"
```

---

## Task 6: Grant Timestream access to the agents

**Files:**
- Modify: `infrastructure/cdk/stacks/compute_stack.py` (ingestion grants near line 262-269; add sustainability read)

- [ ] **Step 1: Add Timestream IAM to ingestion + sustainability**

After the ingestion table grants (line 268), add:

```python
        from aws_cdk import aws_iam as iam
        ts_write = iam.PolicyStatement(
            actions=["timestream:WriteRecords", "timestream:DescribeEndpoints"],
            resources=["*"],  # DescribeEndpoints requires * ; WriteRecords scoped at table level below
        )
        self.iot_ingestion_fn.add_to_role_policy(ts_write)
        self.sustainability_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["timestream:Select", "timestream:DescribeEndpoints"], resources=["*"],
        ))
```

- [ ] **Step 2: Verify synth**

Run: `cd infrastructure/cdk && cdk synth FactoryMindCompute --context region=us-east-1 > /dev/null && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add infrastructure/cdk/stacks/compute_stack.py
git commit -m "feat(infra): grant Timestream write/read to ingestion + sustainability"
```

---

## Task 7: Real energy query

Replace the placeholder in `energy_monitor.py` with a real Timestream query + real DynamoDB baselines.

**Files:**
- Modify: `agents/sustainability/workers/energy_monitor.py:61-91`
- Test: `tests/unit/test_energy_monitor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_energy_monitor.py
from unittest.mock import MagicMock
from agents.sustainability.workers.energy_monitor import _query_energy_readings

def test_query_parses_timestream_rows():
    client = MagicMock()
    client.query.return_value = {
        "Rows": [
            {"Data": [{"ScalarValue": "CNC-AERO-01"}, {"ScalarValue": "14.2"}]},
            {"Data": [{"ScalarValue": "CNC-AERO-02"}, {"ScalarValue": "9.7"}]},
        ],
        "ColumnInfo": [{"Name": "machine_id"}, {"Name": "power_kwh"}],
    }
    rows = _query_energy_readings("PLANT-001", None, client)
    assert {"machine_id": "CNC-AERO-01", "power_kwh": 14.2} in rows
    assert len(rows) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/unit/test_energy_monitor.py -v`
Expected: FAIL (returns the hardcoded `[{"machine_id":"CNC-AERO-01","power_kwh":12.5}]`)

- [ ] **Step 3: Implement the real parse**

Replace lines 71-81 (`try:` block) with:

```python
    try:
        query = (
            'SELECT machine_id, AVG(measure_value::double) AS power_kwh '
            'FROM "FactoryMindSensors"."EnergyReadings" '
            "WHERE time > ago(1h) GROUP BY machine_id"
        )
        response = client.query(QueryString=query)
        rows: list[dict] = []
        for row in response.get("Rows", []):
            data = row.get("Data", [])
            if len(data) >= 2 and "ScalarValue" in data[0] and "ScalarValue" in data[1]:
                rows.append({
                    "machine_id": data[0]["ScalarValue"],
                    "power_kwh": float(data[1]["ScalarValue"]),
                })
        return rows
    except Exception as e:
        import structlog
        structlog.get_logger().warning("energy_query_failed", error=str(e)[:200])
        return []
```

And replace `_get_baselines` (lines 84-91) to read the real table:

```python
def _get_baselines(plant_id, machine_id, table):
    if table is None:
        from agents.shared.utils.aws_clients import get_dynamodb_resource
        table = get_dynamodb_resource().Table("FactoryMind_EnergyBaselines")
    try:
        items = table.scan().get("Items", [])
        return {it["machine_id"]: it for it in items}
    except Exception as e:
        import structlog
        structlog.get_logger().warning("baseline_query_failed", error=str(e)[:200])
        return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/unit/test_energy_monitor.py tests/unit/test_sustainability.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/sustainability/workers/energy_monitor.py tests/unit/test_energy_monitor.py
git commit -m "feat(sustainability): real Timestream energy query + DynamoDB baselines"
```

---

## Task 8: Hygiene — kill the silent except

**Files:**
- Modify: `agents/iot_ingestion/workers/anomaly_detector.py:98-107`

- [ ] **Step 1: Replace the silent `except: pass`**

```python
    if publish:
        try:
            publish_event(
                source=IOT_EVENT_SOURCE,
                detail_type="AnomalyDetected",
                detail=anomaly_event.model_dump(),
            )
        except Exception as e:
            import structlog
            structlog.get_logger().error(
                "anomaly_publish_failed",
                machine_id=reading.machine_id,
                alert_type=alert_type,
                error=str(e)[:200],
            )
```

- [ ] **Step 2: Run ingestion tests**

Run: `PYTHONPATH=. pytest tests/unit/test_iot_ingestion.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add agents/iot_ingestion/workers/anomaly_detector.py
git commit -m "fix(ingestion): log EventBridge publish failures instead of swallowing"
```

---

## Task 9: Deploy script — inject AppSync env onto ingestion Lambda

The ingestion Lambda's `APPSYNC_URL`/`APPSYNC_API_KEY` default to `""`. After the ML stack deploys, patch them (mirroring the existing Redis patch).

**Files:**
- Modify: `scripts/deploy.ps1` (after the Redis patch block, ~line 106)

- [ ] **Step 1: Add the post-deploy AppSync env patch**

```powershell
# Step 6b - patch IoT Ingestion Lambda with AppSync endpoint (for dashboard push)
Write-Host "[6b] Patching iot-ingestion Lambda with AppSync URL/key..."
$AppsyncUrl = aws cloudformation describe-stacks --stack-name FactoryMindML --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='AppSyncEndpoint'].OutputValue" --output text
$AppsyncKey = aws cloudformation describe-stacks --stack-name FactoryMindML --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='AppSyncApiKey'].OutputValue" --output text
if ($AppsyncUrl -and $AppsyncUrl -ne "None") {
    $envVars = "Variables={EVENT_BUS_NAME=factorymind-bus,PLANT_ID=PLANT-001,APPSYNC_URL=$AppsyncUrl,APPSYNC_API_KEY=$AppsyncKey,POWERTOOLS_SERVICE_NAME=factorymind-iot-ingestion-manager,POWERTOOLS_METRICS_NAMESPACE=FactoryMind,LOG_LEVEL=INFO}"
    aws lambda update-function-configuration --function-name factorymind-iot-ingestion-manager `
        --environment $envVars --region $Region | Out-Null
    Write-Host "  Patched iot-ingestion -> APPSYNC_URL set"
} else { Write-Warning "  AppSync endpoint not resolved; dashboard push will be a no-op." }
Write-Host ""
```

- [ ] **Step 2: Verify (manual at deploy time)** — after a deploy, confirm:

Run: `aws lambda get-function-configuration --function-name factorymind-iot-ingestion-manager --region us-east-1 --query 'Environment.Variables.APPSYNC_URL'`
Expected: the real `https://...appsync-api...` URL (not empty)

- [ ] **Step 3: Commit**

```bash
git add scripts/deploy.ps1
git commit -m "feat(deploy): inject AppSync URL/key onto ingestion Lambda post-ML-deploy"
```

---

## Task 10: Dashboard honesty — real fields, LIVE/NO-DATA, no silent mock

**Files:**
- Modify: `dashboard/lib/useLiveMachines.ts`

- [ ] **Step 1: Remove the synthesized display fields in `toMachine`**

In `toMachine` (lines 44-78), replace the synthesized `load`/`energy`/`temp`/`rpm` derivations with real-or-null and drop the predicted-hours guess. Keep only fields the backend actually provides:

```typescript
  const vibration = tel?.vibration_mms ?? fallback.vibration;
  const current = tel?.current_amps ?? null;
  const coolant = tel?.coolant_lmin ?? null;
  // Real fields only — no synthesis. Unknown values render as "—" in the UI.
  return {
    id: s.machine_id,
    name, line,
    status: statusToUI(s.status),
    health,
    vibration,
    current,
    coolant,
    acoustic: tel?.acoustic_db ?? null,
    position: gridPosition(idx),
  } as Machine;
```

(Update the `Machine` type in `dashboard/lib/mockData.ts` to make `temp/rpm/load/energy` optional and add `current/coolant/acoustic`; render `—` for nullish in the consuming tiles.)

- [ ] **Step 2: Remove the silent 4s mock fallback**

Delete the entire `useEffect` block at lines 207-225 (the `// Demo fallback` effect that swaps in `initialMachines`). The fleet stays on real placeholders until real data lands.

- [ ] **Step 3: Surface a real LIVE / NO-DATA indicator**

The hook already exposes `live` and `error`. In `DashboardLayout.tsx`, replace the hardcoded "Live · 247 sensors / Edge latency 7ms" with a badge driven by `live`:

```tsx
// in DashboardLayout, consume useLiveMachines()
const { live, machines } = useLiveMachines();
const running = machines.filter(m => m.status === "running").length;
// ...
<span>{live ? `LIVE · ${running}/${machines.length} machines` : "NO DATA · awaiting telemetry"}</span>
```

- [ ] **Step 4: Build the dashboard to verify it compiles**

Run: `cd dashboard && npm install && npm run build`
Expected: build succeeds (no TS errors)

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/useLiveMachines.ts dashboard/lib/mockData.ts dashboard/components/DashboardLayout.tsx
git commit -m "feat(dashboard): show real fields only, LIVE/NO-DATA badge, drop silent mock fallback"
```

---

## Task 11: Full deploy + live smoke test (Phase 1 gate)

**Files:** none (operational).

- [ ] **Step 1: Train model artifacts (deploy needs them)**

```bash
PYTHONPATH=. python models/edge/train_edge_classifier.py
PYTHONPATH=. python models/lstm/train_lstm_maintenance.py && bash models/lstm/package_lstm.sh
```
Expected: `models/edge/*.onnx` and `models/lstm/model.tar.gz` exist.

- [ ] **Step 2: Deploy**

```powershell
.\scripts\deploy.ps1 -Region us-east-1
```
Expected: all 6 stacks deploy; Redis + AppSync env patches print success; dashboard URL printed.

- [ ] **Step 3: Run the simulator (real telemetry)**

```bash
ENDPOINT=$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --region us-east-1 --query endpointAddress --output text)
PYTHONPATH=. python scripts/simulate_aerospace_cnc.py --machine-id CNC-AERO-01 --mode optimal --publish --endpoint $ENDPOINT --duration 60
```

- [ ] **Step 4: Verify the push fires**

```bash
aws logs tail /aws/lambda/factorymind-iot-ingestion-manager --follow --region us-east-1
```
Expected: `appsync_published` log lines with `machine_id=CNC-AERO-01`.

- [ ] **Step 5: Verify on the dashboard (the Phase 1 gate)**

Open the CloudFront URL. Expected:
- CNC-AERO-01 shows real vibration/current/coolant updating live; badge reads **LIVE**.
- Stop the simulator → within a cycle the badge flips toward **NO DATA** (no silent mock swap-in).
- Sustainability page shows real energy (not a flat 12.5).

- [ ] **Step 6: Tag the milestone**

```bash
git tag phase1-foundation-complete
```

---

## Self-Review Notes
- **Spec coverage:** push wiring (T1/T3/T9), real status/health (T2/T3), reconcile publishers (T1/T4), real energy + Timestream (T5/T6/T7), hygiene (T8), dashboard honesty (T10), deploy+smoke (T11). All Phase 1 spec bullets mapped.
- **User contribution:** Task 2 `_telemetry_health` body (domain judgment, ~5-8 lines).
- **Type consistency:** `publish_machine_state(...)` signature identical across T1/T3/T4; `derive_status_health(severity, telemetry)→(status,health)` used consistently in T2/T3.
