"""FactoryMind constants and configuration for Aerospace CNC Titanium Milling."""

# Plant Configuration
PLANT_ID = "PLANT-001"
PLANT_NAME = "Chennai Aerospace Plant 01"
MACHINE_PREFIX = "CNC-AERO-"
MACHINE_COUNT = 50
PRODUCTION_LINES = ["LINE-A", "LINE-B", "LINE-C"]
MACHINE_TYPE = "CNC_MILL"
MATERIAL = "Ti-6Al-4V"

# Titanium Milling Sensor Thresholds
# Normal operating ranges
VIBRATION_NORMAL_MIN = 2.0  # mm/s
VIBRATION_NORMAL_MAX = 5.0  # mm/s
CURRENT_NORMAL_MIN = 15.0  # Amps
CURRENT_NORMAL_MAX = 25.0  # Amps
COOLANT_NORMAL_MIN = 40.0  # L/min
COOLANT_NORMAL_MAX = 50.0  # L/min
ACOUSTIC_NORMAL_MIN = 75.0  # dB
ACOUSTIC_NORMAL_MAX = 85.0  # dB

# Warning thresholds (single sensor)
VIBRATION_WARNING_MAX = 8.0  # mm/s
CURRENT_WARNING_MAX = 35.0  # Amps
COOLANT_WARNING_MIN = 30.0  # L/min
ACOUSTIC_WARNING_MAX = 95.0  # dB

# Anomaly thresholds (triggers alert)
VIBRATION_ANOMALY_THRESHOLD = 8.0  # mm/s - severe tool wear or chatter
CURRENT_ANOMALY_THRESHOLD = 35.0  # Amps - dull tool struggling
COOLANT_ANOMALY_THRESHOLD = 30.0  # L/min - blockage risk
ACOUSTIC_ANOMALY_THRESHOLD = 95.0  # dB - micro-fractures in tool

# Physical range limits (reject outliers beyond these)
VIBRATION_PHYSICAL_MAX = 20.0  # mm/s
CURRENT_PHYSICAL_MAX = 50.0  # Amps
COOLANT_PHYSICAL_MAX = 80.0  # L/min
ACOUSTIC_PHYSICAL_MAX = 120.0  # dB

# Compound Rule: IMMEDIATE SPINDLE STOP
# If vibration > 8.0 mm/s AND coolant < 30.0 L/min simultaneously
COMPOUND_RULE_VIBRATION_THRESHOLD = 8.0  # mm/s
COMPOUND_RULE_COOLANT_THRESHOLD = 30.0  # L/min

# Tool Wear Trending (Predictive Maintenance)
TOOL_WEAR_CURRENT_RATE = 0.5  # Amps per hour increase indicates wear
TOOL_WEAR_VIBRATION_RATE = 0.3  # mm/s per hour increase indicates wear
TOOL_WEAR_WINDOW_HOURS = 72  # Rolling window for trend analysis

# Sustainability Constants
CARBON_KG_PER_KWH = 0.82  # India grid average
ENERGY_COST_INR_PER_KWH = 7.50  # Rs per kWh

# Redis Configuration
REDIS_TWIN_TTL_SECONDS = 300  # Digital Twin cache TTL
REDIS_EDGE_WINDOW_SIZE = 10  # Last N readings for Edge AI

# Timing Constraints
STALE_TIMESTAMP_THRESHOLD_SECONDS = 60
KINESIS_MAX_BATCH_SIZE = 100
SENSOR_SAMPLING_RATE_HZ = 1  # 1 reading per second

# EventBridge
EVENT_BUS_NAME = "factorymind-bus"
BRAIN_EVENT_SOURCE = "factorymind.brain.decision"
IOT_EVENT_SOURCE = "factorymind.iot.anomaly"
EDGE_EVENT_SOURCE = "factorymind.edge.escalation"

# MQTT
MQTT_TOPIC = "factory/aerospace/cnc/telemetry"

# ID Prefixes
ID_PREFIX_BRAIN = "BRN-"
ID_PREFIX_INGESTION = "ING-"
ID_PREFIX_QUALITY = "QCR-"
ID_PREFIX_PREDICTIVE = "PRD-"
ID_PREFIX_SUSTAINABILITY = "SUSR-"
ID_PREFIX_TWIN = "TWNR-"
ID_PREFIX_EDGE = "EDGR-"
ID_PREFIX_WORK_ORDER = "WO-"

# SLA Targets (milliseconds)
SLA_EDGE_AI_MS = 10
SLA_IOT_INGESTION_MS = 500
SLA_DIGITAL_TWIN_MS = 500
SLA_QUALITY_VISION_MS = 3000
SLA_PREDICTIVE_MAINTENANCE_MS = 3000
SLA_SUSTAINABILITY_MS = 5000
SLA_BRAIN_AGENT_MS = 2000

# Simulation Baselines (MODE_OPTIMAL)
SIM_VIBRATION_BASELINE = 3.4  # mm/s
SIM_CURRENT_BASELINE = 18.2  # Amps
SIM_COOLANT_BASELINE = 45.1  # L/min
SIM_ACOUSTIC_BASELINE = 78.5  # dB
SIM_SPINDLE_RPM = 3500
