# Architecture and trust boundaries

## Components

| Component | Responsibility |
|---|---|
| Hermes | Agent loop, tool selection, sessions, and workflow orchestration |
| Ollama | Local model loading and OpenAI-compatible inference endpoint |
| Discord gateway | Persistent remote messaging and session routing |
| Tool layer | Web retrieval, terminal actions, files, memory, and automation |
| Linux host | Service management, logging, storage, and hardware access |

## Request flow

1. A request enters through the local CLI or Discord gateway.
2. Hermes assembles the allowed context and tool definitions.
3. The selected local model receives the request through Ollama.
4. Hermes executes approved tool calls and returns their results to the model.
5. The final response is returned through the originating interface.

## Trust boundaries

- Model inference is designed to remain local when a local model is selected.
- Web and connected-service tools can transmit task-specific requests externally.
- Credentials remain outside the repository and are loaded only at runtime.
- Private memory and behavioral prompts are not part of the public project.
- Remote access is authenticated separately from the local model API.

## Operational lessons

- A large advertised context window does not guarantee that the complete stack is configured to use it.
- Tool reliability depends on both model behavior and clear stop conditions.
- Authentication recovery should use maintained helpers rather than repeated ad hoc commands.
- Live-data requests need authoritative sources and an explicit refusal to fabricate unavailable results.

