import { useEffect, useState } from "react";
import { generateClient } from "aws-amplify/api";

import { onMachineStateUpdated } from "../graphql/subscriptions";
import type { Alert, MachineState, Severity } from "../types";

const client = generateClient();
const SEVERITY_FILTERS: ("ALL" | Severity)[] = ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"];

export function Alerts() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [filter, setFilter] = useState<"ALL" | Severity>("ALL");

  // Subscribe and synthesize alerts from active_alerts list on each update.
  useEffect(() => {
    const sub = client
      .graphql({ query: onMachineStateUpdated })
      // @ts-expect-error — Amplify v6 subscription typing.
      .subscribe({
        next: ({ data }: { data: { onMachineStateUpdated: MachineState } }) => {
          const m = data.onMachineStateUpdated;
          if (!m.active_alerts || m.active_alerts.length === 0) return;
          const newAlerts: Alert[] = m.active_alerts.map((id) => ({
            alert_id: id,
            machine_id: m.machine_id,
            alert_type: id.split("-")[0] ?? "ALERT",
            severity: _inferSeverity(m),
            timestamp: m.updated_at ?? new Date().toISOString(),
            message: `Active on ${m.machine_id}`,
          }));
          setAlerts((prev) => [...newAlerts, ...prev].slice(0, 200));
        },
      });
    return () => sub.unsubscribe();
  }, []);

  const visible = filter === "ALL" ? alerts : alerts.filter((a) => a.severity === filter);

  return (
    <>
      <h1>Alerts</h1>
      <div style={{ marginBottom: 16 }}>
        {SEVERITY_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            style={{
              marginRight: 8,
              padding: "6px 12px",
              background: filter === s ? "var(--accent)" : "var(--panel-2)",
              color: filter === s ? "var(--bg)" : "var(--text)",
              border: "1px solid #243142",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            {s}
          </button>
        ))}
      </div>

      <div className="panel">
        {visible.length === 0 ? (
          <div className="empty">No alerts yet. Subscribed and waiting…</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Machine</th>
                <th>Type</th>
                <th>Severity</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((a) => (
                <tr key={`${a.alert_id}-${a.timestamp}`}>
                  <td>{new Date(a.timestamp).toLocaleTimeString()}</td>
                  <td>{a.machine_id}</td>
                  <td>{a.alert_type}</td>
                  <td className={`severity-${a.severity}`}>{a.severity}</td>
                  <td>{a.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function _inferSeverity(m: MachineState): Severity {
  // Without a dedicated alerts API, infer from health and telemetry.
  const health = m.health_score ?? 1.0;
  if (health < 0.3) return "CRITICAL";
  if (health < 0.6) return "HIGH";
  if (health < 0.85) return "MEDIUM";
  return "LOW";
}
