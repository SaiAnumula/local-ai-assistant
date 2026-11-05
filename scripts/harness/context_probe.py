#!/usr/bin/env python3
"""Near-window recall probe.

Builds a ~115K-token synthetic reference of 3,000 inert records and hides three anchor codes at
the start, middle, and end. The model must return all three as JSON. This checks that the full
context window is wired up end to end. It does not measure reasoning quality across the window.

Usage: context_probe.py MODEL PORT LABEL
  Writes $BENCH_OUT_DIR/LABEL.json.
"""

from __future__ import annotations

import argparse
import json
import random
import time

from common import ollama_url, output_dir, post_json, short_error, write_json

RECORDS = 3000
ANCHORS = {0: ("start", "ALDER-4821"), 1500: ("middle", "BRONZE-7395"), 2999: ("end", "CEDAR-2608")}
TIMING_KEYS = (
    "prompt_eval_count",
    "prompt_eval_duration",
    "eval_count",
    "eval_duration",
    "total_duration",
    "load_duration",
    "done_reason",
)


def build_prompt(seed: int = 617) -> str:
    rng = random.Random(seed)
    rows = []
    for i in range(RECORDS):
        if i in ANCHORS:
            name, code = ANCHORS[i]
            rows.append(f"ANCHOR {name}: {code}. This exact anchor code is the required lookup value.")
        rows.append(
            f"Fixture record {i:04d}: site={rng.randrange(10000):04d}; status=ready; "
            f"checksum={rng.getrandbits(48):012x}; retained flag=green."
        )
    return (
        "Read this inert synthetic reference. Keep the three ANCHOR codes for a lookup at the end.\n"
        + "\n".join(rows)
        + "\nReturn only a JSON object with keys start, middle, end and the exact respective ANCHOR codes. "
        "Do not use tools."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model")
    parser.add_argument("port")
    parser.add_argument("label")
    args = parser.parse_args()

    prompt = build_prompt()
    payload = {
        "model": args.model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"num_ctx": 131072, "num_predict": 256, "temperature": 0, "seed": 42},
    }
    start = time.monotonic()
    try:
        response = post_json(ollama_url(args.port, "/api/generate"), payload, timeout=1800)
        content = response.get("response", "")
        row = {key: response.get(key) for key in TIMING_KEYS}
        row.update(
            {
                "wall_seconds": time.monotonic() - start,
                "anchors_recalled": {name: code in content for name, code in ANCHORS.values()},
                "response_chars": len(content),
                "input_chars": len(prompt),
            }
        )
    except Exception as error:
        row = {"error": short_error(error, 200), "wall_seconds": time.monotonic() - start}

    write_json(
        output_dir() / f"{args.label}.json",
        {"model": args.model, "num_ctx": 131072, "think": False, "synthetic": True, "result": row},
    )
    print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
