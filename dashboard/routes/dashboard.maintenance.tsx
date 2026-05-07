import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Card, StatusPill } from "./dashboard.index";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from "recharts";
import { Button } from "@/components/ui/button";
import { generateFaultReport } from "@/lib/report";
import { useLiveMachines } from "@/lib/useLiveMachines";
import { Download } from "lucide-react";
import type { Machine } from "@/lib/mockData";

export const Route = createFileRoute("/dashboard/maintenance")({ component: Maint });

// Rolling-window vibration history per machine (60 points × 1.5 s = 90 s).
// Module-scoped so the trace survives remounts as the user toggles tabs.
const HISTORY: Record<string, { t: string; value: number; predicted: number }[]> = {};
const MAX_POINTS = 60;
const FAILURE_THRESHOLD = 6.0; // mm/s — ISO 10816 zone D for spindle housings.

function pushSample(machineId: string, vibration: number) {
  const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const prev = HISTORY[machineId] ?? [];
  // Naive ARIMA-ish forecast: extend the last delta out by 30%.
  const delta = prev.length >= 2 ? vibration - prev[prev.length - 1].value : 0;
  const predicted = Math.max(0, vibration + delta * 0.3);
  const next = [...prev, { t, value: vibration, predicted }];
  HISTORY[machineId] = next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next;
}

function priorityFor(m: Machine): "P1" | "P2" | "P3" {
  if (m.status === "critical" || m.health < 50) return "P1";
  if (m.status === "warning" || m.health < 70) return "P2";
  return "P3";
}

function etaFor(m: Machine): string {
  if (m.predictedFailureHours) return `${m.predictedFailureHours}h`;
  if (m.status === "critical") return "8h";
  if (m.status === "warning") return "36h";
  return "5d";
}

function deriveWorkOrders(machines: Machine[]) {
  return machines
    .filter((m) => m.status === "critical" || m.status === "warning" || m.health < 75)
    .sort((a, b) => a.health - b.health)
    .slice(0, 8)
    .map((m, i) => ({
      id: `WO-${String(1000 + i).padStart(4, "0")}`,
      machine: m.id,
      priority: priorityFor(m),
      task:
        m.status === "critical"
          ? `Inspect ${m.name} — vibration ${m.vibration.toFixed(2)} mm/s, health ${m.health}%`
          : `Schedule maintenance — health trending down (${m.health}%)`,
      eta: etaFor(m),
      status: m.status === "critical" ? "open" : "scheduled",
    }));
}

function Maint() {
  const { machines, loading, live } = useLiveMachines();

  const worst = useMemo(() => {
    if (!machines.length) return null;
    return [...machines].sort((a, b) => a.health - b.health)[0];
  }, [machines]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const focused = useMemo(
    () => machines.find((m) => m.id === selectedId) ?? worst,
    [machines, selectedId, worst],
  );

  // Append a sample every 1.5s so the chart fills in even before remount.
  const machinesRef = useRef(machines);
  machinesRef.current = machines;
  useEffect(() => {
    const id = setInterval(() => {
      machinesRef.current.forEach((m) => pushSample(m.id, m.vibration));
    }, 1500);
    return () => clearInterval(id);
  }, []);

  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1500);
    return () => clearInterval(id);
  }, []);
  void tick;

  const series = focused ? HISTORY[focused.id] ?? [] : [];
  const workOrders = useMemo(() => deriveWorkOrders(machines), [machines]);

  const stats = useMemo(() => {
    const critical = machines.filter((m) => m.status === "critical").length;
    const warning = machines.filter((m) => m.status === "warning").length;
    const avgHealth = machines.length
      ? Math.round(machines.reduce((s, m) => s + m.health, 0) / machines.length)
      : 0;
    return { critical, warning, avgHealth };
  }, [machines]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-mono uppercase text-muted-foreground">Module 4 · LSTM Forecasting · SageMaker</p>
          <h2 className="mt-1 font-display text-3xl font-bold">
            Predictive Maintenance
            <span className={`ml-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 align-middle text-xs font-medium ${live ? "bg-success/15 text-success" : "bg-muted text-muted-foreground"}`}>
              <span className={`h-1.5 w-1.5 rounded-full bg-current ${live ? "pulse-dot" : ""}`} />
              {live ? "Live" : loading ? "Connecting…" : "Demo"}
            </span>
          </h2>
        </div>
        <Button onClick={() => generateFaultReport(machines)} disabled={loading}>
          <Download className="mr-2 h-4 w-4" /> Download Fault Report
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <KpiCard l="Fleet avg health" v={`${stats.avgHealth}%`} />
        <KpiCard l="Critical assets" v={String(stats.critical)} accent="destructive" />
        <KpiCard l="Trending warnings" v={String(stats.warning)} accent="warning" />
        <KpiCard l="Open work orders" v={String(workOrders.length)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card title={`Vibration forecast — ${focused?.name ?? "—"} (rolling 90 s)`}>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={series}>
              <CartesianGrid stroke="oklch(0.92 0.01 250)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="t" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} domain={[0, "dataMax + 1"]} />
              <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
              <ReferenceLine y={FAILURE_THRESHOLD} stroke="oklch(0.6 0.24 25)" strokeDasharray="4 4" label={{ value: "Failure threshold", fontSize: 10, fill: "oklch(0.6 0.24 25)" }} />
              <Line type="monotone" dataKey="value" stroke="oklch(0.55 0.22 260)" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="predicted" stroke="oklch(0.78 0.16 75)" strokeWidth={2} strokeDasharray="5 5" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
          <div className="mt-3 flex gap-6 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-primary" /> Actual sensor</span>
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 border-t border-dashed border-warning" /> LSTM forecast</span>
          </div>
        </Card>

        <Card title="Pick an asset">
          <ul className="max-h-[260px] space-y-1.5 overflow-auto">
            {[...machines]
              .sort((a, b) => a.health - b.health)
              .slice(0, 25)
              .map((m) => (
                <li
                  key={m.id}
                  onClick={() => setSelectedId(m.id)}
                  className={`flex cursor-pointer items-center justify-between rounded-md px-2 py-1.5 text-sm transition ${
                    (focused?.id ?? "") === m.id ? "bg-primary/10" : "hover:bg-secondary"
                  }`}
                >
                  <span className="truncate">
                    <span className="font-mono text-xs text-muted-foreground">{m.id}</span>{" "}
                    <span className="font-mono">{m.health}%</span>
                  </span>
                  <StatusPill status={m.status} />
                </li>
              ))}
          </ul>
        </Card>
      </div>

      <Card title="Auto-generated work orders">
        <div className="overflow-hidden rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-secondary text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">Order</th>
                <th className="px-3 py-2 text-left">Asset</th>
                <th className="px-3 py-2 text-left">Priority</th>
                <th className="px-3 py-2 text-left">Task</th>
                <th className="px-3 py-2 text-left">ETA</th>
                <th className="px-3 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {workOrders.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-xs text-muted-foreground">
                    No critical or warning assets — fleet is healthy.
                  </td>
                </tr>
              )}
              {workOrders.map((w) => (
                <tr key={w.id} className="border-t border-border">
                  <td className="px-3 py-2 font-mono text-xs">{w.id}</td>
                  <td className="px-3 py-2">{w.machine}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                      w.priority === "P1" ? "bg-destructive/15 text-destructive" :
                      w.priority === "P2" ? "bg-warning/20 text-warning-foreground" : "bg-secondary"
                    }`}>{w.priority}</span>
                  </td>
                  <td className="px-3 py-2 text-xs">{w.task}</td>
                  <td className="px-3 py-2 font-mono text-xs">{w.eta}</td>
                  <td className="px-3 py-2 capitalize text-xs">{w.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function KpiCard({ l, v, accent }: { l: string; v: string; accent?: "destructive" | "warning" }) {
  const tone = accent === "destructive" ? "text-destructive" : accent === "warning" ? "text-warning" : "";
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{l}</p>
      <p className={`mt-2 font-display text-3xl font-bold ${tone}`}>{v}</p>
    </div>
  );
}
