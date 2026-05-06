// AppSync subscriptions for real-time machine state updates.

export const onMachineStateUpdated = /* GraphQL */ `
  subscription OnMachineStateUpdated($machine_id: ID) {
    onMachineStateUpdated(machine_id: $machine_id) {
      machine_id
      plant_id
      status
      health_score
      last_telemetry {
        vibration_mms
        current_amps
        coolant_lmin
        acoustic_db
      }
      active_alerts
      updated_at
    }
  }
`;
