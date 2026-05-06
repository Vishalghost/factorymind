import { Link } from "react-router-dom";
import type { MachineState } from "../types";

export function MachineCard({ machine }: { machine: MachineState }) {
  const t = machine.last_telemetry;
  const health = machine.health_score ?? 1.0;
  const healthClass =
    health < 0.4 ? "critical" : health < 0.7 ? "warning" : "";

  return (
    <Link to={`/machines/${machine.machine_id}`} className="machine-card">
      <div>
        <span className="id">{machine.machine_id}</span>
        <span className={`status ${machine.status ?? "RUNNING"}`}>
          {machine.status ?? "RUNNING"}
        </span>
      </div>
      <div className="telemetry">
        <span>vib</span>
        <strong>{t?.vibration_mms?.toFixed(2) ?? "—"} mm/s</strong>
        <span>cur</span>
        <strong>{t?.current_amps?.toFixed(2) ?? "—"} A</strong>
        <span>cool</span>
        <strong>{t?.coolant_lmin?.toFixed(2) ?? "—"} L/min</strong>
        <span>aco</span>
        <strong>{t?.acoustic_db?.toFixed(2) ?? "—"} dB</strong>
      </div>
      <div className="health-bar">
        <div
          className={`health-bar-fill ${healthClass}`}
          style={{ width: `${health * 100}%` }}
        />
      </div>
    </Link>
  );
}
