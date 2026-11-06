from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import srt

import llmsrt


def event(value):
    return ("data: " + json.dumps(value, ensure_ascii=False) + "\n\n").encode()


def stream(content, *, finish="stop", usage=None, separate_usage=True, done=True):
    chunks = [b": keepalive\n\n", event({"choices": [{"index": 0, "delta": {
        "reasoning_content": "PRIVATE_THINKING"}}]})]
    for offset in range(0, len(content), 7):
        chunks.append(event({"choices": [{"index": 0, "delta": {"content": content[offset:offset + 7]}}]}))
    if finish is not None:
        chunks.append(event({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                             "usage": None if separate_usage else usage}))
    if separate_usage:
        chunks.append(event({"choices": [], "usage": usage}))
    if done:
        chunks.append(b"data: [DONE]\n\n")
    return io.BytesIO(b"".join(chunks))


class StreamingTests(unittest.TestCase):
    requested = [{"id": 1, "targets": ["ja"]}, {"id": 2, "targets": ["ja"]}]
    items = [{"id": 1, "translations": {"ja": '訳文 { [ " one'}},
             {"id": 2, "translations": {"ja": "訳文二\n次の行"}}]

    def args(self, *extra):
        args = llmsrt.argument_parser().parse_args([
            "--api-key-env", "LLMSRT_TEST_KEY", "--retries", "0", *extra])
        llmsrt.configure_llm(args)
        return args

    def test_streaming_receives_entries_before_completion_and_counts_usage_once(self):
        for separate in (True, False):  # OpenAI and DeepSeek usage placement.
            with self.subTest(separate=separate):
                progress = llmsrt.ProgressReporter("test", 1, 1, interval=5, enabled=False)
                progress.set_stage("translating subtitles", total=2)
                progress.begin_response(2)
                counts = []
                receive = progress.receive_response

                def update(*args):
                    receive(*args)
                    counts.append(progress.response_received)
                    self.assertEqual(progress.completed, 0)
                    self.assertNotIn("PRIVATE_THINKING", progress.detail)

                content = json.dumps({"items": self.items, "story_update": {"summary": "PRIVATE_STORY"}},
                                     ensure_ascii=False)
                with patch.object(progress, "receive_response", side_effect=update):
                    result = llmsrt.read_llm_response(stream(content, usage={
                        "prompt_tokens": 100, "completion_tokens": 30}, separate_usage=separate),
                        self.requested, progress)
                self.assertIn(1, counts)
                self.assertEqual(counts[-1], 2)
                self.assertEqual(result["usage"]["completion_tokens"], 30)
                self.assertEqual(llmsrt.LLMTranslator.validate(result, self.requested),
                                 {item["id"]: item["translations"] for item in self.items})
                self.assertEqual(progress.reasoning_chars, len("PRIVATE_THINKING"))
                self.assertNotIn("PRIVATE_STORY", progress.detail)

    def test_preview_ignores_incomplete_wrong_duplicate_and_nested_entries(self):
        preview = llmsrt.StreamedItems(self.requested)
        prefix = '{"story_update":{"items":[{"id":2,"translations":{"ja":"hidden"}}]},"items":['
        self.assertEqual(preview.feed(prefix), 0)
        text = json.dumps(self.items[0])
        self.assertEqual(preview.feed(text[:-1]), 0)
        self.assertEqual(preview.feed(text[-1:]), 1)
        for item in (self.items[0], {"id": True, "translations": {"ja": "yes"}},
                     {"id": 99, "translations": {"ja": "unknown"}},
                     {"id": 2, "translations": {"zh": "wrong"}},
                     {"id": 2, "translations": {"ja": " "}}):
            self.assertEqual(preview.feed("," + json.dumps(item)), 1)
        for char in "," + json.dumps(self.items[1]) + "]}":
            preview.feed(char)
        self.assertEqual(preview.received, {1, 2})

    def test_stream_errors_and_tool_calls_are_not_accepted(self):
        content = json.dumps({"items": self.items})
        for response in (stream(content, finish=None), stream(content, finish=None, done=False),
                         io.BytesIO(b'data: broken\n\n'),
                         io.BytesIO(event({"error": {"message": "provider failed"}})),
                         io.BytesIO(event({"choices": [None]}))):
            with self.subTest(response=response), self.assertRaises(llmsrt.InvalidLLMResponse):
                llmsrt.read_llm_response(response, self.requested)
        for key in ("tool_calls", "function_call"):
            response = io.BytesIO(event({"choices": [{"delta": {key: [{"name": "search"}]}}]}))
            with self.assertRaisesRegex(llmsrt.LlmsrtError, "tool use is disabled"):
                llmsrt.read_llm_response(response, self.requested)
        result = llmsrt.read_llm_response(stream(content, finish="length"), self.requested)
        with self.assertRaises(llmsrt.TruncatedLLMResponse):
            llmsrt.LLMTranslator.validate(result, self.requested)
        result = llmsrt.read_llm_response(io.BytesIO(event({"choices": [{"delta": {"refusal": "no"},
            "finish_reason": "stop"}]}) + b"data: [DONE]\n\n"), self.requested)
        with self.assertRaisesRegex(llmsrt.LlmsrtError, "refused"):
            llmsrt.LLMTranslator.validate(result, self.requested)

    def test_sse_comments_multiline_crlf_eof_and_json_gateway_fallback(self):
        raw = b': ping\r\nevent: message\r\ndata: {"choices":\r\ndata: []}\r\n\r\ndata: [DONE]'
        self.assertEqual(list(llmsrt.sse_data(io.BytesIO(raw))), ['{"choices":\n[]}', '[DONE]'])
        result = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        self.assertEqual(llmsrt.read_llm_response(io.BytesIO(
            ("\n" + json.dumps(result, indent=2)).encode()), self.requested), result)

    def test_transport_configuration_and_quips_remain_nonstreaming(self):
        for provider in ("openai", "deepseek", "custom"):
            extra = ["--provider", provider]
            if provider == "custom":
                extra += ["--model", "custom", "--base-url", "https://example.invalid"]
            for enabled in (True, False):
                args = self.args(*extra, *([] if enabled else ["--no-stream"]))
                translator = llmsrt.LLMTranslator(args, Mock())
                with patch.dict("os.environ", {"LLMSRT_TEST_KEY": "key"}), \
                        patch.object(translator.opener, "open", return_value=stream('{}')) as api:
                    translator.request({"items": self.requested})
                body = json.loads(api.call_args.args[0].data)
                self.assertEqual(body["stream"], enabled)
                self.assertEqual("stream_options" in body, enabled and provider != "custom")
                self.assertFalse(llmsrt.TOOL_PARAMETERS & body.keys())
        with patch.dict("os.environ", {"LLMSRT_TEST_KEY": "key"}):
            request, _ = llmsrt.make_llm_request(self.args(), llmsrt.QUIP_PROMPT, {})
        self.assertFalse(json.loads(request.data)["stream"])
        self.assertNotIn("stream_options", json.loads(request.data))
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text('{"stream": false}')
            for extra, expected in (([], False), (["--stream"], True)):
                with patch("sys.argv", ["llmsrt", "--config", str(config), *extra]):
                    self.assertEqual(llmsrt.configured_arguments(llmsrt.argument_parser()).stream, expected)
        args.stream = "true"
        with self.assertRaisesRegex(llmsrt.LlmsrtError, "stream"):
            llmsrt.configure_llm(args)

    def test_interrupted_stream_caches_nothing_and_retry_starts_from_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = llmsrt.TranslationCache(Path(directory) / "cache.sqlite3")
            self.addCleanup(cache.close)
            args = self.args("--batch-size", "2", "--retries", "1")
            translator = llmsrt.LLMTranslator(args, cache)
            progress = llmsrt.ProgressReporter("test", 1, 1, interval=5, enabled=False)
            cues = [srt.Subtitle(i, timedelta(seconds=i), timedelta(seconds=i + 1), f"Hello {i}") for i in (1, 2)]
            attempts, counts = [], []
            first = stream(json.dumps({"items": self.items[:1]}), finish=None, done=False)
            second = stream(json.dumps({"items": self.items}), usage={"prompt_tokens": 10, "completion_tokens": 5})

            def open_response(*unused, **kwargs):
                self.assertEqual(progress.response_received, 0)
                self.assertEqual(progress.completed, 0)
                self.assertEqual(cache.connection.execute("SELECT COUNT(*) FROM translations").fetchone()[0], 0)
                attempts.append(True)
                return first if len(attempts) == 1 else second

            receive = progress.receive_response

            def update(*args):
                receive(*args)
                counts.append(progress.response_received)
                self.assertEqual(progress.completed, 0)
                self.assertEqual(cache.connection.execute("SELECT COUNT(*) FROM translations").fetchone()[0], 0)

            with patch.dict("os.environ", {"LLMSRT_TEST_KEY": "key"}), \
                    patch.object(translator.opener, "open", side_effect=open_response), \
                    patch.object(progress, "receive_response", side_effect=update), \
                    self.assertLogs(llmsrt.LOG, "WARNING"):
                output = translator.translate_cues(cues, "en", ["ja", "en"], {}, progress)
            self.assertEqual(len(attempts), 2)
            self.assertIn(1, counts)
            self.assertEqual([row["ja"] for row in output], [item["translations"]["ja"] for item in self.items])
            self.assertEqual(progress.completed, 2)
            self.assertEqual(progress.response_total, 0)
            self.assertEqual((progress.input_tokens, progress.output_tokens), (10, 5))
            args.offline = True
            with patch.object(translator.opener, "open", side_effect=AssertionError("cache miss")):
                self.assertEqual(translator.translate_cues(cues, "en", ["ja", "en"], {}, progress), output)

    def test_timeout_during_stream_resets_receipt_before_network_retry(self):
        class BrokenStream(io.BytesIO):
            def __iter__(self):
                while line := self.readline():
                    yield line
                raise TimeoutError("connection timed out")

        args = self.args("--retries", "1")
        translator = llmsrt.LLMTranslator(args, Mock())
        progress = llmsrt.ProgressReporter("test", 1, 1, interval=5, enabled=False)
        translator.progress = progress
        content = json.dumps({"items": self.items})
        broken = BrokenStream(stream(content, finish=None, done=False).getvalue())
        attempts = []

        def respond(*unused, **kwargs):
            self.assertEqual(progress.response_received, 0)
            attempts.append(True)
            return broken if len(attempts) == 1 else stream(content)

        with patch.dict("os.environ", {"LLMSRT_TEST_KEY": "key"}), \
                patch.object(translator.opener, "open", side_effect=respond), \
                patch("llmsrt.time.sleep") as sleep, self.assertLogs(llmsrt.LOG, "WARNING"):
            result = translator.request({"items": self.requested})
        self.assertEqual(len(attempts), 2)
        sleep.assert_called_once_with(2)
        self.assertEqual(len(llmsrt.LLMTranslator.validate(result, self.requested)), 2)
        self.assertEqual(progress.completed, 0)

    def test_full_translation_stream_truncation_splits_without_caching_partial_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = llmsrt.TranslationCache(Path(directory) / "cache.sqlite3")
            self.addCleanup(cache.close)
            args = self.args("--full-translation", "--batch-size", "1")
            translator = llmsrt.LLMTranslator(args, cache)
            progress = llmsrt.ProgressReporter("test", 1, 1, interval=5, enabled=False)
            cues = [srt.Subtitle(i, timedelta(seconds=i), timedelta(seconds=i + 1), f"Hello {i}") for i in (1, 2)]
            batches = []

            def respond(request, **kwargs):
                payload = json.loads(json.loads(request.data)["messages"][1]["content"])
                ids = [item["id"] for item in payload["items"]]
                batches.append(ids)
                if len(ids) == 2:
                    return stream('{"items":[' + json.dumps(self.items[0]) + ",", finish="length")
                self.assertEqual(progress.response_received, 0)
                self.assertEqual(progress.completed, ids[0] - 1)
                return stream(json.dumps({"items": [self.items[ids[0] - 1]]}))

            with patch.dict("os.environ", {"LLMSRT_TEST_KEY": "key"}), \
                    patch.object(translator.opener, "open", side_effect=respond), \
                    patch.object(cache, "save_batch", wraps=cache.save_batch) as save, \
                    self.assertLogs(llmsrt.LOG, "WARNING"):
                output = translator.translate_cues(cues, "en", ["ja", "en"], {}, progress)
            self.assertEqual(batches, [[1, 2], [1], [2]])
            self.assertEqual(save.call_count, 2)
            self.assertEqual(progress.completed, 2)
            self.assertEqual([row["ja"] for row in output], [item["translations"]["ja"] for item in self.items])


if __name__ == "__main__":
    unittest.main()
