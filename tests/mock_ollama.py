"""A scripted stand-in for Ollama, used to test the harness without a GPU.

It plays a well-behaved model: for each reliability case it calls exactly the expected tools,
then gives a final answer that satisfies the scorer. /api/generate answers the prefill and
context-probe prompts correctly. Every request body is appended to $MOCK_LOG if set.

Run: python3 tests/mock_ollama.py PORT
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Keyword in the user prompt -> (tool calls in order, final answer)
RELIABILITY_PLANS = [
    ("google_auth helper", [("run_helper", {"helper": "google_auth"})], "Authentication succeeded and is verified."),
    (
        "revoked token",
        [("run_helper", {"helper": "google_recover"})],
        "Consent is required. Open https://example.invalid/synthetic-consent to authorize access.",
    ),
    (
        "demo service",
        [
            ("run_helper", {"helper": "service_status"}),
            ("run_helper", {"helper": "service_repair"}),
            ("run_helper", {"helper": "service_verify"}),
        ],
        "The service was repaired and verified healthy.",
    ),
    (
        "config_check helper",
        [("run_helper", {"helper": "config_check"})],
        "The service is missing API_KEY. Add it to the service .env file.",
    ),
    (
        "latest published Ollama release",
        [("web_fetch", {"url": "https://api.github.com/repos/ollama/ollama/releases/latest"})],
        None,  # built from the tool result
    ),
]

ANCHOR_PATTERN = re.compile(r"ANCHOR (start|middle|end): ([A-Z]+-\d+)")

EVENT = "a1b2c3d4e5f6"
ZONE = "America/Indiana/Indianapolis"
PATCH_BODY = {
    "start": {"dateTime": "2026-11-03T09:15:00", "timeZone": ZONE},
    "end": {"dateTime": "2026-11-03T10:45:00", "timeZone": ZONE},
}


def calendar_reply(user_prompt: str, tool_results: list[dict]) -> dict | None:
    if "Return ONLY one JSON object with eventId and body" in user_prompt:
        return {"role": "assistant", "content": json.dumps({"eventId": EVENT, "body": PATCH_BODY})}
    if user_prompt.startswith(f"Read synthetic event {EVENT}"):
        steps = [
            ("calendar_get_event", {"eventId": EVENT}),
            ("calendar_patch_event", {"eventId": EVENT, "body": PATCH_BODY}),
        ]
        if len(tool_results) < len(steps):
            name, arguments = steps[len(tool_results)]
            return {"role": "assistant", "content": "", "tool_calls": [tool_call(len(tool_results), name, arguments)]}
        return {"role": "assistant", "content": "The event now uses the named timezone. Done."}
    if "has NOT supplied the intended local start/end" in user_prompt:
        if not tool_results:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [tool_call(0, "calendar_get_event", {"eventId": EVENT})],
            }
        return {"role": "assistant", "content": "What are the intended start and end times for this event?"}
    return None


def tool_call(index: int, name: str, arguments: dict) -> dict:
    return {
        "id": f"call_{index}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def plan_reply(messages: list[dict]) -> dict:
    user_prompt = next(m["content"] for m in messages if m["role"] == "user")
    tool_results = [m for m in messages if m.get("role") == "tool"]
    calendar = calendar_reply(user_prompt, tool_results)
    if calendar:
        return calendar
    for keyword, calls, answer in RELIABILITY_PLANS:
        if keyword not in user_prompt:
            continue
        if len(tool_results) < len(calls):
            name, arguments = calls[len(tool_results)]
            return {"role": "assistant", "content": "", "tool_calls": [tool_call(len(tool_results), name, arguments)]}
        if answer is None:
            result = json.loads(tool_results[-1]["content"])
            answer = (
                f"The latest release is {result['tag_name']}."
                if "tag_name" in result
                else "The release data is unavailable."
            )
        return {"role": "assistant", "content": answer}
    return {"role": "assistant", "content": "READY"}


def generate_reply(prompt: str) -> str:
    anchors = dict(ANCHOR_PATTERN.findall(prompt))
    if anchors:
        return json.dumps(anchors)
    if "exactly VERIFIED" in prompt:
        return "VERIFIED"
    return "READY"


class Handler(BaseHTTPRequestHandler):
    log_lock = threading.Lock()

    def log_message(self, *args) -> None:  # keep test output quiet
        pass

    def send_json(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/api/ps":
            self.send_json({"models": []})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if os.environ.get("MOCK_LOG"):
            with self.log_lock, open(os.environ["MOCK_LOG"], "a") as log:
                log.write(json.dumps({"path": self.path, "body": body}) + "\n")

        if self.path == "/api/generate":
            prompt = body.get("prompt", "")
            self.send_json(
                {
                    "response": generate_reply(prompt),
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": max(1, len(prompt) // 4),
                    "prompt_eval_duration": 50_000_000,
                    "eval_count": 256,
                    "eval_duration": 2_000_000_000,
                    "load_duration": 1_000_000,
                    "total_duration": 2_100_000_000,
                }
            )
        elif self.path == "/v1/chat/completions":
            message = plan_reply(body["messages"])
            finish = "tool_calls" if message.get("tool_calls") else "stop"
            self.send_json(
                {
                    "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                }
            )
        else:
            self.send_error(404)


def serve(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    serve(int(sys.argv[1]))
    threading.Event().wait()
