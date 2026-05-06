import { createFileRoute } from "@tanstack/react-router";
import { Card } from "./dashboard.index";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { generateTimeSeries } from "@/lib/mockData";

export const Route = createFileRoute("/dashboard/sustainability")({ component: Sus });

function Sus() {
  const energy = generateTimeSeries(24, 110, 40);
  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-mono uppercase text-muted-foreground">Module 5 · Bedrock Agent Core</p>
        <h2 className="mt-1 font-display text-3xl font-bold">Sustainability & ESG</h2>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        {[
          { l: "Energy saved (mo)", v: "14.8%" },
          { l: "CO₂ avoided", v: "32.4 t" },
          { l: "Waste reduction", v: "11%" },
          { l: "Carbon score", v: "A−" },
        ].map((s) => (
          <div key={s.l} className="rounded-xl border border-border bg-card p-5">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">{s.l}</p>
            <p className="mt-2 font-display text-3xl font-bold text-success">{s.v}</p>
          </div>
        ))}
      </div>

      <Card title="Plant energy consumption (24h, kWh)">
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={energy}>
            <defs>
              <linearGradient id="ge" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="oklch(0.65 0.18 150)" stopOpacity={0.5} />
                <stop offset="100%" stopColor="oklch(0.65 0.18 150)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="oklch(0.92 0.01 250)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="t" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
            <Area type="monotone" dataKey="value" stroke="oklch(0.65 0.18 150)" strokeWidth={2} fill="url(#ge)" />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      <Card title="GenAI recommendations (Bedrock + Claude 3 Sonnet)">
        <ul className="space-y-3 text-sm">
          {[
            "Shift 18% of CNC-02 load to off-peak window 02:00–05:00 — projected saving Rs.1.2L/mo.",
            "Replace CNV-01 motor with IE4-rated unit; payback in 11 months at current duty cycle.",
            "Compressor leak detected near Line B (ultrasonic anomaly) — fixing saves 4.2 kWh/h.",
          ].map((r, i) => (
            <li key={i} className="flex gap-3 rounded-lg border border-border bg-card p-3">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">{i + 1}</div>
              <p>{r}</p>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
