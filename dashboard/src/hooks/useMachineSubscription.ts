import { useEffect, useState } from "react";
import { generateClient } from "aws-amplify/api";

import { onMachineStateUpdated } from "../graphql/subscriptions";
import type { MachineState } from "../types";

const client = generateClient();

/**
 * Subscribe to live AppSync updates for one machine (or all if undefined).
 *
 * Returns the most recent MachineState received. Falls back to null until
 * the first subscription event lands.
 */
export function useMachineSubscription(machine_id?: string): MachineState | null {
  const [state, setState] = useState<MachineState | null>(null);

  useEffect(() => {
    const sub = client
      .graphql({
        query: onMachineStateUpdated,
        variables: { machine_id },
      })
      // @ts-expect-error — Amplify v6 typing for subscription observable is loose.
      .subscribe({
        next: ({ data }: { data: { onMachineStateUpdated: MachineState } }) => {
          setState(data.onMachineStateUpdated);
        },
        error: (err: unknown) => {
          // eslint-disable-next-line no-console
          console.warn("AppSync subscription error", err);
        },
      });

    return () => sub.unsubscribe();
  }, [machine_id]);

  return state;
}
