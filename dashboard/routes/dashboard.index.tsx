import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { defectFeed, generateTimeSeries } from "@/lib/mockData";
import { useLiveMachines } from "@/lib/useLiveMachines";
import { generateFaultReport } from "@/lib/report";
import { Button } from "@/components/ui/button";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid, Bar, BarChart } from "recharts";
import { AlertTriangle, CheckCircle2, Download, FileWarning, Zap } from "lucide-react";

export const Route = createFileRoute("/dashboard/")({
  component: Overview,
});

// Module-level seed so chart shapes survive component remounts. If the
// route component re-mounts (route preload, subscription churn, etc.)
// we hand back the same data instead of generating a new random shape,
// which previously made the chart "reset" every few seconds.
let SERIES_SEED: ReturnType<typeof generateTimeSeries> | null = null;
let ENERGY_SEED: ReturnType<typeof generateTimeSeries> | null = null;

function Overview() {
  const { machines, loading, live } = useLiveMachines();
  if (!SERIES_SEED) SERIES_SEED = generateTimeSeries(30, 78, 18);
  if (!ENERGY_SEED) ENERGY_SEED = generateTimeSeries(12, 95, 30);

  const [series, setSeries] = useState(SERIES_SEED);
  const [energy, setEnergy] = useState(ENERGY_SEED);
  const tickRef = useRef(0);

  // Stable ref to the latest fleet — avoids re-running the chart interval
  // whenever a single machine's telemetry updates.
  const machinesRef = useRef(machines);
  machinesRef.current = machines;

  // Smooth rolling window: every 5 s, append a new data point derived from
  // current fleet OEE and drop the oldest. The wave drifts left rather
  // than getting wiped and regenerated, so the chart no longer "resets".
  useEffect(() => {
    const id = setInterval(() => {
      tickRef.current += 1;
      const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const oee = machinesRef.current.length
        ? Math.round(machinesRef.current.reduce((s, m) => s + (m.health ?? 0), 0) / machinesRef.current.length)
        : 78;
      const energyKwh = Math.round(60 + Math.sin(tickRef.current / 4) * 25 + Math.random() * 8);
      setSeries((prev) => {
        const next = [...prev.slice(1), { t, value: oee, predicted: oee }];
        SERIES_SEED = next;
        return next;
      });
      setEnergy((prev) => {
        const next = [...prev.slice(1), { t, value: energyKwh, predicted: energyKwh }];
        ENERGY_SEED = next;
        return next;
      });
    }, 5000);
    return () => clearInterval(id);
  }, []);

  const stats = useMemo(() => {
    const running = machines.filter((m) => m.status === "running").length;
    const critical = machines.filter((m) => m.status === "critical").length;
    const warning = machines.filter((m) => m.status === "warning").length;
    const oee = machines.length
      ? Math.round(machines.reduce((s, m) => s + (m.health ?? 0), 0) / machines.length)
      : 0;
    return { running, critical, warning, oee };
  }, [machines]);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-xs font-mono uppercase text-muted-foreground">PLANT-001 · Chennai Aerospace · Ti-6Al-4V</p>
          <h2 className="mt-1 font-display text-3xl font-bold">
            Real-time Plant Overview
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
        <Stat label="Fleet OEE" value={`${stats.oee}%`} accent="primary" icon={Zap} sub={`${stats.running}/${machines.length} running`} />
        <Stat label="Critical alerts" value={String(stats.critical)} accent="destructive" icon={AlertTriangle} sub="Action required" />
        <Stat label="Warnings" value={String(stats.warning)} accent="warning" icon={FileWarning} sub="Trending toward fault" />
        <Stat label="Quality pass rate" value="96.4%" accent="success" icon={CheckCircle2} sub="↑ 2.1% vs yesterday" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Fleet health (last 30 min)" className="lg:col-span-2">
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={series}>
              <defs>
                <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="oklch(0.55 0.22 260)" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="oklch(0.55 0.22 260)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="oklch(0.92 0.01 250)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="t" tick={{ fontSize: 10 }} stroke="oklch(0.5 0.02 250)" />
              <YAxis tick={{ fontSize: 10 }} stroke="oklch(0.5 0.02 250)" />
              <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid oklch(0.92 0.01 250)", fontSize: 12 }} />
              <Area type="monotone" dataKey="value" stroke="oklch(0.55 0.22 260)" strokeWidth={2} fill="url(#g1)" isAnimationActive={false} />
              <Area type="monotone" dataKey="predicted" stroke="oklch(0.65 0.18 150)" strokeWidth={1.5} strokeDasharray="4 4" fill="transparent" isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Energy load (kWh)">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={energy}>
              <CartesianGrid stroke="oklch(0.92 0.01 250)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="t" tick={{ fontSize: 10 }} stroke="oklch(0.5 0.02 250)" />
              <YAxis tick={{ fontSize: 10 }} stroke="oklch(0.5 0.02 250)" />
              <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid oklch(0.92 0.01 250)", fontSize: 12 }} />
              <Bar dataKey="value" fill="oklch(0.65 0.18 150)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Live machine telemetry (${machines.length} CNC units)`}>
          <div className="max-h-[440px] overflow-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-secondary text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">Asset</th>
                  <th className="px-3 py-2 text-left">Status</th>
                  <th className="px-3 py-2 text-right">Health</th>
                  <th className="px-3 py-2 text-right">Temp</th>
                  <th className="px-3 py-2 text-right">Vib</th>
                </tr>
              </thead>
              <tbody>
                {machines.map((m) => (
                  <tr key={m.id} className="border-t border-border">
                    <td className="px-3 py-2">
                      <div className="font-medium">{m.name}</div>
                      <div className="text-xs text-muted-foreground">{m.id} · {m.line}</div>
                    </td>
                    <td className="px-3 py-2"><StatusPill status={m.status} /></td>
                    <td className="px-3 py-2 text-right font-mono">{m.health}%</td>
                    <td className="px-3 py-2 text-right font-mono">{m.temp.toFixed(1)}°</td>
                    <td className="px-3 py-2 text-right font-mono">{m.vibration.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Vision QC stream">
          <ul className="space-y-2">
            {defectFeed.map((d) => (
              <li key={d.id} className="flex items-center justify-between rounded-md border border-border bg-card p-3">
                <div>
                  <div className="text-sm font-medium">{d.part} <span className="ml-2 font-mono text-xs text-muted-foreground">{d.id}</span></div>
                  <div className="text-xs text-muted-foreground">{d.line} · {d.time}</div>
                </div>
                <div className={`rounded-full px-2.5 py-1 text-xs font-medium ${d.defect === "Pass" ? "bg-success/15 text-success" : "bg-destructive/15 text-destructive"}`}>
                  {d.defect} · {(d.confidence * 100).toFixed(0)}%
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

export function Card({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-border bg-card p-5 ${className}`}>
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      {children}
    </div>
  );
}

function Stat({ label, value, sub, icon: Icon, accent }: { label: string; value: string; sub: string; icon: any; accent: "primary" | "destructive" | "warning" | "success" }) {
  const colorMap = {
    primary: "text-primary bg-primary/10",
    destructive: "text-destructive bg-destructive/10",
    warning: "text-warning bg-warning/15",
    success: "text-success bg-success/10",
  };
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${colorMap[accent]}`}><Icon className="h-4 w-4" /></div>
      </div>
      <div className="mt-3 font-display text-3xl font-bold">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{sub}</div>
    </div>
  );
}

export function StatusPill({ status }: { status: "running" | "warning" | "critical" | "idle" }) {
  const map = {
    running: "bg-success/15 text-success",
    warning: "bg-warning/20 text-warning-foreground",
    critical: "bg-destructive/15 text-destructive",
    idle: "bg-muted text-muted-foreground",
  } as const;
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${map[status]}`}><span className="h-1.5 w-1.5 rounded-full bg-current" />{status}</span>;
}
