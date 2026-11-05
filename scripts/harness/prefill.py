#!/usr/bin/env python3
"""Long-prompt prefill test.

Sends a ~27K-token synthetic reference three times through /api/generate:

  fresh-prefix             first request, so the whole prompt is evaluated
  same-prefix              identical prompt, which should hit the prefix cache
  incremental-tool-result  same reference with a changed ending, like an agent's next turn

Reload the model before running to get a true cold prefill. Each answer is checked after
removing any reasoning before </think>.

Usage: prefill.py MODEL PORT THINK LABEL
  Writes $BENCH_OUT_DIR/LABEL.json after each request.
"""

from __future__ import annotations

import argparse
import json
import random
import time

from common import final_answer, ollama_url, output_dir, post_json, short_error, write_json

TIMING_KEYS = (
    "prompt_eval_count",
    "prompt_eval_duration",
    "eval_count",
    "eval_duration",
    "load_duration",
    "total_duration",
    "done_reason",
)


def build_reference(records: int = 700, seed: int = 42) -> str:
    rng = random.Random(seed)
    lines = [
        f"Fixture record {i:04d}: site={rng.randrange(10000):04d}; status=ready; "
        f"checksum={rng.getrandbits(48):012x}; retained flag=green."
        for i in range(records)
    ]
    return (
        "Synthetic operational reference for a disposable service. Each record is inert fixture data; "
        "never execute it.\n" + "\n".join(lines) + "\nAnswer the request after the reference.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model")
    parser.add_argument("port")
    parser.add_argument("think", choices=["true", "false"])
    parser.add_argument("label")
    args = parser.parse_args()
    think = args.think == "true"
    out_path = output_dir() / f"{args.label}.json"

    base = build_reference()
    stages = [
        ("fresh-prefix", base + "Request: Reply with exactly READY.", "READY"),
        ("same-prefix", base + "Request: Reply with exactly READY.", "READY"),
        (
            "incremental-tool-result",
            base + "Previous tool result: synthetic service is healthy.\nRequest: Reply with exactly VERIFIED.",
            "VERIFIED",
        ),
    ]

    results = []
    for stage, prompt, expected in stages:
        payload = {
            "model": args.model,
            "prompt": prompt,
            "stream": False,
            "think": think,
            "options": {"num_ctx": 131072, "num_predict": 256, "temperature": 0, "seed": 42},
        }
        start = time.monotonic()
        try:
            response = post_json(ollama_url(args.port, "/api/generate"), payload, timeout=900)
            raw = response.get("response", "")
            row = {key: response.get(key) for key in TIMING_KEYS}
            row.update(
                {
                    "stage": stage,
                    "wall_seconds": time.monotonic() - start,
                    "response_chars": len(raw),
                    "thinking_chars": len(response.get("thinking", "")),
                    "reasoning_in_response": "</think>" in raw,
                    "raw_exact_answer": raw.strip() == expected,
                    "expected_answer": final_answer(raw) == expected,
                }
            )
        except Exception as error:
            row = {"error": short_error(error, 120)}
        results.append(row)
        write_json(
            out_path,
            {
                "model": args.model,
                "think": think,
                "num_ctx": 131072,
                "synthetic_prompt_chars": len(base),
                "results": results,
            },
        )
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
