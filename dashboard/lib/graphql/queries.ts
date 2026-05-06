// GraphQL operations for FactoryMind AppSync API.
// Schema lives at infrastructure/cdk/schema/factorymind.graphql.

export const getMachineState = /* GraphQL */ `
  query GetMachineState($machine_id: ID!) {
    getMachineState(machine_id: $machine_id) {
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
