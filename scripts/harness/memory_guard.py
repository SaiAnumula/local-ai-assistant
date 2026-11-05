#!/usr/bin/env python3
"""Memory guard for benchmark runs on a shared desktop.

Refuses to start while the production Ollama instance has a model loaded. Otherwise it runs
COMMAND in its own process group and samples RAM, swap, memory pressure, and VRAM every two
seconds. It stops the command and unloads the benchmark instance's models when:

  - available RAM drops below 6.25 GiB
  - memory PSI avg10 stays above 15 for 20 seconds
  - the run passes 40 minutes

The production instance is only read, never changed.

Usage: memory_guard.py LABEL COMMAND [ARGS...]
  Env: PROD_OLLAMA and BENCH_OLLAMA (base URLs), BENCH_OUT_DIR (default results/raw).
  Writes $BENCH_OUT_DIR/LABEL-guard.json. Exits 3 if production is busy, 2 if the guard
  stopped the run, otherwise with COMMAND's exit code.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

from common import (
    get_json,
    memory_pressure,
    output_dir,
    post_json,
    read_meminfo,
    read_vmstat,
    vram_used_bytes,
    write_json,
)

PROD = os.environ.get("PROD_OLLAMA", "http://127.0.0.1:11437")
BENCH = os.environ.get("BENCH_OLLAMA", "http://127.0.0.1:11441")

MIN_AVAILABLE_KIB = int(6.25 * 1024**2)
PSI_LIMIT = 15.0
PSI_SAMPLES = 10  # 10 samples x 2 s = 20 s
MAX_SECONDS = 40 * 60
INTERVAL = 2


def psi_avg10(text: str) -> float:
    return float(text.split("avg10=")[1].split()[0])


def unload_benchmark_models() -> None:
    try:
        for model in get_json(f"{BENCH}/api/ps", timeout=2).get("models", []):
            post_json(f"{BENCH}/api/generate", {"model": model["name"], "keep_alive": 0}, timeout=10)
    except Exception:
        pass


def stop(process: subprocess.Popen) -> None:
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    label, command = sys.argv[1], sys.argv[2:]

    if get_json(f"{PROD}/api/ps", timeout=3).get("models"):
        print("BLOCKED: production model still resident", flush=True)
        sys.exit(3)

    process = subprocess.Popen(command, start_new_session=True)
    start = time.monotonic()
    samples = []
    high_psi = 0
    reason = None

    while process.poll() is None:
        meminfo = read_meminfo()
        vmstat = read_vmstat()
        pressure = memory_pressure()
        high_psi = high_psi + 1 if psi_avg10(pressure) > PSI_LIMIT else 0

        row = {
            "time": time.time(),
            "available_kib": meminfo["MemAvailable"],
            "swap_free_kib": meminfo["SwapFree"],
            "pswpin": vmstat["pswpin"],
            "pswpout": vmstat["pswpout"],
            "psi": pressure,
            "vram_used": vram_used_bytes(),
        }
        try:
            row["models"] = get_json(f"{BENCH}/api/ps", timeout=1).get("models")
        except Exception:
            pass
        samples.append(row)

        if meminfo["MemAvailable"] < MIN_AVAILABLE_KIB:
            reason = "available RAM below 6.25 GiB"
        elif high_psi >= PSI_SAMPLES:
            reason = "memory PSI avg10 above 15 for 20 seconds"
        elif time.monotonic() - start > MAX_SECONDS:
            reason = "40 minute cap"

        if reason:
            stop(process)
            unload_benchmark_models()
            break
        time.sleep(INTERVAL)

    exit_code = process.wait()
    write_json(
        output_dir() / f"{label}-guard.json",
        {"reason": reason, "exit": exit_code, "wall": time.monotonic() - start, "samples": samples},
    )
    print(json.dumps({"guard": label, "stop_reason": reason, "exit": exit_code}), flush=True)
    sys.exit(2 if reason else exit_code)


if __name__ == "__main__":
    main()
