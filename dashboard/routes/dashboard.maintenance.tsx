import { createFileRoute } from "@tanstack/react-router";
import { workOrders, generateTimeSeries } from "@/lib/mockData";
import { Card } from "./dashboard.index";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from "recharts";
import { Button } from "@/components/ui/button";
import { generateFaultReport } from "@/lib/report";
import { initialMachines } from "@/lib/mockData";
import { Download } from "lucide-react";

export const Route = createFileRoute("/dashboard/maintenance")({ component: Maint });

function Maint() {
  const series = generateTimeSeries(40, 65, 30);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-xs font-mono uppercase text-muted-foreground">Module 4 · LSTM Forecasting</p>
          <h2 className="mt-1 font-display text-3xl font-bold">Predictive Maintenance</h2>
        </div>
        <Button onClick={() => generateFaultReport(initialMachines)}><Download className="mr-2 h-4 w-4" /> Download Fault Report</Button>
      </div>

      <Card title="Vibration forecast — PRS-01 (next 72h)">
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={series}>
            <CartesianGrid stroke="oklch(0.92 0.01 250)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="t" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
            <ReferenceLine y={90} stroke="oklch(0.6 0.24 25)" strokeDasharray="4 4" label={{ value: "Failure threshold", fontSize: 10, fill: "oklch(0.6 0.24 25)" }} />
            <Line type="monotone" dataKey="value" stroke="oklch(0.55 0.22 260)" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="predicted" stroke="oklch(0.78 0.16 75)" strokeWidth={2} strokeDasharray="5 5" dot={false} />
          </LineChart>
        </ResponsiveContainer>
        <div className="mt-3 flex gap-6 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-primary" /> Actual sensor</span>
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 border-t border-dashed border-warning" /> LSTM forecast</span>
        </div>
      </Card>

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
