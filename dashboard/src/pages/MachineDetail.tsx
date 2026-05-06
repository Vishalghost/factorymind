import { useParams } from "react-router-dom";

import { useMachineSubscription } from "../hooks/useMachineSubscription";

const NORMAL_RANGES = {
  vibration_mms: [2.0, 5.0],
  current_amps: [15.0, 25.0],
  coolant_lmin: [40.0, 50.0],
  acoustic_db: [75.0, 85.0],
} as const;

export function MachineDetail() {
  const { machineId = "" } = useParams<{ machineId: string }>();
  const machine = useMachineSubscription(machineId);

  if (!machine) {
    return <div className="empty">Waiting for live state for {machineId}…</div>;
  }

  const t = machine.last_telemetry;

  return (
    <>
      <h1>{machine.machine_id}</h1>
      <div className="panel">
        <h2>Status</h2>
        <p>
          <span className={`status ${machine.status ?? "IDLE"}`}>
            {machine.status ?? "IDLE"}
          </span>{" "}
          · health {((machine.health_score ?? 1.0) * 100).toFixed(0)}%
        </p>
      </div>

      <div className="panel">
        <h2>Live Telemetry</h2>
        <table>
          <tbody>
            <SensorRow label="Spindle vibration" unit="mm/s"
                       value={t?.vibration_mms} range={NORMAL_RANGES.vibration_mms} />
            <SensorRow label="Motor current" unit="A"
                       value={t?.current_amps} range={NORMAL_RANGES.current_amps} />
            <SensorRow label="Coolant flow" unit="L/min"
                       value={t?.coolant_lmin} range={NORMAL_RANGES.coolant_lmin} />
            <SensorRow label="Acoustic emission" unit="dB"
                       value={t?.acoustic_db} range={NORMAL_RANGES.acoustic_db} />
          </tbody>
        </table>
      </div>

      {machine.active_alerts && machine.active_alerts.length > 0 && (
        <div className="panel">
          <h2>Active Alerts</h2>
          <ul>
            {machine.active_alerts.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

function SensorRow({
  label,
  unit,
  value,
  range,
}: {
  label: string;
  unit: string;
  value: number | null | undefined;
  range: readonly [number, number];
}) {
  if (value == null) {
    return (
      <tr>
        <td>{label}</td>
        <td>—</td>
        <td>{unit}</td>
        <td style={{ color: "var(--muted)" }}>no data</td>
      </tr>
    );
  }
  const [min, max] = range;
  const inNormal = value >= min && value <= max;
  const tone = inNormal ? "var(--green)" : "var(--yellow)";
  return (
    <tr>
      <td>{label}</td>
      <td><strong>{value.toFixed(2)}</strong></td>
      <td>{unit}</td>
      <td style={{ color: tone }}>
        {inNormal ? "normal" : `out of range (${min}–${max})`}
      </td>
    </tr>
  );
}
