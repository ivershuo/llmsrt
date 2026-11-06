import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import llmsrt


SAFE_QUIP = "正在给译文调低音量，让语气轻轻落地。"


def model_result(quips=None, **choice_fields):
    return {"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"quips": quips if quips is not None else [SAFE_QUIP]})},
        **choice_fields}], "usage": {"prompt_tokens": 12, "completion_tokens": 8}}


class ModelQuipTests(unittest.TestCase):
    def setUp(self):
        self.args = llmsrt.argument_parser().parse_args(["--api-key-env", "LLMSRT_QUIP_TEST_KEY"])
        llmsrt.configure_llm(self.args)
        self.generator = llmsrt.ModelQuips(self.args)
        self.addCleanup(self.generator.close)
        self.progress = llmsrt.ProgressReporter("test.mkv", 1, 1, interval=5, enabled=False)
        self.environment = patch.dict("os.environ", {"LLMSRT_QUIP_TEST_KEY": "private-test-key"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_filters_spoilers_names_quotes_controls_and_malformed_responses(self):
        candidates = [SAFE_QUIP, "字幕揭晓谁才是真正的凶手。", "张三正在给译文整理标点。",
                      "字幕里藏着爱丽丝的秘密。", "字幕准备迎接下一场反转。",
                      "字幕照着原句说你好朋友。", "字幕开始执行\x1b[31m红色指令。",
                      "正在翻译 Alice 的下一句话。"]
        for text in candidates:
            with self.subTest(text=text):
                self.assertEqual(llmsrt.validate_model_quips(model_result([text]), "张三：你好朋友"),
                                 (SAFE_QUIP,) if text == SAFE_QUIP else ())
        for result in (None, {}, {"choices": []}, {"choices": [None]},
                       model_result(finish_reason="length"), model_result(["太短"]),
                       model_result(message={"content": "not JSON"}),
                       model_result(message={"refusal": "no", "content": "{}"})):
            with self.subTest(result=result):
                self.assertEqual(llmsrt.validate_model_quips(result, "Hello"), ())

    def test_request_runs_in_parallel_and_only_one_worker_is_allowed(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def respond(request, **kwargs):
            entered.set()
            self.assertTrue(release.wait(1))
            return io.BytesIO(json.dumps(model_result()).encode())

        with patch("llmsrt.QUIP_DELAY", 0), patch("urllib.request.OpenerDirector.open", side_effect=respond) as api:
            with self.progress.waiting(["Coffee?"]):
                self.generator.start(self.progress, ["Coffee?"], self.progress.wait_cancel)
                self.assertTrue(entered.wait(1))
                worker = self.generator.thread
                self.generator.start(self.progress, ["Another batch"], self.progress.wait_cancel)
                self.assertIs(self.generator.thread, worker)
                # The primary thread keeps processing while the HTTP call is blocked.
                self.progress.update(completed=5)
                self.assertEqual(self.progress.completed, 5)
                release.set()
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(self.progress.wait_quips[0], SAFE_QUIP)
                self.assertEqual((self.progress.input_tokens, self.progress.output_tokens), (12, 8))
                request = api.call_args.args[0]
                body = json.loads(request.data)
                self.assertNotIn("tool_choice", body)
                self.assertNotIn("tools", body)
                self.assertEqual(json.loads(body["messages"][1]["content"]), {"current_subtitles": "Coffee?"})
                self.assertIn("NOT watched", body["messages"][0]["content"])
                self.assertEqual(body["max_completion_tokens"], 1024)
                self.assertEqual(api.call_args.kwargs["timeout"], 15)
                # A completed worker still observes the one-minute request limit.
                with patch("llmsrt.time.monotonic", return_value=self.generator.last_started + 59):
                    self.generator.start(self.progress, ["Coffee?"], self.progress.wait_cancel)
                self.assertEqual(api.call_count, 1)

    def test_quick_wait_is_cancelled_before_any_model_call(self):
        with patch("llmsrt.QUIP_DELAY", 60), patch("urllib.request.OpenerDirector.open") as api:
            with self.progress.waiting(["Hello"]):
                self.generator.start(self.progress, ["Hello"], self.progress.wait_cancel)
            self.generator.thread.join(1)
            self.assertFalse(self.generator.thread.is_alive())
            self.assertEqual(self.generator.last_started, float("-inf"))
            api.assert_not_called()

    def test_late_result_cannot_replace_next_batch_quips(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def respond(*args, **kwargs):
            entered.set()
            release.wait(1)
            return io.BytesIO(json.dumps(model_result()).encode())

        with patch("llmsrt.QUIP_DELAY", 0), patch("urllib.request.OpenerDirector.open", side_effect=respond):
            with self.progress.waiting(["Coffee?"]):
                self.generator.start(self.progress, ["Coffee?"], self.progress.wait_cancel)
                self.assertTrue(entered.wait(1))
            with self.progress.waiting(["Thank you"]):
                local = self.progress.wait_quips
                release.set()
                self.generator.thread.join(1)
                self.assertEqual(self.progress.wait_quips, local)
                self.assertNotIn(SAFE_QUIP, self.progress.wait_quips)

    def test_rate_limit_falls_back_without_logging_secrets_or_retrying(self):
        error = HTTPError("https://example.invalid", 429, "private-test-key", {}, io.BytesIO(b"plot secret"))
        with patch("llmsrt.QUIP_DELAY", 0), \
                patch("urllib.request.OpenerDirector.open", side_effect=error) as api, \
                self.assertLogs(llmsrt.LOG, "DEBUG") as logs:
            with self.progress.waiting(["Hello"]):
                local = self.progress.wait_quips
                self.generator.start(self.progress, ["Hello"], self.progress.wait_cancel)
                self.generator.thread.join(1)
                self.assertTrue(self.generator.disabled)
                self.assertEqual(self.progress.wait_quips, local)
                self.generator.start(self.progress, ["Hello"], self.progress.wait_cancel)
                self.assertEqual(api.call_count, 1)
        self.assertNotIn("private-test-key", str(logs.output))
        self.assertNotIn("plot secret", str(logs.output))

    def test_closing_does_not_wait_for_http_or_publish_after_finish(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def respond(*args, **kwargs):
            entered.set()
            release.wait(1)
            return io.BytesIO(json.dumps(model_result()).encode())

        with patch("llmsrt.QUIP_DELAY", 0), patch("urllib.request.OpenerDirector.open", side_effect=respond):
            with self.progress.waiting(["Hello"]):
                self.generator.start(self.progress, ["Hello"], self.progress.wait_cancel)
                self.assertTrue(entered.wait(1))
                self.progress.finish("done")
                self.generator.close()
                self.assertTrue(self.generator.thread.is_alive())
                release.set()
                self.generator.thread.join(1)
                self.assertNotIn(SAFE_QUIP, self.progress.wait_quips)
                self.assertEqual(self.progress.input_tokens, 0)

    def test_default_opt_out_and_config_type_validation(self):
        self.assertTrue(self.args.model_quips)
        self.assertFalse(llmsrt.argument_parser().parse_args(["--no-model-quips"]).model_quips)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"model_quips": False}))
            with patch("sys.argv", ["llmsrt", "--config", str(config)]):
                args = llmsrt.configured_arguments(llmsrt.argument_parser())
                self.assertFalse(args.model_quips)
            with patch("sys.argv", ["llmsrt", "--config", str(config), "--model-quips"]):
                args = llmsrt.configured_arguments(llmsrt.argument_parser())
                self.assertTrue(args.model_quips)
        self.args.model_quips = "false"
        with self.assertRaisesRegex(llmsrt.LlmsrtError, "model_quips"):
            llmsrt.configure_media_and_progress(self.args)


if __name__ == "__main__":
    unittest.main()
