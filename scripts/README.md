# Scripts

## benchmark_ollama.sh

Sends a fixed prompt to Ollama's `/api/generate` endpoint and writes timing metrics to CSV. It fixes temperature at 0, the seed at 42, and output at 256 tokens so runs are comparable. It does not save the generated text or the endpoint.

Requirements: Bash, `curl`, `jq`, a running Ollama server, and the model pulled locally.

```bash
./scripts/benchmark_ollama.sh \
  --model 'hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M' \
  --runs 3 \
  --num-ctx 131072 \
  --think false \
  --endpoint http://127.0.0.1:11434
```

| Option | Default | Meaning |
|---|---|---|
| `--model` | required | Exact Ollama model name |
| `--runs` | 3 | Number of measured runs |
| `--num-ctx` | 8192 | Context allocation sent to Ollama |
| `--think` | false | Thinking mode, `true` or `false` |
| `--endpoint` | `http://127.0.0.1:11434` | Ollama base URL |
| `--output` | `results/<timestamp>.csv` | CSV path |

CSV columns: `run, timestamp_utc, model, num_ctx, prompt_tokens, decode_tokens, prompt_tok_s, decode_tok_s, total_seconds, load_seconds, think, prompt_seconds, decode_seconds`.

Notes from using it:

- The first run includes model load. Compare runs 2 and 3 for warm decode speed.
- `num_ctx` in the CSV is what was requested. Check the real context and CPU/GPU split with `OLLAMA_HOST=<endpoint> ollama ps` while it runs.
- The prompt is short, so a 128K allocation here does not test 128K of input. Use `harness/prefill.py` and `harness/context_probe.py` for that.
- With `--think true`, the model can spend all 256 tokens reasoning. Throughput does not show whether it would have finished the task.
- `--think` applies to the native `/api/generate` route. Hermes uses `/v1/chat/completions`, where reasoning is off only with [`reasoning_effort: "none"`](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx).
- Run it while nothing else is using the model. A concurrent request with a different context makes Ollama reload the model.

## harness/

Python 3 scripts used for the November 2026 tests. They use only the standard library and talk to a local Ollama instance on the given port. Each writes JSON to `$BENCH_OUT_DIR` (default `results/raw/`, which is git-ignored).

| Script | Arguments | What it does |
|---|---|---|
| `run_benchmark.py` | `MODEL PORT THINK LABEL [NUM_CTX]` | Runs `benchmark_ollama.sh` and samples `/api/ps`, `/proc/meminfo`, memory PSI, and amdgpu VRAM once per second |
| `reliability_openai.py` | `MODEL PORT THINK LABEL` | Five-case tool reliability suite over `/v1/chat/completions` with simulated helpers |
| `calendar_checks.py` | `MODEL PORT LABEL` | Four Google Calendar PATCH checks against a fake event |
| `prefill.py` | `MODEL PORT THINK LABEL` | Fresh ~27K-token prompt, same prefix again, then a changed follow-up |
| `context_probe.py` | `MODEL PORT LABEL` | Recall of three anchor codes spread across a ~115K-token prompt |
| `memory_guard.py` | `LABEL COMMAND...` | Runs a command and kills it if RAM or memory pressure crosses a limit |

Example, with a separate benchmark instance on port 11441 so production is never touched:

```bash
OLLAMA_HOST=127.0.0.1:11441 OLLAMA_MODELS=~/bench-models ollama serve &
export BENCH_OUT_DIR=results/raw BENCH_OLLAMA=http://127.0.0.1:11441

scripts/harness/memory_guard.py qwen-reliability \
  python3 scripts/harness/reliability_openai.py \
  'hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M' 11441 false qwen-reliability
```

The only real network request is the current-data case in `reliability_openai.py`, which reads Ollama's latest release from the GitHub API. Every auth, service, and calendar helper is simulated. Never point these scripts at real credentials or a real calendar.

The Hermes agent-loop runs (rounds 2 and 4 in [model-results.md](../benchmarks/model-results.md)) used a separate runner that imports the installed Hermes agent and, for one case, reads a real calendar with my OAuth credentials. That runner is not published. Its results are in [`results/2026-11-03-24gb/hermes-loop/`](../results/2026-11-03-24gb/hermes-loop/).
