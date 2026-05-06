// Shared types — mirror the GraphQL schema and Python pydantic models.

export type MachineStatus = "RUNNING" | "IDLE" | "MAINTENANCE" | "FAULT";

export interface Telemetry {
  vibration_mms: number | null;
  current_amps: number | null;
  coolant_lmin: number | null;
  acoustic_db: number | null;
}

export interface MachineState {
  machine_id: string;
  plant_id: string;
  status: MachineStatus | null;
  health_score: number | null;
  last_telemetry: Telemetry | null;
  active_alerts: string[] | null;
  updated_at: string | null;
}

export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

export interface Alert {
  alert_id: string;
  machine_id: string;
  alert_type: string;
  severity: Severity;
  timestamp: string;
  message: string;
}

export interface WorkOrder {
  work_order_id: string;
  machine_id: string;
  priority: Severity;
  status: "OPEN" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";
  failure_mode: string;
  recommended_action: string;
  scheduled_date: string;
}
