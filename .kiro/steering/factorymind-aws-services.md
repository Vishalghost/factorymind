---
inclusion: always
---

# FactoryMind — AWS Services Reference

## Service Map by Agent

### Brain Agent
- Amazon Bedrock AgentCore — runtime and session management
- Amazon Bedrock (Claude 3.5) — reasoning LLM
- Amazon DynamoDB — read plant state before delegating
- Amazon ElastiCache (Redis) — cache task context between steps
- Amazon EventBridge — publish final decisions as plant-wide events
- AWS Lambda — invoke each Manager Agent
- Amazon CloudWatch — decision logs and latency metrics
- AWS X-Ray — trace full delegation chain

### IoT Ingestion Manager
- AWS IoT Core — MQTT topic: `factory/+/sensors/+`
- Amazon Kinesis Data Streams — stream: `factorymind-sensor-stream`
- Amazon Kinesis Firehose — archive to S3: `factorymind-raw-data`
- Amazon Timestream — database: `FactoryMindSensors`, table: `SensorReadings`
- Amazon DynamoDB — table: `FactoryMind_MachineState`
- AWS KMS — encrypt machine data
- Amazon CloudWatch — ingestion metrics
- Amazon EventBridge — publish anomaly events

### Quality Vision Manager
- Amazon S3 — bucket: `factorymind-product-images` (read), `factorymind-defect-images` (write)
- Amazon SageMaker Serverless — endpoint: `factorymind-yolov8-quality`
- Amazon Rekognition — DetectLabels + DetectAnomalies (fallback)
- Amazon Bedrock Knowledge Bases — historical defect patterns
- Amazon DynamoDB — tables: `FactoryMind_QualityResults`, `FactoryMind_QualityThresholds`
- Amazon SNS — topic: `factorymind-quality-alerts`
- Amazon CloudWatch — quality metrics
- AWS X-Ray — inspection pipeline trace

### Predictive Maintenance Manager
- Amazon Timestream — 72-hour rolling sensor windows
- Amazon SageMaker Serverless — endpoint: `factorymind-lstm-maintenance`
- Amazon Lookout for Equipment — model: `factorymind-machine-anomaly-model`
- Amazon Bedrock Knowledge Bases — past maintenance logs
- Amazon DynamoDB — tables: `FactoryMind_MachineSpecs`, `FactoryMind_Predictions`, `FactoryMind_WorkOrders`
- Amazon SQS — queue: `factorymind-workorder-queue`
- Amazon SNS — topic: `factorymind-maintenance-alerts`
- Amazon EventBridge — publish failure predictions
- Amazon CloudWatch — prediction metrics

### Sustainability Manager
- Amazon Timestream — table: `EnergyReadings`
- Amazon DynamoDB — tables: `FactoryMind_EnergyBaselines`, `FactoryMind_SustainabilityKPIs`
- Amazon Bedrock (Claude 3.5) — generate recommendations
- Amazon Bedrock Knowledge Bases — industry benchmarks
- Amazon S3 — bucket: `factorymind-reports`
- Amazon SES — email weekly reports
- Amazon CloudWatch — sustainability metrics
- Amazon EventBridge — publish sustainability summary

### Digital Twin Manager
- AWS IoT TwinMaker — workspace: `factorymind-workspace`
- AWS AppSync — API: `factorymind-appsync-api`, mutation: `updateMachineState`
- Amazon DynamoDB — tables: `FactoryMind_TwinState`, `FactoryMind_FloorLayout`
- Amazon ElastiCache (Redis) — key: `twin:state:{plant_id}:{machine_id}` (TTL 300s)
- Amazon S3 — bucket: `factorymind-twin-snapshots`
- Amazon CloudWatch — twin sync metrics
- Amazon EventBridge — subscribe to state change events

### Edge AI Manager
- AWS Lambda — function: `factorymind-edge-ai-manager` (1024MB, 3s timeout)
- AWS Lambda Layer — ONNX Runtime + model: `edge_classifier_v2.onnx`
- Amazon DynamoDB — tables: `FactoryMind_EdgeThresholds`, `FactoryMind_EdgeResults`
- Amazon ElastiCache (Redis) — key: `edge:window:{machine_id}` (last 10 readings)
- Amazon Kinesis Data Streams — stream: `factorymind-edge-decisions`
- Amazon CloudWatch — edge metrics (inference_latency_ms, escalations_pct)
- Amazon EventBridge — escalation events

## DynamoDB Tables Summary

| Table | Primary Key | Purpose |
|-------|------------|---------|
| FactoryMind_MachineState | machine_id | Current sensor state per machine |
| FactoryMind_MachineSpecs | machine_id | Static machine specifications |
| FactoryMind_QualityResults | inspection_report_id | QC inspection results |
| FactoryMind_QualityThresholds | product_type | Defect rate thresholds |
| FactoryMind_Predictions | prediction_report_id | Failure predictions |
| FactoryMind_WorkOrders | work_order_id | Maintenance work orders |
| FactoryMind_EnergyBaselines | machine_id | Energy consumption baselines |
| FactoryMind_SustainabilityKPIs | report_id | Daily sustainability KPIs |
| FactoryMind_TwinState | machine_id | Current digital twin state |
| FactoryMind_FloorLayout | plant_id | Factory floor layout |
| FactoryMind_EdgeThresholds | machine_id | Edge classification thresholds |
| FactoryMind_EdgeResults | edge_result_id | Edge inference results |

## S3 Buckets

| Bucket | Purpose |
|--------|---------|
| factorymind-raw-data | Archived raw sensor data (via Firehose) |
| factorymind-product-images | Product images from cameras |
| factorymind-defect-images | Annotated defect images with bounding boxes |
| factorymind-reports | Sustainability PDF reports |
| factorymind-twin-snapshots | Historical state snapshots on CRITICAL events |

## Constants

- Carbon conversion: 0.82 kg CO2 per kWh (India grid average)
- Energy cost: Rs 7.50 per kWh
- Redis TTL: 300 seconds (Digital Twin), FIFO 10 readings (Edge)
- Kinesis batch size: up to 100 records per invocation
- Stale timestamp threshold: 60 seconds (IoT Ingestion rejects older)
