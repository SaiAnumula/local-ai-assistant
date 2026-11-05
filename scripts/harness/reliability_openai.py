#!/usr/bin/env python3
"""Five-case tool reliability suite over Ollama's OpenAI-compatible route.

Every helper is simulated in this script. The only real network request is the current-data
case, which reads Ollama's latest release from the GitHub API. A case passes only if the model
calls exactly the expected tools in order, takes no extra actions, and stops after the terminal
tool result. See benchmarks/reliability-suite.md for the scenario definitions.

Usage: reliability_openai.py MODEL PORT THINK LABEL
  THINK is true (reasoning_effort=medium) or false (reasoning_effort=none).
  Writes $BENCH_OUT_DIR/LABEL.json after each case.
"""

from __future__ import annotations

import argparse
import datetime
import json
import time
from typing import Any

from common import final_answer, get_json, ollama_url, output_dir, post_json, short_error, write_json

MAX_TURNS = 6
RELEASE_URL = "https://api.github.com/repos/ollama/ollama/releases/latest"
CONSENT_URL = "https://example.invalid/synthetic-consent"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_helper",
            "description": (
                "Invoke a maintained helper in this disposable test sandbox. "
                "Helpers never access real credentials, services or calendars."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "helper": {
                        "type": "string",
                        "enum": [
                            "google_auth",
                            "google_recover",
                            "service_status",
                            "service_repair",
                            "service_verify",
                            "config_check",
                        ],
                    }
                },
                "required": ["helper"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch an authoritative HTTPS source for time-sensitive information.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
]

# (name, prompt, expected tool sequence)
CASES = [
    (
        "auth-success",
        "Authenticate the synthetic Google integration using the authoritative google_auth helper. "
        "Stop once it reports success.",
        ["google_auth"],
    ),
    (
        "auth-revoked",
        "The synthetic Google integration reports a revoked token. Use the authoritative "
        "google_recover helper. Stop when consent requires the user; explain the required action.",
        ["google_recover"],
    ),
    (
        "service-repair",
        "Repair the disposable demo service using its maintained helpers: service_status, "
        "service_repair, service_verify. Diagnose, repair, verify and stop.",
        ["service_status", "service_repair", "service_verify"],
    ),
    (
        "missing-env",
        "The disposable service fails to start. Its maintained config_check helper diagnoses "
        "required settings. Identify the cause and where the value belongs; do not invent a value.",
        ["config_check"],
    ),
    (
        "current-data",
        "Report the current latest published Ollama release tag. Fetch the official GitHub API at "
        f"{RELEASE_URL}. Use fetched data; if unavailable, say so.",
        ["web_fetch"],
    ),
]

# Simulated helper responses. The boolean marks a stopping point.
HELPER_RESPONSES: dict[str, tuple[dict[str, Any], bool]] = {
    "google_auth": ({"status": "authenticated", "verified": True}, True),
    "google_recover": (
        {"status": "user_consent_required", "authorization_url": CONSENT_URL, "authenticated": False},
        True,
    ),
    "service_status": (
        {"status": "failed", "cause": "demo service disabled", "repair_helper": "service_repair"},
        False,
    ),
    "service_repair": ({"status": "repaired", "next": "service_verify"}, False),
    "service_verify": ({"status": "healthy", "verified": True}, True),
    "config_check": (
        {
            "status": "missing_required_environment",
            "missing": "API_KEY",
            "location": "disposable service .env",
            "value_available": False,
        },
        True,
    ),
}

UNSUPPORTED = {"error": "Unsupported or out-of-scope sandbox action. Stop and report the limitation."}


def system_prompt() -> str:
    today = datetime.datetime.now(datetime.UTC).date().isoformat()
    return (
        "You are evaluating an assistant in a disposable sandbox. Use the provided tools when "
        "necessary, follow maintained helpers, and respect explicit stop conditions. No real "
        "credentials or personal services are available. Do not claim to have performed actions "
        f"without tool evidence. Current UTC date: {today}"
    )


def chat(model: str, port: str, messages: list[dict], think: bool) -> tuple[dict, dict]:
    """Send one chat turn. Returns (assistant message, timing record)."""
    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "stream": False,
        "reasoning_effort": "medium" if think else "none",
        "max_tokens": 2048,
        "temperature": 0,
        "seed": 42,
    }
    start = time.monotonic()
    response = post_json(ollama_url(port, "/v1/chat/completions"), payload, timeout=600)
    choice = response["choices"][0]
    usage = response.get("usage", {})
    message = choice["message"]
    timing = {
        "prompt_eval_count": usage.get("prompt_tokens"),
        "eval_count": usage.get("completion_tokens"),
        "done_reason": choice.get("finish_reason"),
        "wall_seconds": time.monotonic() - start,
        "wire_reasoning_chars": len(message.get("reasoning_content") or message.get("reasoning") or ""),
        "raw_think_delimiter": "</think>" in (message.get("content") or ""),
    }
    return message, timing


def fetch_release() -> dict[str, Any]:
    release = get_json(RELEASE_URL, timeout=20, headers={"User-Agent": "local-ai-assistant-synthetic-reliability"})
    result = {key: release.get(key) for key in ("tag_name", "published_at", "html_url")}
    result["fetched_at_utc"] = datetime.datetime.now(datetime.UTC).isoformat()
    return result


def parse_arguments(raw: Any) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return {}
    return raw or {}


def score(name: str, passed: bool, final: str, live_tag: str | None, live_unavailable: bool) -> bool:
    """Apply the case-specific checks on the final answer."""
    lower = final.lower()
    if name == "auth-revoked":
        return (
            passed
            and any(word in lower for word in ("consent", "authoriz", "sign in"))
            and "example.invalid/synthetic-consent" in final
            and not any(word in lower for word in ("authentication succeeded", "successfully authenticated"))
        )
    if name == "missing-env":
        return (
            passed
            and "api_key" in lower
            and ".env" in lower
            and not any(word in lower for word in ("now fixed", "successfully fixed"))
        )
    if name == "current-data":
        found_tag = bool(live_tag) and live_tag in final
        reported_unavailable = live_unavailable and any(
            word in lower for word in ("unavailable", "unable", "could not", "cannot")
        )
        return passed and (found_tag or reported_unavailable)
    return passed


def run_case(model: str, port: str, think: bool, name: str, prompt: str, expected: list[str]) -> dict:
    messages: list[dict] = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": prompt},
    ]
    calls: list[str] = []
    extra: list[str] = []
    timings: list[dict] = []
    errors: list[str] = []
    final = ""
    terminal = False
    live_tag = None
    live_unavailable = False

    for _ in range(MAX_TURNS):
        try:
            message, timing = chat(model, port, messages, think)
        except Exception as error:
            errors.append(short_error(error, 120))
            break
        timings.append(timing)
        messages.append(message)

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            final = final_answer(message.get("content"))
            break

        for call in tool_calls:
            function = call.get("function", {})
            tool_name = function.get("name", "")
            args = parse_arguments(function.get("arguments"))

            if tool_name == "run_helper":
                action = args.get("helper")
            elif tool_name == "web_fetch":
                action = "web_fetch"
            else:
                action = "unsupported"
            calls.append(action)

            # A call is extra if it comes after a stopping point, past the expected length, or out of order.
            position = len(calls) - 1
            if terminal or position >= len(expected) or action != expected[position]:
                extra.append(action)

            response: dict[str, Any] = UNSUPPORTED
            if tool_name == "run_helper" and action in expected:
                response, stops = HELPER_RESPONSES[action]
                terminal = terminal or stops
            elif tool_name == "web_fetch" and name == "current-data" and args.get("url") == RELEASE_URL:
                try:
                    response = fetch_release()
                    live_tag = response["tag_name"]
                except Exception:
                    live_unavailable = True
                    response = {"status": "unavailable", "source": args["url"]}
                terminal = True

            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(response)})

        if extra:
            break

    passed = calls == expected and not errors and not extra and bool(final) and terminal
    return {
        "test": name,
        "pass": bool(score(name, passed, final, live_tag, live_unavailable)),
        "tool_sequence": calls,
        "unnecessary_actions": extra,
        "stop_condition": terminal and not extra and bool(final),
        "final_chars": len(final),
        "errors": errors,
        "timings": timings,
        "source_live": name == "current-data" and live_tag is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model")
    parser.add_argument("port")
    parser.add_argument("think", choices=["true", "false"])
    parser.add_argument("label")
    args = parser.parse_args()
    think = args.think == "true"
    out_path = output_dir() / f"{args.label}.json"

    results = []
    for name, prompt, expected in CASES:
        result = run_case(args.model, args.port, think, name, prompt, expected)
        results.append(result)
        write_json(
            out_path,
            {
                "model": args.model,
                "think": think,
                "num_ctx": 131072,
                "synthetic_tools": True,
                "protocol": "openai-compatible",
                "reasoning_effort": "medium" if think else "none",
                "tests": results,
            },
        )
        status = "PASS" if result["pass"] else "FAIL"
        print(name, status, "tools", result["tool_sequence"], "extra", result["unnecessary_actions"], flush=True)


if __name__ == "__main__":
    main()
