import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { DigitalTwin3D } from "@/components/DigitalTwin3D";
import { initialMachines, tickMachine, type Machine } from "@/lib/mockData";
import { Button } from "@/components/ui/button";
import { generateFaultReport } from "@/lib/report";
import { Download, RotateCcw } from "lucide-react";
import { Card, StatusPill } from "./dashboard.index";

export const Route = createFileRoute("/dashboard/twin")({
  component: TwinPage,
});

function TwinPage() {
  const [machines, setMachines] = useState<Machine[]>(initialMachines);
  const [selectedId, setSelectedId] = useState<string | null>("PRS-01");

  useEffect(() => {
    const id = setInterval(() => setMachines((ms) => ms.map(tickMachine)), 1500);
    return () => clearInterval(id);
  }, []);

  const selected = machines.find((m) => m.id === selectedId) ?? machines[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-mono uppercase text-muted-foreground">Module 2 · Live Digital Twin</p>
          <h2 className="mt-1 font-display text-3xl font-bold">Factory Floor — 3D Replica</h2>
          <p className="mt-1 text-sm text-muted-foreground">Synced via AWS IoT Device Shadow · drag to orbit · click an asset to inspect.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setSelectedId(null)}><RotateCcw className="mr-2 h-4 w-4" /> Reset view</Button>
          <Button onClick={() => generateFaultReport(machines)}><Download className="mr-2 h-4 w-4" /> Export Report</Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="overflow-hidden rounded-xl border border-border bg-white shadow-sm" style={{ height: 560 }}>
          <DigitalTwin3D machines={machines} selectedId={selectedId} onSelect={setSelectedId} />
        </div>

        <div className="space-y-4">
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
                <Field k="Temperature" v={`${selected.temp.toFixed(1)}°C`} />
                <Field k="Vibration" v={`${selected.vibration.toFixed(2)} mm/s`} />
                <Field k="Load" v={`${selected.load.toFixed(0)}%`} />
                <Field k="RPM" v={selected.rpm.toFixed(0)} />
                <Field k="Energy" v={`${selected.energy.toFixed(1)} kWh`} />
              </dl>
              {selected.predictedFailureHours && (
                <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs">
                  <div className="font-semibold text-destructive">⚠ Predicted failure in ~{selected.predictedFailureHours}h</div>
                  <p className="mt-1 text-foreground/80">LSTM model confidence: 92%. Auto-issued work order.</p>
                </div>
              )}
            </div>
          </Card>

          <Card title="All assets">
            <ul className="space-y-1.5">
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
