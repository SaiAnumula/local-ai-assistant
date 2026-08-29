#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
  cat <<'EOF'
Benchmark an Ollama model with a fixed, non-sensitive prompt.

Usage:
  benchmark_ollama.sh --model MODEL [options]

Options:
  --model MODEL       Exact Ollama model name (required)
  --runs NUMBER       Number of measured runs (default: 3)
  --num-ctx NUMBER    Context allocation passed to Ollama (default: 8192)
  --endpoint URL      Ollama base URL (default: http://127.0.0.1:11434)
  --output FILE       CSV output path (default: results/<timestamp>.csv)
  -h, --help          Show this help

The script records timing and token counts, not generated response text.
EOF
}

model=""
runs=3
num_ctx=8192
endpoint="http://127.0.0.1:11434"
output=""

while (($#)); do
  case "$1" in
    --model)
      model="${2:-}"
      shift 2
      ;;
    --runs)
      runs="${2:-}"
      shift 2
      ;;
    --num-ctx)
      num_ctx="${2:-}"
      shift 2
      ;;
    --endpoint)
      endpoint="${2:-}"
      shift 2
      ;;
    --output)
      output="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for dependency in curl jq; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    echo "Required command not found: $dependency" >&2
    exit 1
  fi
done

if [[ -z "$model" ]]; then
  echo "--model is required" >&2
  usage >&2
  exit 2
fi

if [[ ! "$runs" =~ ^[1-9][0-9]*$ ]] || [[ ! "$num_ctx" =~ ^[1-9][0-9]*$ ]]; then
  echo "--runs and --num-ctx must be positive integers" >&2
  exit 2
fi

endpoint="${endpoint%/}"
timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
if [[ -z "$output" ]]; then
  output="results/${timestamp}.csv"
fi
mkdir -p "$(dirname "$output")"

prompt='Write a detailed technical explanation of why repeatable benchmarks require controlled variables. Continue until the response limit.'
payload="$(jq -n \
  --arg model "$model" \
  --arg prompt "$prompt" \
  --argjson num_ctx "$num_ctx" \
  '{
    model: $model,
    prompt: $prompt,
    stream: false,
    think: false,
    options: {
      num_ctx: $num_ctx,
      num_predict: 256,
      temperature: 0,
      seed: 42
    }
  }')"

printf '%s\n' 'run,timestamp_utc,model,num_ctx,prompt_tokens,decode_tokens,prompt_tok_s,decode_tok_s,total_seconds,load_seconds' >"$output"

echo "Model: $model"
echo "Runs: $runs | Context: $num_ctx"
echo "Output: $output"

for ((run = 1; run <= runs; run++)); do
  response="$(curl --fail --silent --show-error \
    --connect-timeout 5 \
    --max-time 900 \
    -H 'Content-Type: application/json' \
    -d "$payload" \
    "$endpoint/api/generate")"

  if [[ "$(jq -r '.done // false' <<<"$response")" != "true" ]]; then
    echo "Run $run did not complete successfully" >&2
    jq -r '.error // "Ollama returned an incomplete response"' <<<"$response" >&2
    exit 1
  fi

  row="$(jq -r \
    --arg run "$run" \
    --arg timestamp "$timestamp" \
    --arg model "$model" \
    --arg num_ctx "$num_ctx" '
      def seconds: . / 1000000000;
      def rate($count; $duration):
        if ($duration // 0) > 0 then ($count / ($duration | seconds)) else 0 end;
      [
        $run,
        $timestamp,
        $model,
        $num_ctx,
        (.prompt_eval_count // 0),
        (.eval_count // 0),
        (rate((.prompt_eval_count // 0); (.prompt_eval_duration // 0)) | tostring),
        (rate((.eval_count // 0); (.eval_duration // 0)) | tostring),
        ((.total_duration // 0) | seconds | tostring),
        ((.load_duration // 0) | seconds | tostring)
      ] | @csv
    ' <<<"$response")"

  printf '%s\n' "$row" >>"$output"
  decode_rate="$(cut -d, -f8 <<<"$row" | tr -d '"')"
  printf 'Run %d/%d: %.2f decode tok/s\n' "$run" "$runs" "$decode_rate"
done

average="$(awk -F, 'NR > 1 {gsub(/"/, "", $8); sum += $8; count++} END {if (count) printf "%.2f", sum / count}' "$output")"
echo "Average decode speed: ${average} tok/s"
echo "Saved sanitized metrics to $output"
