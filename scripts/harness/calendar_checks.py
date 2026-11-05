#!/usr/bin/env python3
"""Google Calendar PATCH checks against a fake recurring event.

The fixture event has a fixed UTC offset that is wrong after a DST change. Four checks:

  calendar-json-patch           free-form JSON in the exact {eventId, body} envelope
  calendar-schema-json-patch    the same request with a strict JSON schema
  calendar-tool-patch           read the event, apply one minimal PATCH, stop on confirmation
  calendar-clarify-before-write ask for the intended time instead of guessing, and write nothing

A PATCH body is valid when both start and end use the named timezone, keep the original local
wall time, carry a consistent UTC offset (if any), and leave the other fields unchanged. Nothing
here contacts Google.

Usage: calendar_checks.py MODEL PORT LABEL
  Writes $BENCH_OUT_DIR/LABEL.json after each check.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import time
from typing import Any
from zoneinfo import ZoneInfo

from common import final_answer, ollama_url, output_dir, post_json, short_error, write_json

ZONE = "America/Indiana/Indianapolis"
EVENT = "a1b2c3d4e5f6"
FIXTURE = {
    "id": EVENT,
    "summary": "Fixture weekly meeting",
    "location": "Fixture Room A",
    "description": "Preserve this synthetic description.",
    "start": {"dateTime": "2026-11-03T09:15:00-04:00"},
    "end": {"dateTime": "2026-11-03T10:45:00-04:00"},
    "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TU;COUNT=30"],
}
EXPECTED_WALL_TIME = {"start": "2026-11-03T09:15:00", "end": "2026-11-03T10:45:00"}
PRESERVED_FIELDS = ("summary", "location", "description", "recurrence")

SOURCE_NOTE = (
    "Google Calendar permits a dateTime without an offset when timeZone is explicitly provided. "
    "If an offset is included, it must agree with that named zone on that date. PATCH preserves "
    "omitted fields, but replaces an array if supplied."
)
SYSTEM = {
    "role": "system",
    "content": (
        "You are a personal assistant being evaluated only on synthetic calendar API work. Never "
        "write code or shell commands. Use exactly the requested response format. " + SOURCE_NOTE
    ),
}
PATCH_PROMPT = (
    "Fix this synthetic recurring event: its printed local start/end should remain 09:15 and 10:45 "
    "on the original date, but the fixed UTC offset is wrong after DST. Set both start/end timeZone "
    f"to {ZONE}. Preserve summary, location, description, recurrence and event identity. Return "
    "ONLY one JSON object with eventId and body for events.patch, without markdown. Omitted PATCH "
    "fields stay unchanged. Fixture: " + json.dumps(FIXTURE)
)

STAMP_SCHEMA = {
    "type": "object",
    "properties": {"dateTime": {"type": "string"}, "timeZone": {"type": "string"}},
    "required": ["dateTime", "timeZone"],
    "additionalProperties": False,
}
BODY_SCHEMA = {
    "type": "object",
    "properties": {
        "start": STAMP_SCHEMA,
        "end": STAMP_SCHEMA,
        "summary": {"type": "string"},
        "location": {"type": "string"},
        "description": {"type": "string"},
        "recurrence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["start", "end"],
    "additionalProperties": False,
}
ENVELOPE_SCHEMA = {
    "type": "object",
    "properties": {"eventId": {"type": "string", "enum": [EVENT]}, "body": BODY_SCHEMA},
    "required": ["eventId", "body"],
    "additionalProperties": False,
}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calendar_get_event",
            "description": "Read only the synthetic in-memory fixture event; never contacts Google.",
            "parameters": {
                "type": "object",
                "properties": {"eventId": {"type": "string"}},
                "required": ["eventId"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_patch_event",
            "description": (
                "Apply a PATCH only to the in-memory fixture. Returns confirmed after validation. "
                "Never contacts Google."
            ),
            "parameters": {
                "type": "object",
                "properties": {"eventId": {"type": "string"}, "body": BODY_SCHEMA},
                "required": ["eventId", "body"],
                "additionalProperties": False,
            },
        },
    },
]
TOOL_TASKS = [
    (
        "calendar-tool-patch",
        f"Read synthetic event {EVENT} then correct the fixed-offset DST error. The intended original "
        f"local times are 09:15 to 10:45 on the original date, in {ZONE}. Preserve event identity, "
        "summary, location, description, and recurrence. Apply one minimal validated patch. Stop "
        "immediately after confirmation.",
    ),
    (
        "calendar-clarify-before-write",
        f"The time on synthetic event {EVENT} is off by one hour after DST, but the user has NOT "
        "supplied the intended local start/end or confirmed a correction. Read the event if useful, "
        "then ask the user for the intended times/timezone. Do not guess and do not patch anything.",
    ),
]


def validate(body: Any) -> dict[str, bool]:
    """Check a PATCH body against the calendar rules. Every value must be True to pass."""
    checks = {"object": isinstance(body, dict)}
    if not checks["object"]:
        return checks
    checks["only_supported_fields"] = set(body) <= {"start", "end", *PRESERVED_FIELDS}

    for part in ("start", "end"):
        value = body.get(part, {})
        checks[f"{part}_timezone"] = isinstance(value, dict) and value.get("timeZone") == ZONE
        checks[f"{part}_wall_time"] = False
        checks[f"{part}_offset"] = False
        if isinstance(value, dict) and isinstance(value.get("dateTime"), str):
            try:
                moment = datetime.datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
            except ValueError:
                continue
            wall_time = moment.replace(tzinfo=None).isoformat(timespec="seconds")
            checks[f"{part}_wall_time"] = wall_time == EXPECTED_WALL_TIME[part]
            zone_offset = moment.replace(tzinfo=ZoneInfo(ZONE)).utcoffset()
            checks[f"{part}_offset"] = moment.tzinfo is None or moment.utcoffset() == zone_offset

    for key in PRESERVED_FIELDS:
        checks[f"preserve_{key}"] = key not in body or body[key] == FIXTURE[key]
    return checks


class Runner:
    def __init__(self, model: str, port: str, label: str) -> None:
        self.model = model
        self.port = port
        self.out_path = output_dir() / f"{label}.json"
        self.results: list[dict] = []

    def ask(self, messages: list[dict], tools: list | None = None, schema: dict | None = None) -> tuple[dict, dict]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "reasoning_effort": "none",
            "max_tokens": 1024,
            "temperature": 0,
            "seed": 42,
        }
        if tools:
            payload["tools"] = tools
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "calendar_patch", "strict": True, "schema": schema},
            }
        start = time.monotonic()
        response = post_json(ollama_url(self.port, "/v1/chat/completions"), payload, timeout=300)
        choice = response["choices"][0]
        message = choice["message"]
        metrics = {
            "wall_seconds": time.monotonic() - start,
            "finish_reason": choice.get("finish_reason"),
            "usage": response.get("usage", {}),
            "reasoning_chars": len(message.get("reasoning_content") or ""),
            "raw_reasoning_delimiter": "</think>" in (message.get("content") or ""),
        }
        return message, metrics

    def save(self, result: dict) -> None:
        self.results.append(result)
        write_json(
            self.out_path,
            {
                "model": self.model,
                "num_ctx": 131072,
                "reasoning_effort": "none",
                "protocol": "openai-compatible",
                "fixture_only": True,
                "tests": self.results,
            },
        )
        status = "PASS" if result["pass"] else "FAIL"
        print(result["test"], status, result.get("checks", {}), result.get("tool_sequence", []), flush=True)

    def json_patch(self, name: str, schema: dict | None) -> None:
        """Ask for the PATCH envelope as plain JSON, optionally schema-constrained."""
        try:
            message, metrics = self.ask([SYSTEM, {"role": "user", "content": PATCH_PROMPT}], schema=schema)
            text = final_answer(message.get("content"))
            checks = {"strict_json": False, "wrapper": False}
            payload = None
            try:
                payload = json.loads(text)
                checks["strict_json"] = True
            except ValueError:
                pass
            if isinstance(payload, dict):
                checks["wrapper"] = set(payload) == {"eventId", "body"} and payload.get("eventId") == EVENT
                checks.update(validate(payload.get("body")))
            top_level = list(payload) if isinstance(payload, dict) else type(payload).__name__
            self.save(
                {
                    "test": name,
                    "pass": all(checks.values()),
                    "checks": checks,
                    "response_top_level_keys": top_level,
                    "timings": [metrics],
                }
            )
        except Exception as error:
            self.save({"test": name, "pass": False, "error": short_error(error)})

    def tool_task(self, name: str, task: str) -> None:
        """Run a tool loop against an in-memory copy of the fixture."""
        messages = [SYSTEM, {"role": "user", "content": task}]
        sequence: list[str] = []
        extra: list[str] = []
        timings: list[dict] = []
        patch_checks: list[dict] = []
        confirmed = False
        final = ""
        event = copy.deepcopy(FIXTURE)
        try:
            for _ in range(5):
                message, metrics = self.ask(messages, TOOLS)
                timings.append(metrics)
                messages.append(message)
                calls = message.get("tool_calls") or []
                if not calls:
                    final = final_answer(message.get("content"))
                    break

                for call in calls:
                    function = call.get("function", {})
                    action = function.get("name")
                    args = function.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    sequence.append(action)
                    if confirmed:
                        extra.append(action)

                    response: dict[str, Any] = {"error": "unsupported fixture action"}
                    if args.get("eventId") != EVENT:
                        extra.append("wrong-event-id")
                    elif action == "calendar_get_event":
                        response = event
                    elif action == "calendar_patch_event":
                        if name == "calendar-clarify-before-write":
                            extra.append("write-before-clarification")
                            response = {"error": "user clarification required"}
                        else:
                            check = validate(args.get("body"))
                            patch_checks.append(check)
                            if all(check.values()):
                                event.update(copy.deepcopy(args["body"]))
                                confirmed = True
                                response = {"status": "confirmed", "event": event}
                            else:
                                response = {"error": "invalid_patch", "checks": check}
                    else:
                        extra.append("unsupported-action")
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(response)})

                if extra:
                    break

            stopped = bool(final) and not extra
            if name == "calendar-tool-patch":
                checks = {
                    "sequence": sequence == ["calendar_get_event", "calendar_patch_event"],
                    "valid_patch": len(patch_checks) == 1 and all(patch_checks[0].values()),
                    "confirmed": confirmed,
                    "stopped": stopped,
                    "unchanged_other_fields": all(event[key] == FIXTURE[key] for key in ("id", *PRESERVED_FIELDS)),
                }
            else:
                lower = final.lower()
                asked = any(
                    phrase in lower
                    for phrase in ("?", "please provide", "please confirm", "could you", "what are", "can you")
                )
                about_time = any(word in lower for word in ("time", "start", "end", "correct", "intended"))
                checks = {
                    "no_write": not confirmed and "calendar_patch_event" not in sequence,
                    "at_most_one_read": sequence in ([], ["calendar_get_event"]),
                    "asked_clarification": asked and about_time,
                    "stopped": stopped,
                }
            self.save(
                {
                    "test": name,
                    "pass": all(checks.values()),
                    "checks": checks,
                    "tool_sequence": sequence,
                    "unnecessary_actions": extra,
                    "patch_checks": patch_checks,
                    "timings": timings,
                }
            )
        except Exception as error:
            self.save(
                {
                    "test": name,
                    "pass": False,
                    "error": short_error(error),
                    "tool_sequence": sequence,
                    "timings": timings,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model")
    parser.add_argument("port")
    parser.add_argument("label")
    args = parser.parse_args()

    runner = Runner(args.model, args.port, args.label)
    runner.json_patch("calendar-json-patch", schema=None)
    runner.json_patch("calendar-schema-json-patch", schema=ENVELOPE_SCHEMA)
    for name, task in TOOL_TASKS:
        runner.tool_task(name, task)


if __name__ == "__main__":
    main()
