# Benchmark script

`benchmark_ollama.sh` runs a fixed, non-sensitive prompt against Ollama's local `/api/generate` endpoint and saves timing metrics as CSV. It disables thinking, sets temperature to zero, uses a fixed seed, and caps generation at 256 tokens to reduce variation between runs.

It intentionally does not save generated response text, private prompts, API credentials, or the configured endpoint.

## Requirements

- Bash
- `curl`
- `jq`
- A running Ollama server
- A locally available model

## Example

```bash
chmod +x scripts/benchmark_ollama.sh

./scripts/benchmark_ollama.sh \
  --model 'hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_S' \
  --runs 3 \
  --num-ctx 131072
```

The output is written to a timestamped CSV file under `results/` unless `--output` specifies another path.

## Useful comparisons

Keep the prompt, context, runtime version, and run count constant when comparing models. The script fixes generation temperature, seed, thinking mode, and maximum output length. A cold first run may include model-loading time, while later runs reflect a warm model.
