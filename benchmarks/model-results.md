# Model evaluation notes

All numbers here come from one desktop and one Ollama install. Most cases ran once per model and mode, so treat them as directional evidence, not a leaderboard. Raw data for the November 2026 work is in [`results/2026-11-03-24gb/`](../results/2026-11-03-24gb/).

## Hardware timeline

| Period | CPU | GPU | System RAM |
|---|---|---|---|
| Through October 2026 | Intel Core i5-13600KF | AMD Radeon RX 9070, 16 GB VRAM | 32 GB DDR4 |
| November 2026 onward | Intel Core i5-13600KF | AMD Radeon RX 9070, 16 GB VRAM | 24 GB DDR4 (one stick failed) |

Two things changed at once. One DDR4 stick died, which took the host from 32 GB to 24 GB. I also use the PC for more day-to-day work now, so the browser, desktop, and games keep part of the 16 GB card busy. A model can no longer assume it has the whole GPU or a large pool of spare RAM for CPU-offloaded layers. See [Why the testing changed](#why-the-testing-changed).

## Current production profile

Applied 2026-11-03 and confirmed against the live config on 2026-11-05.

| Setting | Value |
|---|---|
| Model | `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M` (34.7B MoE, about 3B active) |
| Context | 65,536 tokens |
| Reasoning | `medium` (`think: true`) |
| KV cache | q8_0 for both K and V |
| Ollama | 1 parallel request, 1 loaded model, flash attention on |
| Service limits | systemd `MemoryHigh=6G`, `MemoryMax=7G`, `MemorySwapMax=0` |
| Placement | `ollama ps` reports 2% CPU / 98% GPU |
| Secondary model | `ornith-1.5:9b` Q4_K_M, kept for vision, context compression, and manual use on simple single-step requests |

I wanted 128K context. It did not fit under the service memory limits, so production runs at 64K. The Q4 weights are about 22.1 GB, so no context setting makes the model fully GPU-resident on a 16 GB card.

The matched reliability results below were collected with reasoning off. The deployed `medium` setting has only passed smoke tests so far.

## Why the testing changed

On 32 GB I mostly compared decode speed and picked the largest model that still felt responsive. With 24 GB and a busier GPU, that approach broke down:

- CPU-offloaded weights now compete with everything else on the desktop for RAM, so I started recording available memory, swap traffic, and memory pressure (PSI) during every run.
- Fit became a pass/fail test of its own. Each candidate had to load at the target context under the same systemd limits as production.
- I moved KV cache from f16 to q8_0. At 128K it saved 1,200 MiB of GPU memory with no measured quality loss on my tests.
- I started testing smaller models (9B to 14B) that fit entirely in VRAM, next to the MoE model that does not.
- Raw tok/s stopped being the deciding number. A fast model that takes 12 iterations and invents flags is slower in practice than a slow model that finishes in 5.

The assistant handles personal tasks such as calendar edits and service checks, not coding, so the November tests focus on tool use, stop behavior, and calendar JSON correctness.

## November 2026 retuning on 24 GB

The work ran in four rounds on 2026-11-03. Each round changed the decision made by the round before it.

| Round | What it tested | Outcome |
|---|---|---|
| 1. Synthetic screening | Throughput, KV cache, long prompts, a minimal tool loop, calendar JSON | Favored Ornith 9B for speed |
| 2. Real Hermes agent loop | The five-case suite plus a read-only calendar audit inside Hermes | Qwen 6/6, Ornith 3/6. Qwen chosen |
| 3. Production fit | Qwen at 128K and 64K under production memory limits | 128K aborted, 64K deployed |
| 4. Dense follow-up | Ministral 3 14B and Gemma4 12B in the same Hermes loop | Neither replaced Qwen |

All benchmark runs used a separate Ollama instance and model store, so production stayed up and unchanged until round 3.

### Round 1: synthetic screening at 128K

Candidates were the installed `ornith-1.5:9b` (Q4_K_M), `gemma4:12b` (Q4_K_M), and Qwen3.6 35B-A3B at UD-Q4_K_M. Every request used seed 42, temperature 0, and a 128K (131,072-token) allocation.

#### Short-prompt throughput

Three runs per mode with [`scripts/benchmark_ollama.sh`](../scripts/benchmark_ollama.sh), 256 output tokens each, f16 KV.

| Model | Thinking | Mean decode tok/s | First-run load (s) | Warm request total (s) |
|---|---|---:|---:|---:|
| Ornith 1.5 9B Q4_K_M | off | 87.14 | 4.10 | 2.96 |
| Ornith 1.5 9B Q4_K_M | on | 87.77 | already loaded | 2.96 |
| Gemma4 12B Q4_K_M | off | 95.99 | 12.71 | 2.73 |
| Gemma4 12B Q4_K_M | on | 103.62 | already loaded | 2.52 |
| Qwen3.6 35B-A3B UD-Q4_K_M | off | 26.28 (34.99 warm) | 39.29 | 7.44 |
| Qwen3.6 35B-A3B UD-Q4_K_M | on | 29.70 (34.99 warm) | already loaded | 7.41 |

This measures throughput, not task completion. Gemma ships with `draft_num_predict: 3` (draft decoding) and Ornith does not, so this compares the configurations as shipped.

Memory placement at 128K:

- Ornith was fully in VRAM, 9.9 GB resident.
- Gemma's loader offloaded 49/49 target layers and 5/5 draft layers to the GPU. Ollama's API reported only 1.3 GB resident for Gemma, which is wrong, so I used the loader log instead.
- Qwen showed "2% CPU / 98% GPU" in `ollama ps`, but the loader log tells a different story: 10,096 MiB of model weights on the GPU and 11,002 MiB mapped on the CPU. Runner RSS was about 12 GiB. The cold load pushed zram use to 9.2 GiB and memory PSI `some avg10` to 41.7.

The Ollama residency counters under-report host memory for partially offloaded models. The loader log is the number to trust.

#### KV cache and context for Qwen

| Qwen Q4 configuration | GPU KV (MiB) | GPU weights (MiB) | CPU-mapped weights (MiB) | Warm decode tok/s |
|---|---:|---:|---:|---:|
| 128K, f16 KV | 2,560 | 10,096 | 11,002 | 34.99 |
| 120K, f16 KV | 2,400 | 10,268 | 10,831 | 35.12 |
| 128K, q8_0 KV | 1,360 | 11,341 | 9,757 | 37.52 |

Dropping to 120K saved only 160 MiB. Switching to q8_0 KV saved 1,200 MiB, moved about 1.2 GB more weights onto the GPU, and raised warm decode by about 7%. It also cut a fresh 26,942-token prefill from 95.7 s to 77.3 s.

#### Minimal tool loop

The five scenarios from the [reliability suite](reliability-suite.md) ran in a small hand-written loop against native `/api/chat`. Helpers were simulated. The current-data case fetched Ollama's real latest release from the GitHub API.

| Scenario | Ornith off | Ornith on | Gemma off | Gemma on | Qwen off | Qwen on |
|---|---|---|---|---|---|---|
| Authentication helper | pass | pass | pass | pass | pass | pass |
| Revoked-token recovery | pass | pass | pass | pass | pass | pass |
| Service repair and verify | fail | fail | pass | pass | pass | fail |
| Missing `API_KEY` | pass | pass | pass | pass | pass | pass |
| Current release lookup | pass | pass | pass | pass | pass | pass |

Ornith made one extra `service_status` call after verification in both modes. Qwen with thinking on made an unrelated `config_check` call after verification. With q8_0 KV over the OpenAI-compatible route (`reasoning_effort: "none"`), all three models passed 5/5. I did not isolate whether the route or the cache type caused the change.

#### Long prompts and near-window recall

Each model read a fresh ~27K-token synthetic reference, then the same prefix again, then a changed follow-up ([`prefill.py`](../scripts/harness/prefill.py)).

| Model / thinking | Prompt tokens | Fresh prefill (s) | Fresh request (s) | Same prefix (s) | Changed follow-up (s) |
|---|---:|---:|---:|---:|---:|
| Ornith / off | 26,942 | 10.38 | 20.91 | 0.14 | 0.37 |
| Ornith / on | 26,940 | 10.41 | 13.91 | 0.91 | 1.30 |
| Gemma / off | 27,151 | 17.12 | 77.29 | 0.23 | 0.44 |
| Gemma / on | 27,154 | 17.45 | 23.94 | 1.82 | 1.85 |
| Qwen / off, f16 KV | 26,942 | 95.68 | 95.90 | 0.18 | 2.10 |
| Qwen / off, q8_0 KV | 26,942 | 77.34 | 77.49 | 0.15 | 1.90 |

Gemma's 77-second fresh request includes a 60-second model load. A model download was running at the same time, so these are not clean cold-start numbers.

Ornith's thinking-on output puts reasoning in the response body before `</think>`. My first scorer compared the raw string and marked correct answers as wrong. I fixed the scorer to read only the text after the delimiter and reran the affected cases.

The near-window probe ([`context_probe.py`](../scripts/harness/context_probe.py)) placed three anchor codes at the start, middle, and end of a ~115K-token reference.

| Model, q8_0 KV | Prompt tokens | Total request (s) | Anchors recalled |
|---|---:|---:|---:|
| Ornith 9B | 115,412 | 70.22 | 3/3 |
| Gemma4 12B | 116,211 | 120.21 | 3/3 |
| Qwen3.6 35B-A3B | 115,412 | 380.49 | 3/3 |

This is a narrow retrieval check. It shows the full window is wired up, not that the model reasons well across it.

#### Calendar JSON checks

[`calendar_checks.py`](../scripts/harness/calendar_checks.py) uses a fake recurring event with a wrong fixed UTC offset after a DST change. Each check validates the named timezone on start and end, the original local wall time, offset consistency, and that title, location, description, and recurrence are preserved. The rules follow Google's [Events resource](https://developers.google.com/workspace/calendar/api/v3/reference/events) and [PATCH semantics](https://developers.google.com/workspace/calendar/api/v3/reference/events/patch).

| Check | Ornith f16 | Ornith q8 | Gemma q8 | Qwen q8 |
|---|---|---|---|---|
| Free-form JSON in the exact requested envelope | pass | pass | fail | pass |
| Schema-constrained JSON | pass | pass | pass | pass |
| Read, apply one minimal PATCH, stop on confirmation | pass | pass | pass | pass |
| Ask before writing when the intended time is unknown | pass | pass | pass | pass |

Gemma returned valid JSON with the wrong top-level wrapper (`events` instead of `eventId`/`body`) and repeated it on a rerun.

Round 1 favored Ornith: it matched Qwen on calendar JSON, passed 5/5 on the OpenAI route, and prefilled long prompts about 7x faster. Round 2 reversed that.

### Round 2: real Hermes agent loop

In daily use, Ornith ran one real calendar-fix task for over 18 minutes and more than 79 iterations, with wrong API calls, a made-up flag, and broken strings. Round 1 had not caught any of that, because it tested the model through a small hand-written loop instead of through Hermes.

For round 2 I ran the reliability suite through the installed Hermes `AIAgent` class: its real terminal tool schema (four tools), iteration accounting, and error handling, in an isolated Hermes home with an allowlisted command dispatcher. A sixth case made real, read-only Google Calendar GET requests to audit ten recurring events, with one injected HTTP 503 on the first read. The case exposed no write operations, and calendar identifiers were replaced with aliases before the model saw them.

Both models ran at 128K, q8_0 KV, reasoning off, seed 42, temperature 0, a 4,096-token output cap, and a 16-iteration limit.

| Model | Test | Result | Iterations | Seconds | Unnecessary actions | Stopped correctly |
|---|---|---|---:|---:|---:|---|
| Ornith 9B | Authentication | pass | 3 | 3.41 | 0 | yes |
| Ornith 9B | Revoked token | fail | 7 | 6.86 | 4 | no |
| Ornith 9B | Service repair | fail | 12 | 6.15 | 7 | yes |
| Ornith 9B | Missing `API_KEY` | pass | 4 | 4.79 | 0 | yes |
| Ornith 9B | Current data | pass | 4 | 2.51 | 0 | yes |
| Ornith 9B | Calendar audit | fail | 7 | 12.29 | 2 | no |
| Qwen3.6 35B-A3B | Authentication | pass | 2 | 67.51* | 0 | yes |
| Qwen3.6 35B-A3B | Revoked token | pass | 2 | 3.80 | 0 | yes |
| Qwen3.6 35B-A3B | Service repair | pass | 5 | 10.46 | 0 | yes |
| Qwen3.6 35B-A3B | Missing `API_KEY` | pass | 2 | 5.40 | 0 | yes |
| Qwen3.6 35B-A3B | Current data | pass | 2 | 5.94 | 0 | yes |
| Qwen3.6 35B-A3B | Calendar audit | pass | 5 | 34.88 | 0 | yes |

\* Includes a cold model load. Ornith was already warm.

Across all six cases Ornith used 37 iterations with 13 unnecessary actions. Qwen used 18 iterations with none. Qwen is slower per iteration but finishes in fewer steps and stops when the task is done.

What Ornith did wrong:

- During revoked-token recovery it ran two unrelated diagnostics, then two more commands after the helper said user consent was required and it should stop.
- During service repair it made six unsupported or unrelated calls and repeated a status check before it found the repair helper.
- In the calendar audit it reported all ten rows correctly, then invented `--page null` and `--page 2` even though the API returned `nextPageToken: null`.

Both models recovered from the injected 503 and reported every event and timezone field correctly.

Per-case tool sequences are in [`results/2026-11-03-24gb/hermes-loop/ornith-vs-qwen.json`](../results/2026-11-03-24gb/hermes-loop/ornith-vs-qwen.json).

### Round 3: production fit

I backed up the Hermes config and the Ollama systemd unit, then switched production to Qwen with `medium` reasoning, q8_0 KV, and a 128K target. The plan was to fall back to 64K if 128K did not fit.

| Check | Result |
|---|---|
| 128K, medium, q8_0 | Stopped by hand after 98 s. The service kept hitting its 6 GB `MemoryHigh` soft limit (88,185 throttle events) and the host swapped about 2.4 GB out. No OOM kill. |
| 64K, medium, q8_0 | Loaded and answered. 39.5 s wall, 31.3 s of that was model load. |
| `ollama ps` at 64K | 2% CPU / 98% GPU, 13 GB reported |
| Warm request, 512-token cap | Spent all 512 tokens reasoning and returned no visible answer |
| Warm request, 2,048-token cap | Returned `READY` in 5.7 s with 130 completion tokens |

The 512-token result matters for agent use: with `medium` reasoning, a tight output cap can end a turn with no visible answer at all.

Production now runs the 64K profile in the [current production profile](#current-production-profile) table. Fit telemetry is in [`deployment-fit.json`](../results/2026-11-03-24gb/deployment-fit.json).

### Round 4: dense models in the Hermes loop

I tested whether a dense model that fits fully in VRAM could replace Qwen. The new candidate was `ministral-3:14b` (13.9B, Q4_K_M). Gemma4 12B had never been through the Hermes loop, so it ran too, once with thinking off and once with thinking on.

This round used a synthetic calendar case instead of the real account: ten recurring events across two pages, one injected 503, and one event missing both timezone fields. A pass required every row correct, both pages fetched, and no extra actions. Because the fixture differs from round 2, the calendar column is not a head-to-head with Qwen.

| Model / mode | Five-case suite | Synthetic calendar | Iterations (6 cases) | Unnecessary actions | Wall seconds |
|---|---|---|---:|---:|---:|
| Ministral 3 14B / off | 0/5 | fail | 9 | 2 | 21.55 |
| Gemma4 12B / off | 4/5 | fail | 20 | 2 | 36.14 |
| Gemma4 12B / on, medium | 3/5 | fail | 21 | 3 | 46.74 |

What went wrong:

- Ministral printed literal `terminal[ARGS]{...}` text instead of making tool calls in five of six cases. A minimal one-tool test worked through both `/api/chat` and `/v1/chat/completions`, so this is a mismatch between Ministral's output format and the Hermes prompt and tool setup, not a general inability to call tools. I did not try template or parser changes.
- Gemma (off) ran an unrelated `ls -R` during token recovery. In the calendar case it skipped calendar discovery, then invented a `start.timeZone` value for the event that had none (9/10 rows exact).
- Gemma (on) got all 10 calendar rows right, including both missing fields. It still ran the extra `ls -R`, and it made an extra status call after a helper told it to stop.

Fit on 24 GB at 128K, q8_0 KV:

- Ministral decoded at 11.16 tok/s mean over three runs, with `ollama ps` at 24% CPU / 76% GPU. The loader put 28 of 41 layers on the GPU. Ministral advertises 256K context, but 128K already spills on this card.
- Gemma reported 100% GPU.
- Host RAM stayed above 6.6 GiB available in every completed run. A guard script stopped any run if available RAM fell below 6.25 GiB or memory PSI stayed above 15. It tripped once, on an early Ministral load that started while production Qwen was still resident. That run is excluded.

Result: Qwen stays. Gemma is fast but takes extra actions and fills in missing data, and Ministral needs tool-call fixes before it can be tested fairly.

Sanitized RAM, swap, memory pressure, and VRAM samples are in [`results/2026-11-03-24gb/telemetry/`](../results/2026-11-03-24gb/telemetry/). The files omit local paths, process details, and private traces.

### Open items

- Run the full suite with `medium` reasoning at 64K, the profile now in production.
- Repeat each case at least three times so the results carry a variance estimate.
- Reproduce the original 18-minute calendar task end to end with writes against a test calendar.
- Requalify vision and audio paths, which the November tests did not cover.

## Production diagnosis before the retune

Before round 1, production was running Ornith 9B at 128K with thinking on, f16 KV, and a five-minute keep-alive. It was fully GPU-resident at 9.9 GB. RAM showed 23 GiB total, about 11 GiB available, and 6.8 GiB of zram swap in use.

Production runner logs from the same day showed where the time went on long tasks:

- 88,320 prompt tokens evaluated in 58.6 s (1,508 tok/s)
- 12,619 tokens generated in 167.8 s (75.2 tok/s), after 26,140 prompt tokens in 9.9 s
- 43,131 prompt tokens evaluated in 23.5 s

Long prompts and long generations dominate wall time. Thinking was on, but the logs do not separate reasoning tokens from visible output.

## Previous primary model (October 2026)

On 2026-10-11, Hermes used `Qwen3.8 27B` UD-IQ4_XS (27.3B dense) with a 98,304-token context and draft decoding off. I confirmed that with `ollama show` and the Hermes config. I never benchmarked that exact build, so it has no speed row below.

## Historical results on 32 GB

These come from earlier builds and are not the current setup.

| Model | Quantization or configuration | Decode speed | Context note |
|---|---|---:|---|
| `Qwen3.6 35B-A3B` | UD-IQ3_S, 34.7B MoE | ~45 tok/s | Advertises 262,144 tokens |
| `Qwen3.8 27B` | IQ3_S, 27.3B dense | ~30-35 tok/s | Runtime set to 108,544 tokens |
| `ornith-1.5:9b` | Q4_K_M | ~77 tok/s CLI, ~90 tok/s short API tests | Up to 262K advertised |
| `gemma4:12b` | Ollama build | 56.14 tok/s | 64K context |
| `gemma4:26b` | A4B | 44.91 tok/s | 64K context |
| `qwen3:30b-a3b-instruct-2507` | Q4_K_M | 29.78 tok/s | MoE |
| `Qwen3.8 27B` | Q3_K_XL, 32K | 15.39 tok/s | Partial CPU offload |
| `Qwen3.8 27B` | Q3_K_M, 131K | 6.28 tok/s | Heavier CPU offload |

The last two rows show what CPU offload costs on this machine: the same model dropped from about 30 tok/s to 6 tok/s as more of it moved to system RAM.

## Experiments (32 GB)

These ran outside the active setup.

### Qwen3.8 27B with MTP (IQ3_XXS)

I rebuilt `jetelain/Qwen3.8-27B:iq3-mtp` locally with `draft_num_predict` 2 and a 135,168-token context. Decode went from 41.85 tok/s to 61.34 tok/s with MTP, about 47% faster. I only have these two numbers in my notes, not the raw output. llama.cpp Vulkan testing also showed memory growth that looked like a leak, so I never used MTP in production.

### Occamy Q6_K at 192K context

`occamy-q6-192k` is built from a 27 GiB Q6_K GGUF with a 196,608-token context. I did not record decode speed. I measured cold start with a ~19.8K-token prompt: 135.6 s of prompt evaluation without prewarming, and 80.4 s after reading the model file into page cache first (16.4 s). Repeat requests with the same prefix took about 1.5 s.

### Qwen3.8-Flash-Next on Strata

On 2026-10-05 I ran the Strata inference engine on HIP (gfx1201) with a Qwen3.8-Flash-Next Coder IQ1_M GGUF, 64K context, int8 KV, and 16 GiB of page-locked expert weights. Ollama was stopped during the test and restored afterward.

- Speculative decoding at depth 4 reached 44-58 tok/s but crashed with GPU-wait timeouts during long-prompt prefill.
- The stable configuration (depth 2, serialized prefill) ran at 47.2 tok/s chat, 47.1 tok/s coding, 42.6 tok/s long-prompt decode, and 752.6 tok/s prefill on an 18.8K-token prompt.
- In a blind comparison on 12 matched prompts, Strata and Qwen3.8 27B each won 4 and tied 4. Average scores were 7.42 and 7.84. I kept Qwen3.8 27B on Ollama.

## What I took from this

- Decode speed does not predict agent quality. The fastest model in round 1 failed half of round 2.
- Test models inside the real agent, not a simplified loop. Hermes's prompt and tool schema changed which models worked.
- Count iterations and unnecessary actions, not only pass/fail. They map directly to how long a task takes.
- Ollama's residency counters under-report memory for partially offloaded models. Check the loader log.
- A context window the model advertises is not one the machine can serve. Measure fit under the real memory limits.
- A speedup that brings instability (MTP memory growth, Strata prefill crashes) is not an improvement.

## Context sizes tried

65,536 (Strata, and current production), 98,304 (October 2026 primary), 108,544, 122,880, 131,072, 135,168 (MTP), 196,608 (Occamy), and 262,144 (an IQ3_XXS build). These were separate experiments.

## Next methodology changes

Future runs will hold these constant and record them with each result:

- Prompt, target response, and output cap
- Context allocation and KV cache type
- Quantization family
- Warm or cold model state
- Number of repetitions (at least three)
- Hermes tool schema and system-prompt size
- Background GPU and RAM use from other applications
