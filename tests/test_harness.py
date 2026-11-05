"""Tests for the benchmark script and harness, run against a mock Ollama server.

Run from the repository root: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import csv
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "harness"
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(ROOT / "tests"))

import calendar_checks  # noqa: E402
import mock_ollama  # noqa: E402
import reliability_openai  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ValidatePatchTest(unittest.TestCase):
    ZONE = calendar_checks.ZONE

    def body(self, **changes):
        body = {
            "start": {"dateTime": "2026-11-03T09:15:00", "timeZone": self.ZONE},
            "end": {"dateTime": "2026-11-03T10:45:00", "timeZone": self.ZONE},
        }
        body.update(changes)
        return body

    def assert_fails(self, body, check):
        result = calendar_checks.validate(body)
        self.assertFalse(result[check], result)
        self.assertFalse(all(result.values()))

    def test_named_zone_without_offset_passes(self):
        self.assertTrue(all(calendar_checks.validate(self.body()).values()))

    def test_offset_matching_zone_passes(self):
        # 2026-11-03 is after the DST change, so Indianapolis is UTC-5.
        body = self.body(start={"dateTime": "2026-11-03T09:15:00-05:00", "timeZone": self.ZONE})
        self.assertTrue(all(calendar_checks.validate(body).values()))

    def test_stale_dst_offset_fails(self):
        body = self.body(start={"dateTime": "2026-11-03T09:15:00-04:00", "timeZone": self.ZONE})
        self.assert_fails(body, "start_offset")

    def test_shifted_wall_time_fails(self):
        body = self.body(end={"dateTime": "2026-11-03T11:45:00", "timeZone": self.ZONE})
        self.assert_fails(body, "end_wall_time")

    def test_missing_timezone_fails(self):
        body = self.body(start={"dateTime": "2026-11-03T09:15:00"})
        self.assert_fails(body, "start_timezone")

    def test_changed_recurrence_fails(self):
        self.assert_fails(self.body(recurrence=["RRULE:FREQ=DAILY"]), "preserve_recurrence")

    def test_unexpected_field_fails(self):
        self.assert_fails(self.body(attendees=[]), "only_supported_fields")

    def test_non_object_fails(self):
        self.assertEqual(calendar_checks.validate(["start"]), {"object": False})


class HarnessAgainstMockTest(unittest.TestCase):
    """Runs each script end to end against a mock model that behaves correctly."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = mock_ollama.serve(cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = pathlib.Path(self.tmp.name)
        self.env = {**os.environ, "BENCH_OUT_DIR": str(self.out)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, check=True):
        return subprocess.run(
            [sys.executable, *map(str, args)], env=self.env, capture_output=True, text=True, check=check, timeout=120
        )

    def load(self, name):
        return json.loads((self.out / name).read_text())

    def test_reliability_suite_passes_for_correct_model(self):
        self.run_script(HARNESS / "reliability_openai.py", "mock", self.port, "false", "rel")
        tests = self.load("rel.json")["tests"]
        self.assertEqual([t["test"] for t in tests], [case[0] for case in reliability_openai.CASES])
        for test in tests:
            self.assertTrue(test["pass"], test)
            self.assertEqual(test["unnecessary_actions"], [])

    def test_calendar_checks_pass_for_correct_model(self):
        self.run_script(HARNESS / "calendar_checks.py", "mock", self.port, "cal")
        tests = self.load("cal.json")["tests"]
        self.assertEqual(len(tests), 4)
        for test in tests:
            self.assertTrue(test["pass"], test)

    def test_prefill_scores_answers_after_think_tag(self):
        self.run_script(HARNESS / "prefill.py", "mock", self.port, "false", "pre")
        results = self.load("pre.json")["results"]
        self.assertEqual([r["stage"] for r in results], ["fresh-prefix", "same-prefix", "incremental-tool-result"])
        self.assertTrue(all(r["expected_answer"] for r in results))

    def test_context_probe_recalls_all_anchors(self):
        self.run_script(HARNESS / "context_probe.py", "mock", self.port, "ctx")
        result = self.load("ctx.json")["result"]
        self.assertEqual(result["anchors_recalled"], {"start": True, "middle": True, "end": True})

    def test_benchmark_script_writes_csv(self):
        output = self.out / "bench.csv"
        subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "benchmark_ollama.sh"),
                "--model",
                "mock",
                "--runs",
                "2",
                "--think",
                "true",
                "--endpoint",
                f"http://127.0.0.1:{self.port}",
                "--output",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        with output.open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["think"], "true")
        self.assertAlmostEqual(float(rows[0]["decode_tok_s"]), 128.0)

    def test_benchmark_script_rejects_bad_think_value(self):
        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "benchmark_ollama.sh"), "--model", "mock", "--think", "maybe"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)

    @unittest.skipUnless(pathlib.Path("/proc/pressure/memory").exists(), "needs Linux PSI")
    def test_memory_guard_runs_command_when_production_idle(self):
        self.env.update(PROD_OLLAMA=f"http://127.0.0.1:{self.port}", BENCH_OLLAMA=f"http://127.0.0.1:{self.port}")
        result = self.run_script(HARNESS / "memory_guard.py", "guard", sys.executable, "-c", "pass")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(self.load("guard-guard.json")["reason"])


if __name__ == "__main__":
    unittest.main()
