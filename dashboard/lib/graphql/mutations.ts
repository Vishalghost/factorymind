// GraphQL mutations. Operators rarely call these directly — Lambda agents
// publish state via AppSync after every Digital Twin sync.

export const updateMachineState = /* GraphQL */ `
  mutation UpdateMachineState($input: MachineStateInput!) {
    updateMachineState(input: $input) {
      machine_id
      plant_id
      status
      health_score
      updated_at
    }
  }
`;
