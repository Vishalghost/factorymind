import { createFileRoute, Link } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/Logo";
import { ArrowRight, Boxes, Cpu, Eye, Leaf, MessageSquare, ShieldCheck, Wrench, Zap } from "lucide-react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "FactoryMind — Unified AI Platform for Smart Manufacturing" },
      { name: "description", content: "5-in-1 manufacturing intelligence: Edge AI, Live Digital Twin, Vision QC, Predictive Maintenance, and GenAI." },
    ],
  }),
  component: Landing,
});

const MODULES = [
  { icon: Cpu, title: "Edge AI Inference", desc: "Sub-10ms on-device inference with ONNX + TF-Lite. No cloud round-trip." },
  { icon: Boxes, title: "Live Digital Twin", desc: "Real-time 3D replica of the factory floor synced with live IoT streams." },
  { icon: Eye, title: "Quality Vision AI", desc: "YOLOv8 computer vision for defect detection at >95% accuracy." },
  { icon: Wrench, title: "Predictive Maintenance", desc: "LSTM models predict failures 24-72h ahead and auto-issue work orders." },
  { icon: Leaf, title: "Sustainability + GenAI", desc: "Bedrock Agent Core tracks energy & waste with natural-language insight." },
];

const STATS = [
  { v: "Rs.50-80L", l: "Saved per plant / yr" },
  { v: ">95%", l: "Defect accuracy" },
  { v: "30-50%", l: "Downtime reduction" },
  { v: "<10ms", l: "Edge inference" },
];

function Landing() {
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-20 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <Logo />
          <nav className="hidden items-center gap-8 text-sm md:flex">
            <a href="#modules" className="text-muted-foreground hover:text-foreground">Modules</a>
            <a href="#impact" className="text-muted-foreground hover:text-foreground">Impact</a>
            <a href="#architecture" className="text-muted-foreground hover:text-foreground">Architecture</a>
          </nav>
          <div className="flex items-center gap-2">
            <Button asChild variant="ghost" size="sm"><Link to="/login">Sign in</Link></Button>
            <Button asChild size="sm"><Link to="/login">Launch dashboard <ArrowRight className="ml-1 h-3.5 w-3.5" /></Link></Button>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden gradient-mesh">
        <div className="absolute inset-0 grid-bg opacity-40" />
        <div className="relative mx-auto max-w-7xl px-6 py-24 md:py-32">
          <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card/70 px-3 py-1 text-xs font-medium backdrop-blur">
            <span className="relative inline-flex h-1.5 w-1.5 items-center justify-center text-primary pulse-dot">
              <span className="h-1.5 w-1.5 rounded-full bg-primary" />
            </span>
            Technoverse 2026 · Cognizant
          </div>
          <h1 className="mt-6 max-w-4xl font-display text-5xl font-bold leading-[1.05] tracking-tight md:text-7xl">
            The unified AI brain for the <span className="bg-gradient-to-r from-primary to-chart-5 bg-clip-text text-transparent">smart factory floor</span>.
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-muted-foreground">
            FactoryMind fuses Edge AI, a live 3D Digital Twin, Vision-based QC, Predictive Maintenance and Generative AI into one platform — turning blind, reactive plants into autonomous, self-healing operations.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Button asChild size="lg"><Link to="/login">Open live dashboard <ArrowRight className="ml-2 h-4 w-4" /></Link></Button>
            <Button asChild size="lg" variant="outline"><a href="#modules">Explore the 5 modules</a></Button>
          </div>

          <dl className="mt-16 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-border bg-border md:grid-cols-4">
            {STATS.map((s) => (
              <div key={s.l} className="bg-card p-6">
                <dt className="text-xs uppercase tracking-wider text-muted-foreground">{s.l}</dt>
                <dd className="mt-1 font-display text-3xl font-bold tracking-tight">{s.v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* Modules */}
      <section id="modules" className="mx-auto max-w-7xl px-6 py-24">
        <div className="mb-12 max-w-2xl">
          <p className="text-sm font-semibold uppercase tracking-wider text-primary">5-in-1 platform</p>
          <h2 className="mt-2 font-display text-4xl font-bold tracking-tight">One contract. Zero integration tax.</h2>
          <p className="mt-3 text-muted-foreground">No competitor unifies these capabilities under one roof. Each module ships independently and snaps together.</p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {MODULES.map(({ icon: Icon, title, desc }) => (
            <div key={title} className="group relative overflow-hidden rounded-2xl border border-border bg-card p-6 transition-shadow hover:shadow-lg">
              <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Icon className="h-5 w-5" />
              </div>
              <h3 className="font-display text-lg font-semibold">{title}</h3>
              <p className="mt-1.5 text-sm text-muted-foreground">{desc}</p>
              <div className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-primary to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
            </div>
          ))}
        </div>
      </section>

      {/* Impact */}
      <section id="impact" className="border-y border-border bg-secondary/40">
        <div className="mx-auto grid max-w-7xl gap-12 px-6 py-24 md:grid-cols-2">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wider text-primary">Quantified impact</p>
            <h2 className="mt-2 font-display text-4xl font-bold tracking-tight">From $50B annual loss to autonomous correction.</h2>
            <p className="mt-4 text-muted-foreground">Plants lose Rs.10-15 Lakhs per failure event. Manual QC misses 15-20% of defects. FactoryMind's agentic loop detects, diagnoses and acts — without waiting for a human.</p>
          </div>
          <div className="space-y-3">
            {[
              { i: ShieldCheck, t: "Agentic AI loop", d: "Bedrock Agent Core monitors streams, diagnoses anomalies and triggers corrective actions autonomously." },
              { i: Zap, t: "OTA model updates", d: "Push new edge models over-the-air with S3-backed versioning. No physical access required." },
              { i: MessageSquare, t: "Natural-language operations", d: '"Why did Line 3 slow down?" — get a reasoned, action-oriented answer powered by Claude 3 Sonnet.' },
            ].map(({ i: Icon, t, d }) => (
              <div key={t} className="flex gap-4 rounded-xl border border-border bg-card p-5">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground"><Icon className="h-5 w-5" /></div>
                <div>
                  <h4 className="font-semibold">{t}</h4>
                  <p className="mt-0.5 text-sm text-muted-foreground">{d}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Architecture */}
      <section id="architecture" className="mx-auto max-w-7xl px-6 py-24">
        <div className="mb-10">
          <p className="text-sm font-semibold uppercase tracking-wider text-primary">Architecture</p>
          <h2 className="mt-2 font-display text-4xl font-bold tracking-tight">Built on AWS, edge-first, AI-native.</h2>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {[
            { t: "Frontend", d: "React + TanStack Start. Real-time WebSockets. Role-based views (Operator / Manager / CXO)." },
            { t: "Backend", d: "FastAPI async REST. <50ms response. Direct ML pipeline integration." },
            { t: "Data", d: "PostgreSQL for telemetry & audit. MongoDB for high-frequency sensors." },
            { t: "AI / ML", d: "YOLOv8 vision · LSTM forecasting · ONNX runtime on Jetson / RPi." },
            { t: "GenAI", d: "Amazon Bedrock · Claude 3 Sonnet · RAG knowledge base · Guardrails." },
            { t: "Deploy", d: "Docker · ECS Fargate · IoT Device Shadow · OTA model rollout." },
          ].map((x) => (
            <div key={x.t} className="rounded-xl border border-border bg-card p-5">
              <div className="font-mono text-xs uppercase tracking-wider text-primary">{x.t}</div>
              <p className="mt-2 text-sm">{x.d}</p>
            </div>
          ))}
        </div>
        <div className="mt-12 flex justify-center">
          <Button asChild size="lg"><Link to="/login">Enter the live MVP <ArrowRight className="ml-2 h-4 w-4" /></Link></Button>
        </div>
      </section>

      <footer className="border-t border-border bg-card">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-6 py-8 text-sm text-muted-foreground md:flex-row">
          <Logo />
          <p>© 2026 Cognizant · Team FactoryMind · Technoverse Hackathon</p>
        </div>
      </footer>
    </div>
  );
}
