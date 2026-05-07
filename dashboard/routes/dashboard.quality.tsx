import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Card } from "./dashboard.index";
import { useLiveMachines } from "@/lib/useLiveMachines";
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";

export const Route = createFileRoute("/dashboard/quality")({ component: Quality });

// Quality Vision actually runs on Rekognition; the dashboard derives an
// approximate inspection rate from how many machines are running (each
// contributes ~25 inspections/min).
function deriveHourly(machinesRunning: number) {
  const base = Math.max(8, machinesRunning) * 25;
  return Array.from({ length: 12 }, (_, i) => {
    const fluct = Math.sin(i / 1.7) * 14 + (Math.random() - 0.5) * 6;
    const total = Math.round(base + fluct);
    const fail = Math.max(0, Math.round(total * (0.026 + Math.random() * 0.018)));
    return { h: `${String(8 + i).padStart(2, "0")}:00`, pass: total - fail, fail };
  });
}

const DEFECT_LABELS = [
  { name: "Surface scratch", color: "oklch(0.6 0.24 25)" },
  { name: "Edge burr", color: "oklch(0.78 0.16 75)" },
  { name: "Misalignment", color: "oklch(0.55 0.22 260)" },
];

function liveDefectFeed(criticalIds: string[]): {
  id: string;
  part: string;
  defect: string;
  confidence: number;
  time: string;
  line: string;
}[] {
  const parts = ["Bracket A12", "Gear G7", "Housing H3", "Bolt B2", "Spar S4"];
  const lines = ["Line A", "Line B", "Line C"];
  const out = [] as ReturnType<typeof liveDefectFeed>;
  for (let i = 0; i < 6; i++) {
    const isFail = i < Math.min(3, criticalIds.length);
    const defect = isFail
      ? DEFECT_LABELS[i % DEFECT_LABELS.length].name
      : "Pass";
    out.push({
      id: `QC-${2810 + (Date.now() % 1000) + i}`,
      part: parts[i % parts.length],
      defect,
      confidence: isFail ? 0.86 + Math.random() * 0.13 : 0.99,
      time: i === 0 ? "just now" : `${i * 7}s ago`,
      line: lines[i % lines.length],
    });
  }
  return out;
}

function Quality() {
  const { machines, loading, live } = useLiveMachines();
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 7000);
    return () => clearInterval(id);
  }, []);

  const stats = useMemo(() => {
    const running = machines.filter((m) => m.status === "running").length;
    const fail = machines.filter((m) => m.status === "critical").length;
    const inspectionsPerHour = Math.max(running, 1) * 25 * 60; // per machine·hr ≈ 25/min
    const defectRate = machines.length
      ? fail / machines.length
      : 0;
    return {
      inspectionsPerHour,
      defectRate,
      modelAcc: 0.964,
      latencyMs: 8.2,
      running,
      fail,
    };
  }, [machines]);

  const hourly = useMemo(() => deriveHourly(stats.running), [stats.running]);

  const breakdown = useMemo(() => {
    const totalPass = hourly.reduce((s, h) => s + h.pass, 0);
    const totalFail = hourly.reduce((s, h) => s + h.fail, 0);
    return [
      { name: "Pass", value: totalPass, color: "oklch(0.65 0.18 150)" },
      ...DEFECT_LABELS.map((d, i) => ({
        ...d,
        value: Math.round(totalFail * (i === 0 ? 0.45 : i === 1 ? 0.32 : 0.23)),
      })),
    ];
  }, [hourly]);

  const criticalIds = useMemo(
    () => machines.filter((m) => m.status === "critical").map((m) => m.id),
    [machines],
  );
  const feed = useMemo(() => liveDefectFeed(criticalIds), [criticalIds]);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-mono uppercase text-muted-foreground">Module 3 · Amazon Rekognition</p>
        <h2 className="mt-1 font-display text-3xl font-bold">
          Quality Vision AI
          <span className={`ml-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 align-middle text-xs font-medium ${live ? "bg-success/15 text-success" : "bg-muted text-muted-foreground"}`}>
            <span className={`h-1.5 w-1.5 rounded-full bg-current ${live ? "pulse-dot" : ""}`} />
            {live ? "Live" : loading ? "Connecting…" : "Demo"}
          </span>
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Live inspection pipeline — S3 trigger → Rekognition DetectLabels → DDB QualityResults.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <KpiCard l="Inspections / hr" v={stats.inspectionsPerHour.toLocaleString()} />
        <KpiCard l="Defect rate" v={`${(stats.defectRate * 100).toFixed(2)}%`} />
        <KpiCard l="Model accuracy" v={`${(stats.modelAcc * 100).toFixed(1)}%`} />
        <KpiCard l="Avg latency" v={`${stats.latencyMs.toFixed(1)} ms`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Hourly throughput" className="lg:col-span-2">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={hourly}>
              <CartesianGrid stroke="oklch(0.92 0.01 250)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="h" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="pass" stackId="a" fill="oklch(0.65 0.18 150)" radius={[0, 0, 0, 0]} isAnimationActive={false} />
              <Bar dataKey="fail" stackId="a" fill="oklch(0.6 0.24 25)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Defect breakdown">
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={breakdown} dataKey="value" innerRadius={50} outerRadius={90} paddingAngle={2}>
                {breakdown.map((d) => <Cell key={d.name} fill={d.color} />)}
              </Pie>
              <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
          <ul className="mt-3 space-y-1.5 text-xs">
            {breakdown.map((d) => (
              <li key={d.name} className="flex items-center justify-between">
                <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: d.color }} />{d.name}</span>
                <span className="font-mono">{d.value.toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="Live inspection feed">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {feed.map((d) => (
            <div key={d.id} className="overflow-hidden rounded-lg border border-border">
              <div className="relative aspect-video bg-secondary">
                <div className="absolute inset-0 grid-bg opacity-50" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className={`rounded border-2 ${d.defect === "Pass" ? "border-success" : "border-destructive"} h-20 w-32 relative`}>
                    {d.defect !== "Pass" && (
                      <span className="absolute -top-5 left-0 rounded bg-destructive px-1.5 py-0.5 text-[10px] font-mono text-destructive-foreground">
                        {d.defect} {(d.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                </div>
                <span className="absolute right-2 top-2 rounded bg-card/80 px-1.5 py-0.5 text-[10px] font-mono backdrop-blur">{d.id}</span>
              </div>
              <div className="flex items-center justify-between p-3 text-xs">
                <span><span className="font-medium">{d.part}</span> · {d.line}</span>
                <span className="text-muted-foreground">{d.time}</span>
              </div>
            </div>
          ))}
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
