import { createFileRoute } from "@tanstack/react-router";
import { Card } from "./dashboard.index";
import { defectFeed } from "@/lib/mockData";
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid } from "recharts";

export const Route = createFileRoute("/dashboard/quality")({ component: Quality });

const DEFECT_BREAKDOWN = [
  { name: "Pass", value: 962, color: "oklch(0.65 0.18 150)" },
  { name: "Surface scratch", value: 18, color: "oklch(0.6 0.24 25)" },
  { name: "Edge burr", value: 11, color: "oklch(0.78 0.16 75)" },
  { name: "Misalignment", value: 9, color: "oklch(0.55 0.22 260)" },
];

const HOURLY = Array.from({ length: 12 }, (_, i) => ({
  h: `${i + 8}:00`,
  pass: 80 + Math.round(Math.random() * 20),
  fail: Math.round(Math.random() * 8),
}));

function Quality() {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-mono uppercase text-muted-foreground">Module 3 · YOLOv8 Vision</p>
        <h2 className="mt-1 font-display text-3xl font-bold">Quality Vision AI</h2>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        {[
          { l: "Inspections / hr", v: "1,284" },
          { l: "Defect rate", v: "3.6%" },
          { l: "Model accuracy", v: "96.4%" },
          { l: "Avg latency", v: "8.2 ms" },
        ].map((s) => (
          <div key={s.l} className="rounded-xl border border-border bg-card p-5">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">{s.l}</p>
            <p className="mt-2 font-display text-3xl font-bold">{s.v}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Hourly throughput" className="lg:col-span-2">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={HOURLY}>
              <CartesianGrid stroke="oklch(0.92 0.01 250)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="h" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="pass" stackId="a" fill="oklch(0.65 0.18 150)" radius={[0, 0, 0, 0]} />
              <Bar dataKey="fail" stackId="a" fill="oklch(0.6 0.24 25)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Defect breakdown">
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={DEFECT_BREAKDOWN} dataKey="value" innerRadius={50} outerRadius={90} paddingAngle={2}>
                {DEFECT_BREAKDOWN.map((d) => <Cell key={d.name} fill={d.color} />)}
              </Pie>
              <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
          <ul className="mt-3 space-y-1.5 text-xs">
            {DEFECT_BREAKDOWN.map((d) => (
              <li key={d.name} className="flex items-center justify-between">
                <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: d.color }} />{d.name}</span>
                <span className="font-mono">{d.value}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="Live inspection feed">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {defectFeed.map((d) => (
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
