// AppSync mutation that proxies to the FactoryMind assistant gateway Lambda,
// which in turn invokes the Bedrock AgentCore Runtime.
//
// Schema is added at deploy time by scripts/wire_appsync_assistant.py.

export const chatWithAssistantMutation = /* GraphQL */ `
  mutation ChatWithAssistant($input: AssistantChatInput!) {
    chatWithAssistant(input: $input) {
      session_id
      answer
      context_used
      model_id
      error
    }
  }
`;
