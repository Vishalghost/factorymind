// Hook that bridges live AppSync MachineState (50 CNC machines) into the
// new dashboard's Machine[] shape (consumed by the Overview/Twin/etc. pages).
//
// We keep the dashboard's existing Machine type intact so the rest of the
// UI keeps working unchanged; this hook overlays real telemetry on top of
// the synthetic positions/labels in mockData.

import { useEffect, useMemo, useState } from "react";
import { generateClient } from "aws-amplify/api";

import { type Machine } from "./mockData";
import { getMachineState } from "./graphql/queries";
import { onMachineStateUpdated } from "./graphql/subscriptions";
import type { MachineState, MachineStatus } from "./types";

// Real fleet IDs (must match scripts/seed_dummy_data.py + simulate_aerospace_cnc.py).
const MACHINE_IDS = Array.from(
  { length: 50 },
  (_, i) => `CNC-AERO-${String(i + 1).padStart(2, "0")}`,
);

// 50 deterministic positions on a 10x5 grid (centered at origin).
function gridPosition(idx: number): [number, number, number] {
  const cols = 10;
  const x = (idx % cols) - cols / 2;
  const z = Math.floor(idx / cols) - 2;
  return [x * 1.2, 0, z * 1.2];
}

function statusToUI(status: MachineStatus | null): Machine["status"] {
  switch (status) {
    case "RUNNING": return "running";
    case "FAULT": return "critical";
    case "MAINTENANCE": return "warning";
    case "IDLE":
    default: return "idle";
  }
}

// Map a backend MachineState onto the UI Machine type.
// Real fields ONLY — no synthesis. Anything the backend doesn't send
// (temp/rpm/load/energy) stays undefined and renders as "—" in the UI.
function toMachine(s: MachineState, fallback: Machine, idx: number): Machine {
  const tel = s.last_telemetry ?? null;
  // Backend stores health_score as a normalized 0..1 float (matching the
  // Pydantic model). The UI shows it as a percentage 0..100.
  // Tolerate both shapes in case future backends emit 0..100 directly.
  const rawHealth = s.health_score;
  let health = fallback.health;
  if (rawHealth != null) {
    health = Math.round(rawHealth <= 1 ? rawHealth * 100 : rawHealth);
  }
  const status = statusToUI(s.status);
  const [name, line] = nameForIdx(idx);
  return {
    id: s.machine_id,
    name,
    line,
    status,
    health,
    vibration: tel?.vibration_mms ?? fallback.vibration,
    current: tel?.current_amps ?? null,
    coolant: tel?.coolant_lmin ?? null,
    acoustic: tel?.acoustic_db ?? null,
    position: gridPosition(idx),
  };
}

function nameForIdx(idx: number): [string, string] {
  const lines = ["Line A", "Line B", "Line C"];
  const line = lines[idx % 3];
  return [`CNC Aero Mill ${idx + 1}`, line];
}

// Pre-data placeholder: idle, no synthesized telemetry. Real values land
// once AppSync delivers a MachineState; until then tiles render "—".
function placeholder(machineId: string, idx: number): Machine {
  const [name, line] = nameForIdx(idx);
  return {
    id: machineId,
    name,
    line,
    status: "idle",
    health: 100,
    vibration: 0,
    current: null,
    coolant: null,
    acoustic: null,
    position: gridPosition(idx),
  };
}

export type LiveFleet = {
  machines: Machine[];
  loading: boolean;
  live: boolean; // true once at least one AppSync record landed.
  error: string | null;
};

/**
 * Live 50-machine fleet, AppSync-backed. No mock fallback — if the backend is
 * silent the fleet stays on idle placeholders and `live` stays false, so the
 * UI can honestly show NO DATA instead of synthesizing motion.
 *
 * - On mount: parallel getMachineState queries for all 50 IDs.
 * - Then: subscribes to onMachineStateUpdated and patches the row in place.
 */
export function useLiveMachines(): LiveFleet {
  const [byId, setById] = useState<Record<string, Machine>>(() => {
    const init: Record<string, Machine> = {};
    MACHINE_IDS.forEach((id, i) => { init[id] = placeholder(id, i); });
    return init;
  });
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initial load + recurring poll. The AppSync `onMachineStateUpdated`
  // subscription fires only when somebody invokes the AppSync `updateMachineState`
  // mutation; the IoT ingestion Lambda writes straight to DynamoDB, so the
  // subscription never fires. Polling `getMachineState` every 6 s covers the
  // gap and keeps the UI honestly live.
  useEffect(() => {
    let cancelled = false;
    const client = generateClient();

    const refresh = async () => {
      try {
        const results = await Promise.all(
          MACHINE_IDS.map((id, idx) =>
            client
              .graphql({ query: getMachineState, variables: { machine_id: id } })
              .then((res: any) => res?.data?.getMachineState as MachineState | null)
              .then((state) => ({ idx, id, state }))
              .catch(() => ({ idx, id, state: null as MachineState | null })),
          ),
        );
        if (cancelled) return;
        let anyLive = false;
        setById((prev) => {
          const next: Record<string, Machine> = { ...prev };
          results.forEach(({ idx, id, state }) => {
            const fallback = prev[id] ?? placeholder(id, idx);
            if (state) {
              next[id] = toMachine(state, fallback, idx);
              if (state.last_telemetry || state.health_score != null) anyLive = true;
            }
          });
          return next;
        });
        if (anyLive) setLive(true);
        setLoading(false);
      } catch (e: any) {
        if (cancelled) return;
        setError(String(e?.message ?? e));
        setLoading(false);
      }
    };

    refresh();
    const id = setInterval(refresh, 6000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Live subscription — patches rows as IoT messages flow in.
  useEffect(() => {
    let sub: { unsubscribe: () => void } | null = null;
    try {
      const client = generateClient();
      sub = client
        .graphql({ query: onMachineStateUpdated })
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .subscribe?.({
          next: ({ data }: any) => {
            const m: MachineState | undefined = data?.onMachineStateUpdated;
            if (!m) return;
            const idx = MACHINE_IDS.indexOf(m.machine_id);
            if (idx < 0) return;
            setById((prev) => ({
              ...prev,
              [m.machine_id]: toMachine(m, prev[m.machine_id] ?? placeholder(m.machine_id, idx), idx),
            }));
            setLive(true);
          },
          error: (err: unknown) => {
            // eslint-disable-next-line no-console
            console.warn("onMachineStateUpdated error", err);
          },
        });
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("subscription setup failed", e);
    }
    return () => { sub?.unsubscribe(); };
  }, []);

  const machines = useMemo(() => MACHINE_IDS.map((id) => byId[id]), [byId]);
  return { machines, loading, live, error };
}
