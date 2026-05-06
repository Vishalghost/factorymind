import { useEffect, useState } from "react";
import { generateClient } from "aws-amplify/api";

import { MachineCard } from "../components/MachineCard";
import { getMachineState } from "../graphql/queries";
import { onMachineStateUpdated } from "../graphql/subscriptions";
import type { MachineState } from "../types";

const client = generateClient();

const MACHINE_IDS = Array.from(
  { length: 50 },
  (_, i) => `CNC-AERO-${String(i + 1).padStart(2, "0")}`,
);

/**
 * Plant overview: 50 machine cards in a responsive grid.
 *
 * Bootstraps initial state via GetMachineState query (one per machine), then
 * keeps the grid live via a single AppSync subscription on the parent
 * onMachineStateUpdated field.
 */
export function PlantOverview() {
  const [machines, setMachines] = useState<Record<string, MachineState>>({});
  const [loading, setLoading] = useState(true);

  // Initial load — fetch state for all 50 machines in parallel.
  useEffect(() => {
    let cancelled = false;
    Promise.all(
      MACHINE_IDS.map((id) =>
        client
          .graphql({ query: getMachineState, variables: { machine_id: id } })
          .then((res) => {
            // @ts-expect-error — Amplify GraphQL response typing is loose.
            return res.data?.getMachineState as MachineState | null;
          })
          .catch(() => null),
      ),
    ).then((results) => {
      if (cancelled) return;
      const next: Record<string, MachineState> = {};
      results.forEach((m, i) => {
        if (m) next[m.machine_id] = m;
        else next[MACHINE_IDS[i]] = _placeholder(MACHINE_IDS[i]);
      });
      setMachines(next);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  // Subscribe to all machine updates.
  useEffect(() => {
    const sub = client
      .graphql({ query: onMachineStateUpdated })
      // @ts-expect-error — Amplify v6 subscription typing.
      .subscribe({
        next: ({ data }: { data: { onMachineStateUpdated: MachineState } }) => {
          const m = data.onMachineStateUpdated;
          setMachines((prev) => ({ ...prev, [m.machine_id]: m }));
        },
        error: (err: unknown) => {
          // eslint-disable-next-line no-console
          console.warn("PlantOverview subscription error", err);
        },
      });
    return () => sub.unsubscribe();
  }, []);

  if (loading) {
    return <div className="empty">Loading plant state…</div>;
  }

  return (
    <>
      <h1>Plant Overview</h1>
      <p style={{ color: "var(--muted)", marginBottom: 20 }}>
        50 CNC machines · 3 production lines · Ti-6Al-4V titanium milling
      </p>
      <div className="grid">
        {MACHINE_IDS.map((id) => (
          <MachineCard key={id} machine={machines[id] ?? _placeholder(id)} />
        ))}
      </div>
    </>
  );
}

function _placeholder(machine_id: string): MachineState {
  return {
    machine_id,
    plant_id: "PLANT-001",
    status: "IDLE",
    health_score: null,
    last_telemetry: null,
    active_alerts: [],
    updated_at: null,
  };
}
