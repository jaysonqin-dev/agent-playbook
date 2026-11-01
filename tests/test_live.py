import contextlib
import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from evalkit import live
from evalkit.case import Case, load_cases, load_responses
from evalkit.cli import main
from evalkit.live import LiveError, chat_completion, run_live
from evalkit.runner import run_cases

ROOT = Path(__file__).resolve().parent.parent
CASES_FILE = ROOT / "evals/cases/inventory_assistant.jsonl"
SECRET = "sk-test-0123456789-not-a-real-key"


def final(text):
    return 200, {"choices": [{"message": {"role": "assistant", "content": text}}]}


def tool_call(name, args, call_id="call_1"):
    call = {"id": call_id, "type": "function", "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}
    return 200, {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}]}


class FakeServer:
    """An OpenAI-compatible endpoint on 127.0.0.1 that plays back a script and records every request."""

    def __init__(self, script):
        self.script = script  # list of (status, body), the last one repeats; or callable(index, request_json)
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length))
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "json": payload})
                index = len(outer.requests) - 1
                if callable(outer.script):
                    status, body = outer.script(index, payload)
                else:
                    status, body = outer.script[min(index, len(outer.script) - 1)]
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()


def one_case(case_id="md1", prompt="How many units of TJX1-M-BLK can we sell right now?"):
    return Case(case_id, "x", prompt, [{"check": "contains", "value": "100"}])


def run_one(server, case=None, **kwargs):
    options = dict(instructions="be brief", model="test-model", base_url=server.url, api_key=SECRET, sleep=lambda s: None)
    options.update(kwargs)
    return run_live([case or one_case()], **options)


class LiveRunnerTests(unittest.TestCase):
    def test_tool_call_then_answer_is_recorded_in_the_transcript_format(self):
        with FakeServer([tool_call("inventory_query", {"sku": "TJX1-M-BLK"}), final("You can sell 100 units.")]) as server:
            (row,) = run_one(server)
        self.assertEqual(row["id"], "md1")
        self.assertEqual(row["text"], "You can sell 100 units.")
        self.assertEqual(row["tool_calls"], [{"name": "inventory_query", "args": {"sku": "TJX1-M-BLK"}}])
        self.assertEqual(set(row), {"id", "text", "tool_calls", "meta"})

    def test_request_shape(self):
        with FakeServer([final("ok")]) as server:
            run_one(server, temperature=0.2)
        request = server.requests[0]
        self.assertEqual(request["path"], "/chat/completions")
        self.assertEqual(request["auth"], f"Bearer {SECRET}")
        body = request["json"]
        self.assertEqual((body["model"], body["temperature"]), ("test-model", 0.2))
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertEqual(body["messages"][0]["content"], "be brief")
        self.assertEqual(len(body["tools"]), 6)

    def test_base_url_trailing_slash_is_tolerated(self):
        with FakeServer([final("ok")]) as server:
            run_one(server, base_url=server.url + "/v1/")
        self.assertEqual(server.requests[0]["path"], "/v1/chat/completions")

    def test_tool_calls_execute_against_the_mock_backend(self):
        with FakeServer([tool_call("inventory_query", {"sku": "TJX1-M-BLK"}), final("done")]) as server:
            run_one(server)
        messages = server.requests[1]["json"]["messages"]
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "tool"])
        self.assertEqual(json.loads(messages[3]["content"])["available_units"], 100)
        self.assertEqual(messages[3]["tool_call_id"], "call_1")

    def test_each_case_gets_a_fresh_backend(self):
        def script(index, payload):
            return final("done") if index % 2 else tool_call("create_order", {"sku": "SBX2-S-GRY", "qty": 5})

        with FakeServer(script) as server:
            rows = run_live([one_case("a"), one_case("b")], instructions="x", model="m", base_url=server.url, api_key=SECRET)
        self.assertEqual([len(r["tool_calls"]) for r in rows], [1, 1])

    def test_sandboxed_writes_are_still_recorded_as_calls(self):
        args = {"to": "buyer@example.com", "subject": "s", "body": "b"}
        with FakeServer([tool_call("send_email", args), final("sent")]) as server:
            (row,) = run_one(server)
        self.assertEqual(row["tool_calls"][0], {"name": "send_email", "args": args})
        self.assertIn("sandbox", server.requests[1]["json"]["messages"][-1]["content"])

    def test_invalid_tool_arguments_are_recorded_and_reported_to_the_model(self):
        with FakeServer([tool_call("inventory_query", "{not json"), final("sorry")]) as server:
            (row,) = run_one(server)
        self.assertEqual(row["tool_calls"], [{"name": "inventory_query", "args": {}}])
        self.assertIn("error", json.loads(server.requests[1]["json"]["messages"][-1]["content"]))

    def test_unknown_tool_is_recorded_and_answered_with_an_error(self):
        with FakeServer([tool_call("delete_orders", {}), final("cannot")]) as server:
            (row,) = run_one(server)
        self.assertEqual(row["tool_calls"][0]["name"], "delete_orders")
        self.assertIn("unknown tool", server.requests[1]["json"]["messages"][-1]["content"])

    def test_meta_is_filled_and_keeps_the_host_only(self):
        with FakeServer([final("ok")]) as server:
            (row,) = run_one(server, instructions="hello", base_url=server.url + "/v1")
        meta = row["meta"]
        self.assertEqual(meta["model"], "test-model")
        self.assertEqual(meta["base_url_host"], "127.0.0.1")
        self.assertEqual(meta["instructions_sha256"], hashlib.sha256(b"hello").hexdigest())
        self.assertEqual((meta["steps"], meta["truncated"]), (1, False))
        self.assertRegex(meta["timestamp_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_max_steps_truncates_and_keeps_the_transcript_so_far(self):
        with FakeServer([tool_call("inventory_list", {"page": 1})]) as server:
            (row,) = run_one(server, max_steps=3)
        self.assertEqual(len(server.requests), 3)
        self.assertEqual(len(row["tool_calls"]), 3)
        self.assertEqual((row["meta"]["steps"], row["meta"]["truncated"]), (3, True))

    def test_answer_on_the_last_allowed_step_is_not_truncated(self):
        with FakeServer([tool_call("inventory_list", {"page": 1}), final("ok")]) as server:
            (row,) = run_one(server, max_steps=2)
        self.assertEqual((row["meta"]["steps"], row["meta"]["truncated"]), (2, False))

    def test_malformed_response_is_an_error(self):
        with FakeServer([(200, {"unexpected": True})]) as server:
            with self.assertRaisesRegex(LiveError, "unexpected response shape"):
                run_one(server)

    def test_on_row_fires_per_case(self):
        seen = []
        with FakeServer([final("ok")]) as server:
            run_one(server, on_row=seen.append)
        self.assertEqual([r["id"] for r in seen], ["md1"])


class RetryTests(unittest.TestCase):
    def test_429_then_success_retries(self):
        sleeps = []
        with FakeServer([(429, {"error": "slow down"}), final("ok")]) as server:
            (row,) = run_one(server, sleep=sleeps.append)
        self.assertEqual(row["text"], "ok")
        self.assertEqual(len(server.requests), 2)
        self.assertEqual(len(sleeps), 1)

    def test_5xx_is_retried_at_most_three_times(self):
        sleeps = []
        with FakeServer([(503, {"error": "down"})]) as server:
            with self.assertRaisesRegex(LiveError, "HTTP 503"):
                run_one(server, sleep=sleeps.append)
        self.assertEqual(len(server.requests), 4)
        self.assertEqual(len(sleeps), 3)

    def test_backoff_is_short_and_capped(self):
        self.assertEqual([live._backoff(n, None) for n in range(5)], [0.5, 1.0, 2.0, 4.0, 4.0])
        self.assertEqual(live._backoff(0, "999"), live.MAX_BACKOFF_SECONDS)

    def test_other_client_errors_are_not_retried(self):
        sleeps = []
        with FakeServer([(400, {"error": "bad request"})]) as server:
            with self.assertRaisesRegex(LiveError, "HTTP 400"):
                run_one(server, sleep=sleeps.append)
        self.assertEqual(len(server.requests), 1)
        self.assertEqual(sleeps, [])

    def test_unreachable_endpoint_is_a_clear_error(self):
        with FakeServer([final("x")]) as server:
            url = server.url
        with self.assertRaisesRegex(LiveError, "could not reach"):
            chat_completion(url + "/chat/completions", SECRET, {}, timeout=2, sleep=lambda s: None)


class KeyHandlingTests(unittest.TestCase):
    def test_key_echoed_by_the_server_is_scrubbed_from_the_exception(self):
        def script(index, payload):
            return 401, {"error": f"invalid credentials: Bearer {SECRET}"}

        with FakeServer(script) as server:
            with self.assertRaises(LiveError) as caught:
                run_one(server)
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertIn("HTTP 401", str(caught.exception))

    def test_plain_http_to_a_remote_host_is_refused_before_any_request(self):
        with self.assertRaisesRegex(LiveError, "plain http"):
            run_live([one_case()], instructions="x", model="m", base_url="http://models.example.com/v1", api_key=SECRET)

    def test_non_http_schemes_are_refused(self):
        with self.assertRaisesRegex(LiveError, "http"):
            run_live([one_case()], instructions="x", model="m", base_url="file:///etc/passwd", api_key=SECRET)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.out = Path(self.dir.name) / "out" / "live.jsonl"
        self.instructions = Path(self.dir.name) / "i.md"
        self.instructions.write_text("You are an inventory assistant.", encoding="utf-8")

    def cli(self, server_url, *extra, env=None):
        argv = [
            "live", "--cases", str(CASES_FILE), "--instructions", str(self.instructions), "--out", str(self.out),
            "--model", "test-model", "--base-url", server_url, *extra,
        ]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"EVALKIT_API_KEY": SECRET} if env is None else env, clear=True):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def written(self):
        return [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]

    def test_missing_key_is_a_clear_error_and_needs_no_network(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
            code, out, err = self.cli("http://127.0.0.1:9", env={})
        self.assertEqual(code, 2)
        self.assertIn("EVALKIT_API_KEY is not set", err)
        self.assertIn("export EVALKIT_API_KEY", err)
        self.assertFalse(self.out.exists())

    def test_missing_key_names_a_custom_variable(self):
        code, _, err = self.cli("http://127.0.0.1:9", "--api-key-env", "MY_KEY", env={"EVALKIT_API_KEY": SECRET})
        self.assertEqual(code, 2)
        self.assertIn("MY_KEY is not set", err)
        self.assertNotIn(SECRET, err)

    def test_custom_key_variable_is_used(self):
        with FakeServer([final("ok")]) as server:
            code, _, _ = self.cli(server.url, "--only", "md1", "--api-key-env", "MY_KEY", env={"MY_KEY": "other-secret"})
        self.assertEqual(code, 0)
        self.assertEqual(server.requests[0]["auth"], "Bearer other-secret")

    def test_only_filters_cases_and_the_key_stays_out_of_every_output(self):
        with FakeServer([tool_call("inventory_query", {"sku": "TJX1-M-BLK"}), final("100 units")]) as server:
            code, out, err = self.cli(server.url, "--only", "md1")
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in self.written()], ["md1"])
        for text in (out, err, self.out.read_text(encoding="utf-8")):
            self.assertNotIn(SECRET, text)
        self.assertIn("python3 -m evalkit run", out)

    def test_only_accepts_a_comma_list_and_keeps_case_file_order(self):
        with FakeServer([final("ok")]) as server:
            code, _, _ = self.cli(server.url, "--only", "tr1, md1")
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in self.written()], ["md1", "tr1"])

    def test_unknown_only_id_is_rejected(self):
        code, _, err = self.cli("http://127.0.0.1:9", "--only", "nope")
        self.assertEqual(code, 2)
        self.assertIn("nope", err)

    def test_full_run_writes_all_cases_and_the_harness_grades_it(self):
        with FakeServer([final("I don't know.")]) as server:
            code, _, _ = self.cli(server.url)
        self.assertEqual(code, 0)
        responses = load_responses(self.out)
        cases = load_cases(CASES_FILE)
        self.assertEqual(set(responses), {c.id for c in cases})
        self.assertEqual(len(run_cases(cases, responses)), len(cases))
        self.assertEqual(responses["md1"].meta["model"], "test-model")

    def test_max_steps_flag_marks_the_transcript_truncated(self):
        with FakeServer([tool_call("inventory_list", {"page": 1})]) as server:
            code, out, _ = self.cli(server.url, "--only", "nm4", "--max-steps", "2")
        self.assertEqual(code, 0)
        (row,) = self.written()
        self.assertTrue(row["meta"]["truncated"])
        self.assertEqual(len(row["tool_calls"]), 2)
        self.assertIn("(truncated)", out)

    def test_endpoint_error_exits_nonzero_keeps_finished_cases_and_hides_the_key(self):
        def script(index, payload):
            return final("ok") if index == 0 else (401, {"error": f"bad key {SECRET}"})

        with FakeServer(script) as server:
            code, out, err = self.cli(server.url, "--only", "md1,md2")
        self.assertEqual(code, 1)
        self.assertIn("1/2 cases saved", err)
        self.assertEqual(len(self.written()), 1)
        for text in (out, err, self.out.read_text(encoding="utf-8")):
            self.assertNotIn(SECRET, text)


class TranscriptCompatibilityTests(unittest.TestCase):
    def test_loader_accepts_rows_with_and_without_meta(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.jsonl"
            rows = [
                {"id": "a", "text": "x", "tool_calls": []},
                {"id": "b", "text": "y", "tool_calls": [{"name": "t", "args": {"k": 1}}], "meta": {"model": "m", "steps": 2}},
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            loaded = load_responses(path)
        self.assertEqual(loaded["a"].meta, {})
        self.assertEqual(loaded["b"].meta["model"], "m")
        self.assertEqual(loaded["b"].tool_calls[0].args, {"k": 1})

    def test_committed_transcripts_still_load(self):
        for name in ("v1.jsonl", "v2.jsonl"):
            self.assertEqual(len(load_responses(ROOT / "evals/transcripts" / name)), 25)

    def test_instruction_files_exist_and_v2_extends_v1(self):
        v1 = (ROOT / "evals/instructions/v1.md").read_text(encoding="utf-8")
        v2 = (ROOT / "evals/instructions/v2.md").read_text(encoding="utf-8")
        self.assertIn("planned actions", v2)
        self.assertNotIn("planned actions", v1)
        self.assertTrue(v2.startswith(v1.rstrip()))


if __name__ == "__main__":
    unittest.main()
