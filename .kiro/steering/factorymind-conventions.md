---
inclusion: always
---

# FactoryMind — Coding Conventions & Standards

## Project Structure

```
cts_hackathon_factorymind/
├── agents/
│   ├── brain/                    # Brain Agent (LangGraph orchestrator)
│   │   ├── handler.py
│   │   ├── graph.py              # LangGraph state machine
│   │   └── tools/                # Manager invocation tools
│   ├── iot-ingestion/            # IoT Ingestion Manager
│   │   ├── manager/
│   │   │   └── handler.py
│   │   └── workers/
│   │       ├── stream_validator.py
│   │       ├── anomaly_detector.py
│   │       └── data_router.py
│   ├── quality-vision/           # Quality Vision Manager
│   │   ├── manager/
│   │   │   └── handler.py
│   │   └── workers/
│   │       ├── vision_preprocessor.py
│   │       ├── yolov8_worker.py
│   │       ├── rekognition_worker.py
│   │       ├── defect_analyser.py
│   │       └── qc_report_generator.py
│   ├── predictive-maintenance/   # Predictive Maintenance Manager
│   │   ├── manager/
│   │   │   └── handler.py
│   │   └── workers/
│   │       ├── timestream_worker.py
│   │       ├── lstm_worker.py
│   │       ├── lookout_worker.py
│   │       ├── scheduler_worker.py
│   │       └── workorder_worker.py
│   ├── sustainability/           # Sustainability Manager
│   │   ├── manager/
│   │   │   └── handler.py
│   │   └── workers/
│   │       ├── energy_monitor.py
│   │       ├── kpi_calculator.py
│   │       ├── waste_detector.py
│   │       ├── carbon_calculator.py
│   │       └── genai_recommender.py
│   ├── digital-twin/             # Digital Twin Manager
│   │   ├── manager/
│   │   │   └── handler.py
│   │   └── workers/
│   │       ├── twinmaker_worker.py
│   │       ├── dashboard_worker.py
│   │       ├── reconciler_worker.py
│   │       └── snapshot_worker.py
│   └── edge-ai/                  # Edge AI Manager
│       ├── manager/
│       │   └── handler.py
│       └── workers/
│           ├── onnx_worker.py
│           ├── edge_classifier.py
│           ├── cloud_escalator.py
│           └── edge_cache.py
├── infrastructure/
│   ├── cdk/                      # AWS CDK (Python)
│   │   ├── app.py
│   │   └── stacks/
│   │       ├── iot_stack.py
│   │       ├── compute_stack.py
│   │       ├── storage_stack.py
│   │       ├── ml_stack.py
│   │       └── monitoring_stack.py
│   └── terraform/                # Alternative IaC
├── models/
│   ├── lstm/                     # LSTM failure prediction model
│   ├── yolov8/                   # YOLOv8 quality inspection model
│   └── edge/                     # ONNX edge classifier
├── dashboard/
│   ├── src/                      # React ERP dashboard
│   │   ├── components/
│   │   ├── graphql/              # AppSync queries/mutations
│   │   └── pages/
│   └── package.json
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── scripts/
│   ├── deploy.sh
│   ├── seed_dummy_data.py
│   └── simulate_sensors.py
└── docs/
    ├── architecture/
    └── runbooks/
```

## Naming Conventions

- **Agent files**: snake_case (e.g., `anomaly_detector.py`, `lstm_worker.py`)
- **Agent directories**: kebab-case (e.g., `iot-ingestion/`, `quality-vision/`)
- **CDK stacks**: snake_case with `_stack` suffix (e.g., `iot_stack.py`)
- **Lambda functions**: kebab-case with `factorymind-` prefix (e.g., `factorymind-edge-ai-manager`)
- **DynamoDB tables**: PascalCase with `FactoryMind_` prefix (e.g., `FactoryMind_MachineState`)
- **S3 buckets**: kebab-case with `factorymind-` prefix (e.g., `factorymind-raw-data`)
- **EventBridge events**: dot-notation source (e.g., `factorymind.brain.decision`)
- **Kinesis streams**: kebab-case (e.g., `factorymind-sensor-stream`)
- **IDs**: PREFIX-uuid format (e.g., `BRN-<uuid>`, `ING-<uuid>`, `QCR-<uuid>`)

## ID Prefixes

| Agent | ID Prefix | Example |
|-------|-----------|---------|
| Brain Agent | BRN- | BRN-a1b2c3d4 |
| IoT Ingestion | ING- | ING-e5f6g7h8 |
| Quality Vision | QCR- | QCR-i9j0k1l2 |
| Predictive Maintenance | PRD- | PRD-m3n4o5p6 |
| Sustainability | SUSR- | SUSR-q7r8s9t0 |
| Digital Twin | TWNR- | TWNR-u1v2w3x4 |
| Edge AI | EDGR- | EDGR-y5z6a7b8 |
| Work Orders | WO- | WO-2291 |

## Python Standards

- Python 3.11+ for all Lambda functions
- Type hints required on all function signatures
- Pydantic models for all input/output schemas
- boto3 for AWS SDK calls
- structlog for structured JSON logging
- pytest for unit tests
- Use `aws-lambda-powertools` for Lambda observability (logging, tracing, metrics)

## Error Handling

- All agents must retry failed operations once before escalating
- Use exponential backoff for AWS service calls
- Brain Agent escalates to human if any manager returns error after retry
- Edge AI never retries — fire-and-forget with CloudWatch logging

## Testing Strategy

- Unit tests: All worker agent logic (mocked AWS services)
- Integration tests: Manager → Worker delegation chains
- E2E tests: Full Brain → Manager → Worker flows with LocalStack
- Load tests: Simulate 50 machines × 12 readings/minute = 600 events/minute
- Edge latency tests: Verify < 10ms inference SLA

## Build & Deploy Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run unit tests
pytest tests/unit/ -v

# Run integration tests (requires LocalStack)
pytest tests/integration/ -v

# Deploy infrastructure (CDK)
cd infrastructure/cdk && cdk deploy --all

# Deploy single agent Lambda
sam build --template agents/edge-ai/template.yaml
sam deploy --guided

# Seed dummy data
python scripts/seed_dummy_data.py

# Simulate sensor stream
python scripts/simulate_sensors.py --machines 50 --interval 5
```
