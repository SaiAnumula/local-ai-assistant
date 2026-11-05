# Architecture and trust boundaries

## Components

| Component | Role |
|---|---|
| Hermes | Agent loop, tool selection, sessions, and scheduled jobs |
| Ollama | Loads models and serves an OpenAI-compatible endpoint on loopback |
| Discord gateway | Remote messaging into Hermes |
| Hermes gateway | OpenAI-compatible API in front of Hermes (port 8642), used by Odysseus |
| Odysseus | Web workspace (port 7000) that sends chat through the Hermes gateway |
| Mnemosyne | Hermes memory provider, with a daily ingest and consolidation job |
| Tools | Web retrieval, terminal, files, memory, calendar, and automation |
| Linux host | systemd services, logging, storage, and GPU access |

## Request flow

1. A request arrives from the CLI, Discord, or the Hermes gateway (for Odysseus).
2. Hermes builds the prompt from allowed context, memory, and tool definitions.
3. Hermes sends it to the local model through Ollama.
4. Hermes runs approved tool calls and returns the results to the model.
5. The answer goes back through the interface the request came from.

## Inference configuration

Applied 2026-11-03 after the [24 GB retune](../benchmarks/model-results.md#november-2026-retuning-on-24-gb). Hermes calls a dedicated Ollama instance on loopback port 11437, separate from the default CLI instance on 11434.

| Setting | October 2026 (32 GB) | Current (24 GB) |
|---|---|---|
| Primary model | Qwen3.8 27B UD-IQ4_XS | Qwen3.6 35B-A3B UD-Q4_K_M |
| Context | 98,304 | 65,536 |
| Reasoning effort | `medium` | `medium` |
| KV cache | K q5_0, V q4_0 (via `LLAMA_ARG_*`, not verified to apply) | q8_0 for K and V |
| Loaded models | 3 | 1 |
| Parallel requests | 2 | 1 |
| Keep-alive | `-1` (always loaded) | 5 minutes |
| VRAM reserved for the desktop | not recorded | 3 GiB (`OLLAMA_GPU_OVERHEAD`) |
| Flash attention | on | on |
| systemd memory limits | none recorded | `MemoryHigh=6G`, `MemoryMax=7G`, `MemorySwapMax=0` |

Ornith 1.5 9B handles Hermes's auxiliary image-input and context-compression calls.

The 3 GiB GPU reservation keeps room on the card for the browser, desktop, and games I run alongside the assistant. The memory limits cap the Ollama service's anonymous memory so a model load cannot push the desktop into heavy swapping. Model weights are memory-mapped from disk, so the runner can still map far more than 7 GB of file-backed pages. These limits are why 128K context failed to load in production while the same model ran at 128K on the unrestricted benchmark instance.

## Hermes and Odysseus integration

```text
Odysseus UI (7000) -> Hermes gateway (8642) -> Ollama (11437) -> local model
```

Odysseus calls the Hermes gateway instead of Ollama, so chats get Hermes tools and memory. A verification run on 2026-10-05 covered:

- Gateway authentication with a persistent key. Missing or wrong keys get HTTP 401.
- Streaming, conversation history replay, and a Hermes file-tool call.
- An end-to-end chat from Odysseus to the model and back.
- Crash recovery: systemd restarted Odysseus after a forced kill.

Known limits:

- The generic Odysseus provider does not send Hermes session headers, so recall of earlier turns depends on the frontend replaying history. I have not retested cross-session recall through Mnemosyne on this path.
- Only one short chat ran after the service change. Tools and memory were not retested then.

## Trust boundaries

- Inference stays on the machine when a local model is selected.
- Web and connected-service tools send task-specific requests to outside services.
- Credentials live outside the repository and load at runtime.
- Private memory and behavior prompts are not part of this repository.
- Remote access authenticates separately from the local model API.
- Benchmarks run on a separate Ollama instance and model store, so tests never change the production service.

## Troubleshooting findings

**Chat templates matter as much as agent settings.** An earlier Qwen3.8 build (Q3_K_XL) shipped an Ollama template that always injected `Reasoning effort is set to xhigh`, whatever Hermes requested. The later IQ4_XS template accepts `low`, `medium`, and `xhigh` and only defaults to `xhigh` when nothing is passed.

**Tool-call format can break a model inside one agent and not another.** Ministral 3 14B printed `terminal[ARGS]{...}` as plain text inside Hermes, but made correct tool calls in a minimal one-tool test on both Ollama endpoints.

**Ollama's memory counters under-report partial offload.** For Qwen3.6 at 128K, `ollama ps` said 98% GPU while the loader log showed 11 GB of weights mapped on the CPU. For Gemma4 the API reported 1.3 GB resident for a model that fully occupied the GPU. I use the loader log for footprint numbers.

**Agent latency is mostly prompt and generation length.** Production logs showed 88K-token prompts taking 59 s to evaluate and 12.6K-token generations taking 168 s. A 19.8K-token cold prompt on a 27 GiB model took 135.6 s before the first token.

**Reasoning needs output budget.** With `medium` reasoning and a 512-token cap, Qwen spent the whole budget reasoning and returned no visible answer. At 2,048 tokens it answered in 5.7 s.

## Operational lessons

- An advertised context window is not the context the machine can serve. Measure fit under the real service limits.
- Tool reliability depends on both the model and clear stop conditions in each helper's output.
- Use the maintained helper for authentication recovery instead of ad hoc commands.
- Requests for live data need an authoritative source and an explicit "unavailable" path.
