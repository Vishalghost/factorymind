---
inclusion: always
---

# FactoryMind — Multi-Agent Manufacturing Intelligence Platform

## System Overview

FactoryMind is a hierarchical multi-agent manufacturing intelligence system built on AWS Bedrock AgentCore. It uses a Brain Agent (LangGraph orchestrator) that delegates to 5 Manager Agents, each managing their own Worker Agents.

## Agent Hierarchy

```
Brain Agent (LangGraph Orchestrator)
├── IoT Ingestion Manager (3 Workers)
├── Quality Vision Manager (5 Workers)
├── Predictive Maintenance Manager (5 Workers)
├── Sustainability Manager (5 Workers)
├── Digital Twin Manager (4 Workers)
└── Edge AI Manager (4 Workers)
```

## Delegation Rules

- Brain Agent ONLY delegates to Manager Agents — never directly to Workers
- Manager Agents delegate to their own Worker Agents
- Edge AI Agent operates independently for sub-10ms decisions, escalates to cloud only for ANOMALY class
- Brain Agent severity routing:
  - CRITICAL → Maintenance Manager + Digital Twin Manager + Human Handoff
  - HIGH → Relevant domain manager + Digital Twin Manager
  - MEDIUM → Relevant domain manager only
  - LOW → Log to CloudWatch, no delegation

## Data Flow

1. Sensors → IoT Core (MQTT) → Kinesis → IoT Ingestion Manager → Timestream + DynamoDB
2. Anomaly detected → EventBridge → Brain Agent → Delegates to relevant managers
3. Manager results → EventBridge → Digital Twin Manager → AppSync → React Dashboard
4. Edge path: Sensors → IoT Core Rule → Edge AI Lambda (ONNX, <10ms) → Escalate if ANOMALY

## Key Architectural Patterns

### Consensus-Based Decisions
- Predictive Maintenance requires BOTH LSTM and Lookout for Equipment to agree before CRITICAL classification
- Quality Vision uses YOLOv8 primary + Rekognition fallback (confidence < 0.75 triggers fallback)

### Fire-and-Forget Edge
- Edge AI never waits for cloud response
- Local decisions are immediate, escalations are async via EventBridge

### Knowledge-Augmented Recommendations
- All managers query Bedrock Knowledge Bases before generating recommendations
- Historical patterns inform current decisions (past failures, defect patterns, energy benchmarks)

### Real-Time Twin Synchronization
- Digital Twin is the system of record for current plant state
- Redis cache (TTL 300s) → DynamoDB → IoT TwinMaker → AppSync subscriptions
- Historical snapshots on every CRITICAL status change

## Performance SLAs

| Agent | Latency Target | Notes |
|-------|---------------|-------|
| Edge AI | < 10ms | ONNX inference, fire-and-forget |
| IoT Ingestion | < 500ms | Batch of 100 records |
| Digital Twin Sync | < 500ms | State update to dashboard |
| Quality Vision | < 3s | Full inspection pipeline |
| Predictive Maintenance | < 3s | 72-hour window analysis |
| Sustainability | < 5s | Daily energy analysis |
| Brain Agent | < 2s | Full delegation chain |

## Plant Configuration

- Plant ID: PLANT-001 (Chennai Plant 01)
- Machines: MCH-001 through MCH-050
- Production Lines: LINE-A, LINE-B, LINE-C
- Floor Area: 12,000 sqm
- Machine Types: CNC_LATHE, HYDRAULIC_PRESS, CONVEYOR, ROBOT_ARM, WELDING_UNIT
