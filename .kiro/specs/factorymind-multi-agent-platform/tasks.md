# Implementation Plan: FactoryMind Multi-Agent Manufacturing Intelligence Platform

## Overview

This plan implements the FactoryMind hierarchical multi-agent manufacturing intelligence platform on AWS. The implementation follows a bottom-up approach: shared models and utilities first, then individual agents (manager + workers), CDK infrastructure, testing, dashboard, and deployment wiring. Each agent is implemented as a Lambda function with Pydantic models, structlog logging, and aws-lambda-powertools observability.

**Domain Focus**: Aerospace CNC Titanium Milling (Ti-6Al-4V) — monitoring spindle vibration, motor current, coolant flow, and acoustic emission to prevent catastrophic tool failure on high-value titanium parts.

## Tasks

- [ ] 1. Project scaffolding and shared foundations
  - [x] 1.1 Create project directory structure and configuration files
    - Create the full directory tree per conventions: `agents/`, `infrastructure/cdk/`, `models/`, `dashboard/`, `tests/`, `scripts/`
    - Create `pyproject.toml` with Python 3.11+ target, dependencies: pydantic, boto3, structlog, aws-lambda-powertools, langgraph, pytest, moto, numpy
    - Create `requirements.txt` and `requirements-dev.txt`
    - Create `.gitignore`, `README.md`

  - [x] 1.2 Implement shared Pydantic data models (Aerospace CNC Telemetry)
    - Create `agents/shared/models/sensor.py` with `SensorReading` model matching aerospace CNC payload:
      - Fields: reading_id (ING-prefix), machine_id, timestamp, telemetry (vibration_mms, current_amps, coolant_lmin, acoustic_db), metadata (part_id, material, spindle_rpm)
      - Validators: vibration_mms 0-20 mm/s, current_amps 0-50 A, coolant_lmin 0-80 L/min, acoustic_db 0-120 dB, staleness >60s rejection
    - Create `agents/shared/models/machine.py` with `MachineStateRecord` model for CNC machines (machine_type: CNC_MILL)
    - Create `agents/shared/models/events.py` with `AlertSummary`, `AnomalyEvent`, EventBridge event envelope models
    - Create `agents/shared/models/work_order.py` with `WorkOrderRecord` model including status transition and priority validation
    - Create `agents/shared/models/quality.py` with `DefectType` enum, `BoundingBox`, `Detection`, `QualityResultRecord` models
    - Create `agents/shared/models/edge.py` with `EdgeClassification` enum, `EdgeResultRecord` model, aerospace CNC thresholds
    - Create `agents/shared/models/sustainability.py` with `EnergyMetrics`, `SustainabilityKPI` models
    - Create `agents/shared/models/twin.py` with `MachineState`, `TwinSyncInput`, `TwinSyncOutput` models

  - [x] 1.3 Implement shared utilities and base classes
    - Create `agents/shared/utils/aws_clients.py` with boto3 client factory (DynamoDB, Timestream, S3, EventBridge, SQS, Redis)
    - Create `agents/shared/utils/eventbridge.py` with helper to publish structured events to `factorymind-bus`
    - Create `agents/shared/utils/id_generator.py` with prefix-based UUID generator (BRN-, ING-, QCR-, PRD-, SUSR-, TWNR-, EDGR-, WO-)
    - Create `agents/shared/utils/logging.py` with structlog configuration and aws-lambda-powertools integration
    - Create `agents/shared/utils/retry.py` with exponential backoff decorator (1 retry for all agents except Edge AI)
    - Create `agents/shared/constants.py` with:
      - Plant config (PLANT-001, CNC-AERO-01 through CNC-AERO-50)
      - Titanium milling thresholds: vibration NORMAL 2.0-5.0 mm/s, ANOMALY >8.0 mm/s; current NORMAL 15.0-25.0 A, ANOMALY >35.0 A; coolant NORMAL 40.0-50.0 L/min, ANOMALY <30.0 L/min; acoustic NORMAL 75-85 dB, ANOMALY >95 dB
      - Conversion factors (0.82 kg CO2/kWh, Rs 7.50/kWh, Redis TTL 300s)
      - Edge AI compound rule: vibration >8.0 AND coolant <30.0 = IMMEDIATE SPINDLE STOP

  - [x] 1.4 Write unit tests for shared models and utilities
    - Test sensor reading validation (titanium milling ranges, staleness, pattern matching)
    - Test machine state transitions (valid/invalid)
    - Test work order status transitions and priority constraints
    - Test ID generation with correct prefixes
    - Test EventBridge event envelope construction
    - Test aerospace CNC threshold constants

- [ ] 2. IoT Ingestion Manager agent (Aerospace CNC Telemetry)
  - [x] 2.1 Implement IoT Ingestion Manager handler and workers
    - Create `agents/iot-ingestion/manager/handler.py` with Lambda handler accepting Kinesis batch events (up to 100 records)
    - Implement `IngestionBatchInput` and `IngestionOutput` models matching aerospace CNC payload structure
    - Create `agents/iot-ingestion/workers/stream_validator.py` — validates each SensorReading against titanium milling physical ranges:
      - vibration_mms: 0-20 mm/s (reject outliers)
      - current_amps: 0-50 A (reject outliers)
      - coolant_lmin: 0-80 L/min (reject outliers)
      - acoustic_db: 0-120 dB (reject outliers)
      - Staleness: >60s rejection
    - Create `agents/iot-ingestion/workers/anomaly_detector.py` — threshold-based anomaly detection for titanium milling:
      - vibration_mms > 8.0 → HIGH severity
      - current_amps > 35.0 → HIGH severity
      - coolant_lmin < 30.0 → CRITICAL severity (tool damage risk)
      - acoustic_db > 95 → HIGH severity
      - Compound: vibration >8.0 AND coolant <30.0 → CRITICAL (immediate spindle stop)
    - Create `agents/iot-ingestion/workers/data_router.py` — writes validated readings to Timestream and updates DynamoDB MachineState
    - Wire manager to orchestrate: validate → detect anomalies → route data → publish events
    - Ensure processing_time_ms < 500ms tracked and returned in output
    - MQTT topic: `factory/aerospace/cnc/telemetry`

  - [x] 2.2 Write unit tests for IoT Ingestion Manager
    - Test batch validation with mixed valid/invalid readings
    - Test stale timestamp rejection (>60s)
    - Test each sensor range boundary (vibration_mms, current_amps, coolant_lmin, acoustic_db)
    - Test anomaly detection: vibration >8.0 mm/s triggers HIGH
    - Test anomaly detection: coolant <30.0 L/min triggers CRITICAL
    - Test compound rule: vibration >8.0 AND coolant <30.0 triggers CRITICAL with IMMEDIATE_SPINDLE_STOP
    - Test records_processed + records_rejected = total batch size invariant
    - Test AnomalyEvent construction and EventBridge publishing
    - Mock Timestream writes and DynamoDB updates

- [ ] 3. Edge AI Manager agent (Real-Time CNC Protection)
  - [x] 3.1 Implement Edge AI Manager handler and workers
    - Create `agents/edge-ai/manager/handler.py` with Lambda handler triggered by IoT Core rule on `factory/aerospace/cnc/telemetry`
    - Implement `EdgeInferenceInput` and `EdgeInferenceOutput` models with CNC telemetry fields
    - Create `agents/edge-ai/workers/edge_cache.py` — Redis sliding window management (last 10 readings per machine, key: `edge:window:{machine_id}`)
    - Create `agents/edge-ai/workers/onnx_worker.py` — ONNX Runtime inference loading model from Lambda Layer, must complete in <10ms
    - Create `agents/edge-ai/workers/edge_classifier.py` — classifies as NORMAL/WARNING/ANOMALY based on:
      - NORMAL: all values within normal ranges (vibration 2.0-5.0, current 15.0-25.0, coolant 40.0-50.0, acoustic 75-85)
      - WARNING: any single value in warning zone (vibration 5.0-8.0, current 25.0-35.0, coolant 30.0-40.0, acoustic 85-95)
      - ANOMALY: any value in critical zone OR compound rule (vibration >8.0 AND coolant <30.0)
    - Create `agents/edge-ai/workers/cloud_escalator.py` — fire-and-forget EventBridge publish for ANOMALY with EDGR- alert, no retry, no wait
    - Wire manager: get sliding window → inference → classify → escalate if ANOMALY → write to DynamoDB EdgeResults
    - Ensure inference_time_ms < 10ms and no retry logic anywhere

  - [x] 3.2 Write unit tests for Edge AI Manager
    - Test sliding window retrieval and update in Redis
    - Test ONNX inference mock with timing assertion (<10ms)
    - Test classification: all normal values → NORMAL
    - Test classification: vibration 6.5 mm/s → WARNING
    - Test classification: vibration 9.0 mm/s → ANOMALY
    - Test classification: coolant 25.0 L/min → ANOMALY (CRITICAL)
    - Test compound rule: vibration >8.0 AND coolant <30.0 → ANOMALY + IMMEDIATE_SPINDLE_STOP
    - Test fire-and-forget escalation (no retry, no wait)
    - Test that NORMAL classification does not trigger escalation
    - Test DynamoDB EdgeResults write

- [ ] 4. Aerospace CNC Simulator Script
  - [x] 4.1 Create `scripts/simulate_aerospace_cnc.py`
    - Initialize AWS IoT Client using AWSIoTPythonSDK with certificates
    - Implement three simulation modes via state machine:
      - MODE_OPTIMAL: Generate normal Gaussian noise around baseline values (vibration ~3.4 mm/s, current ~18.2 A, coolant ~45.1 L/min, acoustic ~78.5 dB)
      - MODE_TOOL_WEAR: Over 5-minute loop, steadily increase current_amps by +0.5A/hour and vibration_mms by +0.3 mm/s/hour (tests Predictive Maintenance trend detection via Timestream)
      - MODE_CATASTROPHIC_FAILURE: Instantly drop coolant to 10 L/min and spike vibration to 12 mm/s (tests Edge AI immediate anomaly response)
    - Publish at 1 Hz (time.sleep(1)) to MQTT topic `factory/aerospace/cnc/telemetry`
    - Payload structure matches the SensorReading model:
      ```json
      {
        "reading_id": "ING-<uuid>",
        "machine_id": "CNC-AERO-01",
        "timestamp": "2026-05-06T14:30:15Z",
        "telemetry": {
          "vibration_mms": 3.4,
          "current_amps": 18.2,
          "coolant_lmin": 45.1,
          "acoustic_db": 78.5
        },
        "metadata": {
          "part_id": "FUS-BRACKET-992",
          "material": "Ti-6Al-4V",
          "spindle_rpm": 3500
        }
      }
      ```
    - Support CLI args: --machine-id, --mode (optimal|tool_wear|catastrophic), --duration-seconds
    - Use numpy.random.normal() for realistic sensor noise generation

- [ ] 5. Checkpoint - Validate ingestion, edge, and simulator
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Quality Vision Manager agent
  - [x] 6.1 Implement Quality Vision Manager handler and workers
    - Create `agents/quality-vision/manager/handler.py` with Lambda handler triggered by S3 event notification
    - Implement `QualityInspectionInput` and `QualityInspectionOutput` models
    - Create `agents/quality-vision/workers/vision_preprocessor.py` — resize and normalize image for model input
    - Create `agents/quality-vision/workers/yolov8_worker.py` — invoke SageMaker endpoint `factorymind-yolov8-quality`, return detections with confidence scores
    - Create `agents/quality-vision/workers/rekognition_worker.py` — fallback detector using Rekognition DetectLabels when YOLOv8 confidence < 0.75
    - Create `agents/quality-vision/workers/defect_analyser.py` — classify defects (SCRATCH, DENT, CRACK, DISCOLORATION, MISALIGNMENT, NO_DEFECT), determine PASS/FAIL/REVIEW verdict
    - Create `agents/quality-vision/workers/qc_report_generator.py` — generate inspection report, write to DynamoDB QualityResults, publish event
    - Wire manager: preprocess → YOLOv8 → (fallback to Rekognition if confidence < 0.75) → analyse → generate report
    - Ensure processing_time_ms < 3000ms

  - [x] 6.2 Write unit tests for Quality Vision Manager
    - Test image preprocessing pipeline
    - Test YOLOv8 confidence threshold (>=0.75 accepted, <0.75 triggers fallback)
    - Test Rekognition fallback invocation
    - Test defect classification for each DefectType
    - Test verdict determination (PASS/FAIL/REVIEW)
    - Test threshold_exceeded flag when batch defect rate exceeds threshold
    - Test DynamoDB write and EventBridge publish

- [ ] 7. Predictive Maintenance Manager agent (CNC Tool Wear Trending)
  - [x] 7.1 Implement Predictive Maintenance Manager handler and workers
    - Create `agents/predictive-maintenance/manager/handler.py` with Lambda handler
    - Implement `PredictiveMaintenanceInput` and `PredictiveMaintenanceOutput` models
    - Create `agents/predictive-maintenance/workers/timestream_worker.py` — query 72-hour rolling sensor window from Timestream for affected CNC machine; detect gradual trends (e.g., current increasing +0.5A/hour)
    - Create `agents/predictive-maintenance/workers/lstm_worker.py` — invoke SageMaker endpoint `factorymind-lstm-maintenance`, return MaintenancePrediction for tool wear/failure
    - Create `agents/predictive-maintenance/workers/lookout_worker.py` — invoke Lookout for Equipment model `factorymind-machine-anomaly-model`, return MaintenancePrediction
    - Create `agents/predictive-maintenance/workers/scheduler_worker.py` — apply consensus rule (BOTH LSTM + Lookout must agree for CRITICAL; single model CRITICAL → HIGH); schedule end-of-shift tool replacement
    - Create `agents/predictive-maintenance/workers/workorder_worker.py` — generate WorkOrder with sequential WO- ID (e.g., "Replace end-mill on CNC-AERO-01 before next shift"), queue to SQS
    - Wire manager: query history → parallel LSTM + Lookout → consensus → generate work order if HIGH/CRITICAL → publish event
    - Ensure processing_time_ms < 3000ms

  - [x] 7.2 Write unit tests for Predictive Maintenance Manager
    - Test 72-hour Timestream query construction for CNC telemetry
    - Test trend detection (current increasing steadily over 12 hours)
    - Test LSTM prediction parsing
    - Test Lookout prediction parsing
    - Test consensus rule: both CRITICAL → consensus_reached=true, final_severity=CRITICAL
    - Test consensus rule: one CRITICAL → consensus_reached=false, final_severity=HIGH
    - Test work order generation with correct fields and predicted_by="consensus" for CRITICAL
    - Test SQS queue publish
    - Test no work order generated for MEDIUM/LOW

- [ ] 8. Sustainability Manager agent
  - [x] 8.1 Implement Sustainability Manager handler and workers
    - Create `agents/sustainability/manager/handler.py` with Lambda handler
    - Implement `SustainabilityInput` and `SustainabilityOutput` models
    - Create `agents/sustainability/workers/energy_monitor.py` — query Timestream EnergyReadings, compare against DynamoDB EnergyBaselines, calculate deviation percentage
    - Create `agents/sustainability/workers/kpi_calculator.py` — compute energy_efficiency (0.0–1.0), carbon_footprint_kg, waste_index (0.0–1.0), overall_score (0–100)
    - Create `agents/sustainability/workers/waste_detector.py` — detect idle CNC machines consuming power (spindle running with no part loaded)
    - Create `agents/sustainability/workers/carbon_calculator.py` — apply 0.82 kg CO2/kWh conversion, Rs 7.50/kWh cost calculation
    - Create `agents/sustainability/workers/genai_recommender.py` — invoke Bedrock Claude 3.5 with Knowledge Base context for optimization recommendations
    - Wire manager: monitor energy → calculate KPIs → detect waste → compute carbon → generate recommendations
    - Ensure processing_time_ms < 5000ms

  - [x] 8.2 Write unit tests for Sustainability Manager
    - Test energy deviation calculation against baselines
    - Test carbon footprint calculation (0.82 kg CO2/kWh)
    - Test energy cost calculation (Rs 7.50/kWh)
    - Test KPI computation with known inputs
    - Test waste detection logic (idle CNC with spindle power draw)
    - Test GenAI recommender Bedrock invocation mock
    - Test weekly report SES email trigger

- [ ] 9. Checkpoint - Validate domain agents
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Digital Twin Manager agent
  - [x] 10.1 Implement Digital Twin Manager handler and workers
    - Create `agents/digital-twin/manager/handler.py` with Lambda handler
    - Implement `TwinSyncInput` and `TwinSyncOutput` models
    - Create `agents/digital-twin/workers/twinmaker_worker.py` — sync state to IoT TwinMaker workspace `factorymind-workspace`
    - Create `agents/digital-twin/workers/dashboard_worker.py` — publish state change via AppSync `updateMachineState` mutation
    - Create `agents/digital-twin/workers/reconciler_worker.py` — detect Redis/DynamoDB divergence, reconcile using DynamoDB as source of truth
    - Create `agents/digital-twin/workers/snapshot_worker.py` — take historical snapshot to S3 `factorymind-twin-snapshots` on CRITICAL events
    - Wire manager: update Redis (TTL 300s) → persist DynamoDB TwinState → sync TwinMaker → publish AppSync → snapshot if CRITICAL
    - Ensure processing_time_ms < 500ms

  - [x] 10.2 Write unit tests for Digital Twin Manager
    - Test Redis cache update with correct key pattern and TTL
    - Test DynamoDB TwinState persistence
    - Test TwinMaker sync invocation
    - Test AppSync mutation publish
    - Test snapshot taken only on CRITICAL severity
    - Test reconciliation logic (DynamoDB wins on divergence)
    - Test processing time tracking

- [ ] 11. Brain Agent (LangGraph orchestrator)
  - [x] 11.1 Implement Brain Agent LangGraph state machine
    - Create `agents/brain/handler.py` with Lambda handler accepting EventBridge events
    - Implement `BrainInput`, `BrainOutput`, `BrainState` models
    - Create `agents/brain/graph.py` with LangGraph state graph defining nodes: assess_severity → query_machine_history → determine_delegation → invoke_managers → synthesize_recommendation
    - Implement severity assessment logic: analyze CNC telemetry values, detect compound anomalies
    - Implement delegation routing: CRITICAL → Maintenance + Twin + human escalation; HIGH → domain + Twin; MEDIUM → domain only; LOW → log only

  - [x] 11.2 Implement Brain Agent manager invocation tools
    - Create `agents/brain/tools/invoke_iot_ingestion.py` — Lambda invoke wrapper for IoT Ingestion Manager
    - Create `agents/brain/tools/invoke_quality_vision.py` — Lambda invoke wrapper for Quality Vision Manager
    - Create `agents/brain/tools/invoke_predictive_maintenance.py` — Lambda invoke wrapper for Predictive Maintenance Manager
    - Create `agents/brain/tools/invoke_sustainability.py` — Lambda invoke wrapper for Sustainability Manager
    - Create `agents/brain/tools/invoke_digital_twin.py` — Lambda invoke wrapper for Digital Twin Manager
    - Implement parallel invocation for multi-manager delegation
    - Publish BrainDecision event to EventBridge with source `factorymind.brain.decision`
    - Ensure full delegation chain processing_time_ms < 2000ms

  - [x] 11.3 Write unit tests for Brain Agent
    - Test severity assessment for CNC anomalies (compound rule escalation)
    - Test delegation routing for each severity level
    - Test parallel manager invocation
    - Test result synthesis into unified recommendation
    - Test human escalation flag for CRITICAL
    - Test LOW severity logs without delegation
    - Test BrainDecision EventBridge event structure

- [ ] 12. Checkpoint - Validate all agents
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. AWS CDK infrastructure stacks
  - [x] 13.1 Implement CDK app entry point and storage stack
    - Create `infrastructure/cdk/app.py` with CDK app instantiating all stacks
    - Create `infrastructure/cdk/stacks/storage_stack.py` with all DynamoDB tables, S3 buckets, Timestream database, ElastiCache Redis

  - [x] 13.2 Implement CDK IoT and ingestion stack
    - Create `infrastructure/cdk/stacks/iot_stack.py` with IoT Core MQTT rules for `factory/aerospace/cnc/telemetry`, Kinesis streams, Firehose, EventBridge bus, SQS, SNS

  - [ ] 13.3 Implement CDK compute stack
    - Create `infrastructure/cdk/stacks/compute_stack.py` with Lambda functions for each agent, ONNX Lambda Layer, IAM roles, event source mappings

  - [ ] 13.4 Implement CDK ML stack
    - Create `infrastructure/cdk/stacks/ml_stack.py` with SageMaker endpoints, Lookout for Equipment model, AppSync API, IoT TwinMaker workspace

  - [ ] 13.5 Implement CDK monitoring stack
    - Create `infrastructure/cdk/stacks/monitoring_stack.py` with CloudWatch dashboards, alarms for SLA breaches, X-Ray tracing

- [ ] 14. Checkpoint - Validate CDK stacks synthesize
  - Ensure all CDK stacks synthesize without errors (`cdk synth`), ask the user if questions arise.

- [ ] 15. Integration tests
  - [ ] 15.1 Write integration tests for agent delegation chains
    - Create integration tests for IoT ingestion, quality vision, predictive maintenance, digital twin, and brain delegation chains
    - Use moto and localstack fixtures for AWS service mocking

  - [ ] 15.2 Write E2E tests for critical paths
    - Test full CRITICAL alert flow: CNC coolant failure → Edge AI ANOMALY → Brain → Maintenance + Twin → dashboard
    - Test Edge AI compound rule: vibration >8.0 AND coolant <30.0 → IMMEDIATE_SPINDLE_STOP → EventBridge → Brain
    - Test tool wear trending: gradual current increase over 12 hours → Predictive Maintenance → Work Order

- [ ] 16. React dashboard with AppSync subscriptions
  - [ ] 16.1 Set up React dashboard project and AppSync integration
    - Initialize React project with TypeScript, Vite, AWS Amplify
    - Create GraphQL schema, queries, mutations, subscriptions for CNC machine states

  - [ ] 16.2 Implement dashboard pages and components
    - Plant overview with CNC machine status indicators
    - Machine detail with real-time telemetry (vibration, current, coolant, acoustic)
    - Alerts page with severity filtering
    - Maintenance page with work orders
    - Sustainability page with energy KPIs

- [ ] 17. Scripts and deployment utilities
  - [ ] 17.1 Create operational scripts
    - Create `scripts/seed_dummy_data.py` — seed DynamoDB tables with CNC-AERO-01 through CNC-AERO-50 machine specs, Ti-6Al-4V baselines, thresholds
    - Create `scripts/deploy.sh` — orchestrate CDK deploy, Lambda packaging, dashboard build and deploy

  - [ ] 17.2 Wire all components together and validate end-to-end
    - Verify EventBridge rules route events correctly between all agents
    - Verify Kinesis → IoT Ingestion → EventBridge → Brain → Managers flow
    - Verify Edge AI compound rule → EventBridge → Brain escalation path
    - Verify Digital Twin → AppSync → Dashboard subscription path
    - Validate all SLA constraints are met

- [ ] 18. Final checkpoint - Full system validation
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Domain: Aerospace CNC Titanium Milling (Ti-6Al-4V) with real-world sensor parameters
- Sensor parameters: vibration_mms, current_amps, coolant_lmin, acoustic_db (sampled at 1 Hz)
- Critical compound rule: vibration >8.0 mm/s AND coolant <30.0 L/min = IMMEDIATE SPINDLE STOP
- Simulator (`scripts/simulate_aerospace_cnc.py`) operates in 3 modes: OPTIMAL, TOOL_WEAR, CATASTROPHIC_FAILURE
- Tool wear detection: gradual current increase (+0.5A/hour) over 12 hours while vibration trends up
- Python 3.11+ with Pydantic models, structlog, and aws-lambda-powertools used throughout
- All AWS service interactions use boto3 with exponential backoff (except Edge AI which is fire-and-forget)
- Unit tests use moto for AWS mocking; integration tests use LocalStack
- The consensus rule (LSTM + Lookout must agree for CRITICAL) is a core architectural constraint
