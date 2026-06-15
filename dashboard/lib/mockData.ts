// Mock real-time data generators for FactoryMind

export type Machine = {
  id: string;
  name: string;
  line: string;
  status: "running" | "warning" | "critical" | "idle";
  health: number; // 0-100
  vibration: number;
  // Real telemetry pushed from the backend (null/undefined => render "—").
  current?: number | null; // spindle current, A
  coolant?: number | null; // coolant flow, L/min
  acoustic?: number | null; // acoustic emission, dB
  // Display-only fields the backend does NOT provide. Optional so the UI can
  // honestly show "—" instead of synthesizing a plausible-looking value.
  temp?: number;
  rpm?: number;
  load?: number;
  energy?: number;
  position: [number, number, number];
  predictedFailureHours?: number;
};

export const initialMachines: Machine[] = [
  { id: "CNC-01", name: "CNC Mill Alpha", line: "Line A", status: "running", health: 92, temp: 68, vibration: 1.2, rpm: 8400, load: 72, energy: 14.2, position: [-3, 0, -2] },
  { id: "CNC-02", name: "CNC Mill Beta", line: "Line A", status: "warning", health: 67, temp: 84, vibration: 3.8, rpm: 9100, load: 88, energy: 18.6, position: [-1, 0, -2], predictedFailureHours: 36 },
  { id: "ROB-01", name: "Welding Robot R1", line: "Line B", status: "running", health: 95, temp: 55, vibration: 0.8, rpm: 0, load: 60, energy: 9.4, position: [1, 0, -2] },
  { id: "PRS-01", name: "Hydraulic Press", line: "Line B", status: "critical", health: 41, temp: 102, vibration: 6.2, rpm: 0, load: 95, energy: 24.1, position: [3, 0, -2], predictedFailureHours: 8 },
  { id: "CNV-01", name: "Conveyor Main", line: "Line C", status: "running", health: 88, temp: 42, vibration: 0.4, rpm: 1200, load: 55, energy: 4.2, position: [-3, 0, 1] },
  { id: "INJ-01", name: "Injection Molder", line: "Line C", status: "running", health: 78, temp: 195, vibration: 1.6, rpm: 0, load: 70, energy: 22.8, position: [0, 0, 1] },
  { id: "PKG-01", name: "Packaging Unit", line: "Line C", status: "idle", health: 99, temp: 28, vibration: 0.1, rpm: 0, load: 0, energy: 1.1, position: [3, 0, 1] },
];

export function tickMachine(m: Machine): Machine {
  const j = (v: number, range: number) => v + (Math.random() - 0.5) * range;
  return {
    ...m,
    temp: Math.max(20, j(m.temp, 1.5)),
    vibration: Math.max(0, j(m.vibration, 0.2)),
    load: Math.min(100, Math.max(0, j(m.load, 2))),
    energy: Math.max(0, j(m.energy, 0.3)),
    rpm: m.rpm > 0 ? Math.max(0, j(m.rpm, 50)) : 0,
  };
}

export const defectFeed = [
  { id: "QC-2814", part: "Bracket A12", defect: "Surface scratch", confidence: 0.97, time: "2s ago", line: "Line A" },
  { id: "QC-2813", part: "Gear G7", defect: "Edge burr", confidence: 0.91, time: "11s ago", line: "Line B" },
  { id: "QC-2812", part: "Housing H3", defect: "Pass", confidence: 0.99, time: "18s ago", line: "Line C" },
  { id: "QC-2811", part: "Bracket A12", defect: "Misalignment", confidence: 0.88, time: "32s ago", line: "Line A" },
  { id: "QC-2810", part: "Bolt B2", defect: "Pass", confidence: 0.99, time: "44s ago", line: "Line B" },
];

export const workOrders = [
  { id: "WO-1042", machine: "PRS-01", priority: "P1", task: "Replace hydraulic seal — predicted failure in 8h", eta: "8h", status: "open" },
  { id: "WO-1041", machine: "CNC-02", priority: "P2", task: "Spindle bearing inspection — vibration spike detected", eta: "36h", status: "scheduled" },
  { id: "WO-1040", machine: "INJ-01", priority: "P3", task: "Routine lubrication", eta: "5d", status: "scheduled" },
];

export function generateTimeSeries(points = 30, base = 70, range = 20) {
  const now = Date.now();
  return Array.from({ length: points }, (_, i) => ({
    t: new Date(now - (points - i) * 60000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    value: Math.round(base + Math.sin(i / 3) * range * 0.4 + (Math.random() - 0.5) * range * 0.5),
    predicted: Math.round(base + Math.sin(i / 3) * range * 0.4),
  }));
}
