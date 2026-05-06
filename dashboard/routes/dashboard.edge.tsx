import { createFileRoute } from "@tanstack/react-router";
import { Card } from "./dashboard.index";

export const Route = createFileRoute("/dashboard/edge")({ component: Edge });

const NODES = [
  { id: "EDGE-A1", host: "Jetson Nano · Line A", lat: 6, model: "yolov8n.onnx", ver: "v3.2.1", status: "Online" },
  { id: "EDGE-B1", host: "RPi 4 · Line B", lat: 9, model: "lstm-vib.tflite", ver: "v1.8.0", status: "Online" },
  { id: "EDGE-B2", host: "Jetson Xavier · Line B", lat: 5, model: "yolov8s.onnx", ver: "v3.2.1", status: "Online" },
  { id: "EDGE-C1", host: "RPi 4 · Line C", lat: 11, model: "anomaly-cnn.tflite", ver: "v2.0.4", status: "OTA pending" },
];

function Edge() {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-mono uppercase text-muted-foreground">Module 1 · ONNX + TF-Lite</p>
        <h2 className="mt-1 font-display text-3xl font-bold">Edge AI Inference</h2>
        <p className="mt-1 text-sm text-muted-foreground">Sub-10ms on-device decisions. Zero cloud round-trip on the critical path.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        {[
          { l: "Active edge nodes", v: "4" },
          { l: "Avg inference", v: "7.8 ms" },
          { l: "Cloud cost saved", v: "$2,140/mo" },
          { l: "OTA rollouts (30d)", v: "12" },
        ].map((s) => (
          <div key={s.l} className="rounded-xl border border-border bg-card p-5">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">{s.l}</p>
            <p className="mt-2 font-display text-3xl font-bold">{s.v}</p>
          </div>
        ))}
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
                <th className="px-3 py-2 text-right">Latency</th>
                <th className="px-3 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {NODES.map((n) => (
                <tr key={n.id} className="border-t border-border">
                  <td className="px-3 py-2 font-mono text-xs">{n.id}</td>
                  <td className="px-3 py-2">{n.host}</td>
                  <td className="px-3 py-2 font-mono text-xs">{n.model}</td>
                  <td className="px-3 py-2 font-mono text-xs">{n.ver}</td>
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
