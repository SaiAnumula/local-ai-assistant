#!/usr/bin/env python3
"""Run benchmark_ollama.sh with memory telemetry.

Starts scripts/benchmark_ollama.sh (three runs) and, once per second while it runs, records
the models Ollama has loaded with their VRAM share, RAM and swap from /proc/meminfo, memory
pressure (PSI), and amdgpu VRAM in use.

Usage: run_benchmark.py MODEL PORT THINK LABEL [NUM_CTX]
  NUM_CTX defaults to 131072. Writes $BENCH_OUT_DIR/LABEL.csv and LABEL-telemetry.json.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

from common import get_json, memory_pressure, ollama_url, output_dir, read_meminfo, vram_used_bytes, write_json

BENCHMARK_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "benchmark_ollama.sh"
MEMORY_FIELDS = ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")
MODEL_FIELDS = ("name", "size", "size_vram", "context_length")


def sample(port: str) -> dict:
    row: dict = {"time": time.time()}
    try:
        loaded = get_json(ollama_url(port, "/api/ps"), timeout=2).get("models", [])
        row["models"] = [{key: model.get(key) for key in MODEL_FIELDS} for model in loaded]
        meminfo = read_meminfo()
        row["memory_kib"] = {key: meminfo[key] for key in MEMORY_FIELDS}
        row["memory_pressure"] = memory_pressure()
        row["vram_used_bytes"] = vram_used_bytes()
    except Exception as error:
        row["telemetry_error"] = type(error).__name__
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model")
    parser.add_argument("port")
    parser.add_argument("think", choices=["true", "false"])
    parser.add_argument("label")
    parser.add_argument("num_ctx", nargs="?", default="131072")
    args = parser.parse_args()
    out = output_dir()

    command = [
        "bash",
        str(BENCHMARK_SCRIPT),
        "--model",
        args.model,
        "--endpoint",
        ollama_url(args.port, ""),
        "--runs",
        "3",
        "--num-ctx",
        args.num_ctx,
        "--think",
        args.think,
        "--output",
        str(out / f"{args.label}.csv"),
    ]
    process = subprocess.Popen(command)
    samples = []
    while process.poll() is None:
        samples.append(sample(args.port))
        time.sleep(1)

    write_json(out / f"{args.label}-telemetry.json", samples)
    print("benchmark_exit", process.returncode, "telemetry_samples", len(samples), flush=True)
    sys.exit(process.returncode)


if __name__ == "__main__":
    main()
