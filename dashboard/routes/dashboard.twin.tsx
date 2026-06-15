import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { DigitalTwin3D } from "@/components/DigitalTwin3D";
import { Button } from "@/components/ui/button";
import { generateFaultReport } from "@/lib/report";
import { useLiveMachines } from "@/lib/useLiveMachines";
import { Download, RotateCcw } from "lucide-react";
import { Card, StatusPill } from "./dashboard.index";

export const Route = createFileRoute("/dashboard/twin")({
  component: TwinPage,
});

function TwinPage() {
  const { machines, live, loading } = useLiveMachines();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = machines.find((m) => m.id === selectedId) ?? machines[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-mono uppercase text-muted-foreground">Module 2 · Live Digital Twin</p>
          <h2 className="mt-1 font-display text-3xl font-bold">
            Factory Floor — 3D Replica
            <span className={`ml-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 align-middle text-xs font-medium ${live ? "bg-success/15 text-success" : "bg-muted text-muted-foreground"}`}>
              <span className={`h-1.5 w-1.5 rounded-full bg-current ${live ? "pulse-dot" : ""}`} />
              {live ? "Live" : loading ? "Connecting…" : "Demo"}
            </span>
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {machines.length} CNC units · synced via AWS IoT Core + AppSync · drag to orbit, click an asset to inspect.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setSelectedId(null)}><RotateCcw className="mr-2 h-4 w-4" /> Reset view</Button>
          <Button onClick={() => generateFaultReport(machines)} disabled={loading}><Download className="mr-2 h-4 w-4" /> Export Report</Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="overflow-hidden rounded-xl border border-border bg-white shadow-sm" style={{ height: 560 }}>
          <DigitalTwin3D machines={machines} selectedId={selectedId} onSelect={setSelectedId} />
        </div>

        <div className="space-y-4">
          {selected && (
            <Card title="Asset inspector">
              <div className="space-y-3">
                <div>
                  <div className="text-xs text-muted-foreground">Selected</div>
                  <div className="font-display text-xl font-bold">{selected.name}</div>
                  <div className="font-mono text-xs text-muted-foreground">{selected.id} · {selected.line}</div>
                </div>
                <StatusPill status={selected.status} />
                <dl className="grid grid-cols-2 gap-3 pt-2 text-sm">
                  <Field k="Health" v={`${selected.health}%`} />
                  <Field k="Vibration" v={`${selected.vibration.toFixed(2)} mm/s`} />
                  <Field k="Current" v={selected.current != null ? `${selected.current.toFixed(1)} A` : "—"} />
                  <Field k="Coolant" v={selected.coolant != null ? `${selected.coolant.toFixed(1)} L/min` : "—"} />
                  <Field k="Acoustic" v={selected.acoustic != null ? `${selected.acoustic.toFixed(0)} dB` : "—"} />
                </dl>
                {selected.predictedFailureHours && (
                  <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs">
                    <div className="font-semibold text-destructive">⚠ Predicted failure in ~{selected.predictedFailureHours}h</div>
                    <p className="mt-1 text-foreground/80">LSTM model confidence: 92%. Auto-issued work order.</p>
                  </div>
                )}
              </div>
            </Card>
          )}

          <Card title={`All assets (${machines.length})`}>
            <ul className="max-h-[360px] space-y-1.5 overflow-auto">
              {machines.map((m) => (
                <li
                  key={m.id}
                  onClick={() => setSelectedId(m.id)}
                  className={`flex cursor-pointer items-center justify-between rounded-md px-2 py-1.5 text-sm transition ${
                    selectedId === m.id ? "bg-primary/10" : "hover:bg-secondary"
                  }`}
                >
                  <span className="truncate"><span className="font-mono text-xs text-muted-foreground">{m.id}</span> {m.name}</span>
                  <StatusPill status={m.status} />
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Field({ k, v }: { k: string; v: string | number }) {
  return (
    <div className="rounded-md border border-border p-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{k}</div>
      <div className="mt-0.5 font-mono text-sm font-semibold">{v}</div>
    </div>
  );
}
