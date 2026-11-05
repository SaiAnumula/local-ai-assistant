# 24 GB retune, 2026-11-03

Raw data behind the [November 2026 retune](../../benchmarks/model-results.md#november-2026-retuning-on-24-gb). Host: i5-13600KF, RX 9070 16 GB, 24 GB DDR4, CachyOS. All runs used seed 42 and temperature 0. Most cases ran once, so treat them as directional.

| Path | Round | Contents |
|---|---|---|
| `throughput/*.csv` | 1, 4 | [`benchmark_ollama.sh`](../../scripts/benchmark_ollama.sh) output, three runs each. Names are `<model>-<context>[-q8kv]-<thinking>.csv`. Files without `q8kv` used f16 KV |
| `synthetic/*-reliability.json` | 1 | Five-case tool loop with simulated helpers. Files with `openai` in the name used `/v1/chat/completions`, the rest used native `/api/chat` |
| `synthetic/*-calendar.json` | 1 | Calendar PATCH checks against a fake event |
| `synthetic/*-prefill.json` | 1 | Fresh ~27K-token prompt, same prefix, changed follow-up |
| `synthetic/*-window-probe.json` | 1 | Anchor recall in a ~115K-token prompt |
| `synthetic/native-tool-loop-summary.json` | 1 | Pass counts and total time for the native tool loop |
| `synthetic/q8kv-profile-summary.json` | 1 | Summary of the three q8_0 KV profiles |
| `hermes-loop/ornith-vs-qwen.json` | 2 | Six cases through the Hermes agent, including the read-only real-calendar audit |
| `hermes-loop/ministral-vs-gemma.json` | 4 | Six cases through the Hermes agent with the synthetic calendar fixture |
| `hermes-loop/ministral-minimal-tool-call-check.json` | 4 | One-tool call test on both Ollama endpoints |
| `deployment-fit.json` | 3 | Applied production profile and fit results |

The real-calendar case in round 2 publishes only pass/fail, counts, and tool sequences. Calendar names were replaced with aliases (`fall-2026`) before the model saw them, and event contents are not included.

Superseded runs are left out: an early 32K run confounded by a concurrent agent request, prefill runs scored before the `</think>` parsing fix, an Ornith pilot with a broken tool interface, and a Ministral load stopped by the memory guard.
