import { createFileRoute } from "@tanstack/react-router";
import { useMemo } from "react";
import { Card } from "./dashboard.index";
import { useLiveMachines } from "@/lib/useLiveMachines";

export const Route = createFileRoute("/dashboard/edge")({ component: Edge });

// One edge node per production line — co-located with the machines.
// Latency + status are derived from the cluster's live fleet activity.
const EDGE_NODES = [
  { id: "EDGE-A1", host: "Jetson Xavier · Line A", model: "rekognition-async.onnx", ver: "v3.2.1" },
  { id: "EDGE-B1", host: "Jetson Nano · Line B", model: "lstm-vib.tflite", ver: "v1.8.0" },
  { id: "EDGE-C1", host: "RPi 4 · Line C", model: "anomaly-cnn.tflite", ver: "v2.0.4" },
];

function Edge() {
  const { machines, live, loading } = useLiveMachines();

  const summary = useMemo(() => {
    const byLine = new Map<string, { running: number; total: number; vibSum: number }>();
    machines.forEach((m) => {
      const cur = byLine.get(m.line) ?? { running: 0, total: 0, vibSum: 0 };
      cur.total += 1;
      if (m.status === "running") cur.running += 1;
      cur.vibSum += m.vibration;
      byLine.set(m.line, cur);
    });
    const runningTotal = machines.filter((m) => m.status === "running").length;
    return { byLine, runningTotal };
  }, [machines]);

  const nodeRows = useMemo(() => {
    return EDGE_NODES.map((n, idx) => {
      const lineKey = n.host.split("·")[1]?.trim() ?? `Line ${String.fromCharCode(65 + idx)}`;
      const stats = summary.byLine.get(lineKey) ?? { running: 0, total: 0, vibSum: 0 };
      // Latency model: more activity = a touch more queueing.
      const lat = +(5 + (stats.running / Math.max(1, stats.total)) * 6).toFixed(1);
      // Online unless the line is fully idle (suggests a transport issue).
      const status = stats.running > 0 ? "Online" : "OTA pending";
      return { ...n, lat, status, line: lineKey, running: stats.running, total: stats.total };
    });
  }, [summary]);

  const avgLat = nodeRows.length
    ? +(nodeRows.reduce((s, n) => s + n.lat, 0) / nodeRows.length).toFixed(1)
    : 0;
  // Saved cost ≈ 1.4 cents per inference avoided × inferences/min × 60 × 24 × 30.
  const inferencesPerMin = summary.runningTotal * 25;
  const monthlySaved = Math.round((inferencesPerMin * 60 * 24 * 30 * 0.014) / 100);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-mono uppercase text-muted-foreground">Module 1 · ONNX + TF-Lite</p>
        <h2 className="mt-1 font-display text-3xl font-bold">
          Edge AI Inference
          <span className={`ml-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 align-middle text-xs font-medium ${live ? "bg-success/15 text-success" : "bg-muted text-muted-foreground"}`}>
            <span className={`h-1.5 w-1.5 rounded-full bg-current ${live ? "pulse-dot" : ""}`} />
            {live ? "Live" : loading ? "Connecting…" : "Demo"}
          </span>
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Sub-10 ms on-device decisions for {summary.runningTotal} active machines across {nodeRows.length} lines.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <KpiCard l="Active edge nodes" v={String(nodeRows.filter((n) => n.status === "Online").length)} />
        <KpiCard l="Avg inference" v={`${avgLat} ms`} />
        <KpiCard l="Cloud cost saved (mo)" v={`$${monthlySaved.toLocaleString()}`} />
        <KpiCard l="Machines covered" v={String(machines.length)} />
      </div>

      <Card title="Edge node fleet">
        <div className="overflow-hidden rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-secondary text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">Node</th>
                <th className="px-3 py-2 text-left">Host</th>
                <th className="px-3 py-2 text-left">Model</th>
                <th className="px-3 py-2 text-left">Version</th>
                <th className="px-3 py-2 text-right">Machines</th>
                <th className="px-3 py-2 text-right">Latency</th>
                <th className="px-3 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {nodeRows.map((n) => (
                <tr key={n.id} className="border-t border-border">
                  <td className="px-3 py-2 font-mono text-xs">{n.id}</td>
                  <td className="px-3 py-2">{n.host}</td>
                  <td className="px-3 py-2 font-mono text-xs">{n.model}</td>
                  <td className="px-3 py-2 font-mono text-xs">{n.ver}</td>
                  <td className="px-3 py-2 text-right font-mono">{n.running}/{n.total}</td>
                  <td className="px-3 py-2 text-right font-mono">{n.lat} ms</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${n.status === "Online" ? "bg-success/15 text-success" : "bg-warning/20 text-warning-foreground"}`}>{n.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function KpiCard({ l, v }: { l: string; v: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{l}</p>
      <p className="mt-2 font-display text-3xl font-bold">{v}</p>
    </div>
  );
}
