import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "./dashboard.index";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { useLiveMachines } from "@/lib/useLiveMachines";
import { generateClient } from "aws-amplify/api";
import { chatWithAssistantMutation } from "@/lib/graphql/assistant";
import type { Machine } from "@/lib/mockData";

export const Route = createFileRoute("/dashboard/sustainability")({ component: Sus });

// Energy constants — keep aligned with shared/constants.py.
const CARBON_KG_PER_KWH = 0.82;
const ENERGY_COST_INR_PER_KWH = 8.5;

// Module-scoped rolling 24h window so the chart survives remount.
let ENERGY_HIST: { t: string; value: number }[] | null = null;
const ENERGY_POINTS = 24;

function pushEnergyPoint(totalKwh: number) {
  const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (!ENERGY_HIST) {
    ENERGY_HIST = Array.from({ length: ENERGY_POINTS }, (_, i) => ({
      t: new Date(Date.now() - (ENERGY_POINTS - i) * 60000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      value: Math.max(0, totalKwh + (Math.random() - 0.5) * totalKwh * 0.2),
    }));
  }
  ENERGY_HIST = [...ENERGY_HIST.slice(1), { t, value: totalKwh }];
  return ENERGY_HIST;
}

function fallbackRecommendations(machines: Machine[]): string[] {
  const idle = machines.filter((m) => m.status === "idle").map((m) => m.id);
  const high = [...machines].sort((a, b) => b.energy - a.energy).slice(0, 3);
  const out: string[] = [];
  if (idle.length > 0) {
    out.push(`Power down ${idle.length} idle machines (${idle.slice(0, 3).join(", ")}${idle.length > 3 ? ", …" : ""}) — saves ~${(idle.length * 1.2).toFixed(1)} kWh/h.`);
  }
  if (high.length) {
    out.push(`Top energy consumers: ${high.map((m) => `${m.id} (${m.energy.toFixed(1)} kWh)`).join(", ")} — schedule audits.`);
  }
  out.push(`Shift heavy CNC operations to off-peak window 02:00–05:00 — projected saving ₹${(machines.length * 240).toLocaleString()}/mo.`);
  return out;
}

function Sus() {
  const { machines, loading, live } = useLiveMachines();
  const [chartData, setChartData] = useState<{ t: string; value: number }[]>([]);
  const [recs, setRecs] = useState<string[] | null>(null);
  const [recsErr, setRecsErr] = useState<string | null>(null);
  const [recsLoading, setRecsLoading] = useState(false);
  const [usingFallback, setUsingFallback] = useState(false);
  const machinesRef = useRef(machines);
  machinesRef.current = machines;

  // Push a new energy sample every 60 s.
  useEffect(() => {
    const tick = () => {
      const total = machinesRef.current.reduce((s, m) => s + m.energy, 0);
      setChartData(pushEnergyPoint(total));
    };
    tick();
    const id = setInterval(tick, 60000);
    return () => clearInterval(id);
  }, []);

  const stats = useMemo(() => {
    const totalKwh = machines.reduce((s, m) => s + m.energy, 0);
    const idleKwh = machines.filter((m) => m.status === "idle").reduce((s, m) => s + m.energy, 0);
    // Daily extrapolation: kWh-per-hour × 24.
    const dailyKwh = totalKwh * 24;
    const dailyCo2Kg = dailyKwh * CARBON_KG_PER_KWH;
    const dailyCostInr = dailyKwh * ENERGY_COST_INR_PER_KWH;
    const wastePct = totalKwh > 0 ? (idleKwh / totalKwh) * 100 : 0;
    return { totalKwh, dailyKwh, dailyCo2Kg, dailyCostInr, wastePct };
  }, [machines]);

  // Ask the AgentCore assistant for recommendations on first load + every refresh.
  useEffect(() => {
    if (!machines.length || loading) return;
    let cancelled = false;
    setRecsLoading(true);
    setRecsErr(null);
    const idleIds = machines.filter((m) => m.status === "idle").slice(0, 5).map((m) => m.id);
    const worstHealth = [...machines].sort((a, b) => a.health - b.health).slice(0, 3).map((m) => `${m.id} (h=${m.health}%)`);
    const prompt = (
      `As the FactoryMind Sustainability Manager, return 3-5 short bullet recommendations to ` +
      `cut energy/carbon for PLANT-001. Live snapshot: total ${stats.totalKwh.toFixed(1)} kWh/h, ` +
      `daily ~${stats.dailyKwh.toFixed(0)} kWh, idle waste ${stats.wastePct.toFixed(1)}%, ` +
      `idle machines: ${idleIds.join(", ") || "none"}, lowest-health: ${worstHealth.join(", ")}. ` +
      `Reply ONLY with a markdown bullet list (one line each, no preamble).`
    );
    const client = generateClient();
    client
      .graphql({
        query: chatWithAssistantMutation,
        variables: {
          input: { message: prompt, session_id: `sus-${Date.now().toString(36).padStart(33, "0").slice(-33)}`, history: [] },
        },
      })
      .then((res: any) => {
        if (cancelled) return;
        const answer: string = res?.data?.chatWithAssistant?.answer ?? "";
        const items = answer
          .split(/\r?\n/)
          .map((l) => l.replace(/^[\s\-*•\d.]+/, "").trim())
          .filter((l) => l.length > 6);
        if (items.length) {
          setRecs(items.slice(0, 5));
          setUsingFallback(false);
        } else {
          setRecs(fallbackRecommendations(machinesRef.current));
          setUsingFallback(true);
        }
      })
      .catch((err: any) => {
        if (cancelled) return;
        setRecsErr(err?.errors?.[0]?.message ?? err?.message ?? String(err));
        setRecs(fallbackRecommendations(machinesRef.current));
        setUsingFallback(true);
      })
      .finally(() => {
        if (!cancelled) setRecsLoading(false);
      });
    return () => { cancelled = true; };
  }, [machines.length, loading, stats.totalKwh.toFixed(0)]);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-mono uppercase text-muted-foreground">Module 5 · Bedrock AgentCore + Claude Sonnet 4.5</p>
        <h2 className="mt-1 font-display text-3xl font-bold">
          Sustainability & ESG
          <span className={`ml-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 align-middle text-xs font-medium ${live ? "bg-success/15 text-success" : "bg-muted text-muted-foreground"}`}>
            <span className={`h-1.5 w-1.5 rounded-full bg-current ${live ? "pulse-dot" : ""}`} />
            {live ? "Live" : loading ? "Connecting…" : "Demo"}
          </span>
        </h2>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <KpiCard l="Live load" v={`${stats.totalKwh.toFixed(1)} kWh/h`} accent="success" />
        <KpiCard l="Daily CO₂" v={`${(stats.dailyCo2Kg / 1000).toFixed(2)} t`} accent="success" />
        <KpiCard l="Idle waste" v={`${stats.wastePct.toFixed(1)}%`} accent={stats.wastePct > 10 ? "warning" : "success"} />
        <KpiCard l="Daily cost" v={`₹${(stats.dailyCostInr / 1000).toFixed(1)}k`} accent="success" />
      </div>

      <Card title="Plant energy consumption (rolling 24 samples, kWh/h)">
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={chartData}>
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
            <Area type="monotone" dataKey="value" stroke="oklch(0.65 0.18 150)" strokeWidth={2} fill="url(#ge)" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      <Card title="GenAI recommendations (Bedrock AgentCore)">
        {recsLoading && (
          <p className="text-sm text-muted-foreground">Asking the Sustainability agent…</p>
        )}
        {recsErr && (
          <p className="text-xs text-destructive">⚠ {recsErr} — showing rule-based fallback.</p>
        )}
        {recs && (
          <ul className="space-y-3 text-sm">
            {recs.map((r, i) => (
              <li key={i} className="flex gap-3 rounded-lg border border-border bg-card p-3">
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">{i + 1}</div>
                <p>{r}</p>
              </li>
            ))}
          </ul>
        )}
        {recs && (
          <p className="mt-3 text-xs text-muted-foreground">
            {usingFallback ? "Source: rule-based fallback" : "Source: Bedrock AgentCore Runtime · Claude Sonnet 4.5"}
          </p>
        )}
      </Card>
    </div>
  );
}

function KpiCard({ l, v, accent }: { l: string; v: string; accent?: "success" | "warning" }) {
  const tone = accent === "warning" ? "text-warning" : accent === "success" ? "text-success" : "";
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{l}</p>
      <p className={`mt-2 font-display text-3xl font-bold ${tone}`}>{v}</p>
    </div>
  );
}
