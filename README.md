# FactoryMind — Multi-Agent Manufacturing Intelligence Platform

Hierarchical multi-agent system for aerospace CNC titanium milling (Ti-6Al-4V) built on AWS. Brain Agent (LangGraph orchestrator) delegates to 6 Manager Agents, each managing specialized Worker Agents.

## Architecture

```
Brain Agent (LangGraph Orchestrator)        SLA <2s
├── IoT Ingestion Manager (3 Workers)       SLA <500ms
├── Quality Vision Manager (5 Workers)      SLA <3s
├── Predictive Maintenance Manager (5)      SLA <3s
├── Sustainability Manager (5 Workers)      SLA <5s
├── Digital Twin Manager (4 Workers)        SLA <500ms
└── Edge AI Manager (4 Workers)             SLA <10ms
```

## Domain: Aerospace CNC Titanium Milling

Monitors critical parameters to prevent catastrophic tool failure:

| Sensor              | Normal Range     | Anomaly Threshold |
|---------------------|------------------|-------------------|
| Spindle Vibration   | 2.0 – 5.0 mm/s   | > 8.0 mm/s        |
| Motor Current       | 15.0 – 25.0 A    | > 35.0 A          |
| Coolant Flow        | 40.0 – 50.0 L/min| < 30.0 L/min      |
| Acoustic Emission   | 75 – 85 dB       | > 95 dB           |

**Critical Compound Rule**: vibration > 8.0 mm/s AND coolant < 30.0 L/min = IMMEDIATE SPINDLE STOP.

## AWS-native services

Every component is AWS-native:

- **Compute**: Lambda (Python 3.11), Lambda Layers (deps + ONNX Runtime)
- **Brain orchestration**: LangGraph state machine running inside Lambda
- **Ingestion**: IoT Core MQTT → Kinesis → Firehose → S3 + Timestream
- **State**: DynamoDB (12 tables) + ElastiCache Redis (TTL 300s)
- **ML**: Amazon Rekognition (DetectLabels for quality vision), SageMaker Serverless (LSTM for predictive maintenance), Lookout for Equipment, Bedrock Claude 3.5 + Knowledge Bases
- **Eventing**: EventBridge bus `factorymind-bus`, SQS work-order queue, SNS alerts
- **Real-time**: AppSync GraphQL subscriptions, IoT TwinMaker workspace
- **Reporting**: SES weekly emails, S3 reports bucket
- **Observability**: CloudWatch dashboards + alarms, X-Ray tracing
- **Frontend**: React + Vite + AWS Amplify hosted on S3 static website

## Quick Start

### Run tests
```bash
pip install -r requirements-dev.txt
PYTHONPATH=. pytest tests/                  # 261 tests
```

### Simulate sensor data
```bash
PYTHONPATH=. python scripts/simulate_aerospace_cnc.py --machine-id CNC-AERO-01 --mode catastrophic --duration 30
```

### Deploy to AWS
```bash
./scripts/deploy.sh                # Linux/macOS
.\scripts\deploy.ps1               # Windows
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for full instructions including Lookout for Equipment, model artifact upload, smoke testing, and tear-down.

### Local development with Docker
```bash
docker compose up --build localstack redis brain iot-ingestion edge-ai digital-twin
docker compose run --rm seed
docker compose run --rm simulator --mode catastrophic --duration 30
```

## Simulation Modes

| Mode                     | Behaviour                                                                                |
| ------------------------ | ---------------------------------------------------------------------------------------- |
| `optimal`                | Gaussian noise around healthy baselines. Tests normal operation.                         |
| `tool_wear`              | Steady current (+0.5 A/h) and vibration (+0.3 mm/s/h) drift. Tests Predictive Maintenance trend detection. |
| `catastrophic`           | Instant coolant drop + vibration spike. Tests Edge AI compound rule + IMMEDIATE_SPINDLE_STOP.       |

## Project layout

```
agents/                      # Lambda handlers + workers (one package per agent)
infrastructure/cdk/          # 5 CDK stacks: storage, iot, compute, ml, monitoring
infrastructure/cdk/schema/   # AppSync GraphQL schema
docker/                      # Per-agent Dockerfiles + base image
docker-compose.yml           # Local dev stack (LocalStack + Redis + agents)
scripts/                     # deploy.sh, deploy.ps1, build_layers.sh, seed_dummy_data.py, simulate_*.py
dashboard/                   # React + Vite + Amplify dashboard
tests/unit/                  # 231 tests
tests/integration/           # 15 tests (moto + fakeredis)
tests/e2e/                   # 5 tests (cross-agent flows)
.kiro/                       # Spec + steering + skill definitions (source of truth)
DEPLOYMENT.md                # Full deploy runbook
```

## Status

Per [.kiro/specs/factorymind-multi-agent-platform/tasks.md](.kiro/specs/factorymind-multi-agent-platform/tasks.md):

- ✅ All 6 Manager Agents + Brain Agent + simulator implemented
- ✅ All 5 CDK stacks (storage, iot, compute, ml, monitoring) implemented and parse cleanly
- ✅ 251 tests passing (231 unit + 15 integration + 5 e2e)
- ✅ Operational scripts (`seed_dummy_data.py`, `deploy.sh`, `deploy.ps1`, `build_layers.sh`)
- ✅ Per-agent Dockerfiles + `docker-compose.yml` for local dev
- ✅ React dashboard with AppSync subscriptions (Plant overview, Machine detail, Alerts, Work Orders, Sustainability)

Outstanding work (manual / out-of-band):

- LSTM model artifact needs training (`python models/lstm/train_lstm_maintenance.py`) and S3 upload (`bash models/lstm/package_lstm.sh --upload`) — see DEPLOYMENT.md §4.
- Quality Vision uses Amazon Rekognition out of the box (no model needed). For higher accuracy on real defect imagery, train a Rekognition Custom Labels project — see DEPLOYMENT.md §4.
- Lookout for Equipment dataset + model — see DEPLOYMENT.md §5.
- IoT TwinMaker scene authoring (3D view) — Console-only.

## Contributing

This project follows [.kiro/steering/factorymind-conventions.md](.kiro/steering/factorymind-conventions.md):

- Python 3.11+, type hints required, Pydantic for I/O schemas
- structlog + aws-lambda-powertools for observability
- pytest + moto + fakeredis for tests
- All inter-agent communication flows through EventBridge
- Edge AI is fire-and-forget (no retries, no waits)
