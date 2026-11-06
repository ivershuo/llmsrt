from copy import deepcopy
from datetime import timedelta
import json
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from rich.console import Console
import srt

import llmsrt


def response(payload, story=None, *, finish="stop"):
    items = [{"id": item["id"], "translations": {
        language: f"訳文{item['id']}" for language in item["targets"]}}
        for item in payload["items"]]
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps({
        "items": items, "story_update": story,
    })}}]}


def memory(summary, **fields):
    return {"summary": summary, "characters": {}, "terms": {}, **fields}


class StoryContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache_path = Path(self.temporary.name) / "cache.sqlite3"
        self.cache = llmsrt.TranslationCache(self.cache_path)
        self.addCleanup(lambda: self.cache.close())
        self.args = llmsrt.argument_parser().parse_args(["--batch-size", "2", "--retries", "0"])
        llmsrt.configure_llm(self.args)
        self.cues = [srt.Subtitle(index=i, start=timedelta(seconds=i), end=timedelta(seconds=i + 1),
                                  content=text) for i, text in enumerate([
            "Alice works at the observatory.", "She calls the telescope Aurora.",
            "Bob asks her for help.", "They agree to meet tomorrow.",
        ], 1)]
        self.context = {"title": "Test", "characters": "Use アリス for Alice"}

    def translator(self):
        return llmsrt.LLMTranslator(self.args, self.cache)

    def run_translation(self, translator, cues=None):
        progress = llmsrt.ProgressReporter("test.mkv", 1, 1, interval=5, enabled=False)
        return translator.translate_cues(self.cues if cues is None else cues, "en", ["ja", "en"],
                                         self.context, progress)

    def test_story_and_glossary_flow_between_batches_and_survive_cache_reopen(self):
        translator = self.translator()
        payloads = []

        def translate(payload):
            payloads.append(deepcopy(payload))
            if len(payloads) == 1:
                story = memory("爱丽丝介绍了自己的工作和望远镜。",
                               characters={"Alice": {"ja": "アリス"}},
                               terms={"Aurora": {"ja": "オーロラ"}})
            else:
                story = memory("爱丽丝介绍了工作，后来与鲍勃约定见面。",
                               characters={"Alice": {"ja": "別名"}, "Bob": {"ja": "ボブ"}},
                               terms={"Aurora": {"ja": "変更名"}})
            return response(payload, story)

        with patch.object(translator, "request", side_effect=translate) as api:
            output = self.run_translation(translator)
            self.assertEqual(api.call_count, 2)  # Summary uses the translation response.
        self.assertEqual(payloads[0]["previous_story"], {"through_id": 0, **llmsrt.empty_story()})
        self.assertEqual(payloads[1]["previous_story"]["through_id"], 2)
        self.assertIn("望远镜", payloads[1]["previous_story"]["summary"])
        self.assertEqual(translator.story["characters"]["Alice"]["ja"], "アリス")
        self.assertEqual(translator.story["terms"]["Aurora"]["ja"], "オーロラ")
        self.assertEqual([entry["ja"] for entry in output], [f"訳文{i}" for i in range(1, 5)])
        self.assertEqual([entry["en"] for entry in output], [cue.content for cue in self.cues])
        self.cache.close()
        self.cache = llmsrt.TranslationCache(self.cache_path)
        resumed = self.translator()
        self.args.offline = True
        with patch.object(resumed, "request", side_effect=AssertionError("cache miss")):
            self.assertEqual(self.run_translation(resumed), output)
        self.assertEqual(resumed.story, translator.story)
        self.assertEqual(resumed.story_through, 4)

    def test_resume_uses_only_checkpoint_before_first_missing_subtitle(self):
        translator = self.translator()
        first = memory("已经介绍工作。", characters={"Alice": {"ja": "アリス"}})
        calls = 0

        def interrupted(payload):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt()
            return response(payload, first)

        with patch.object(translator, "request", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.run_translation(translator)
        # A later checkpoint must not leak into an earlier missing batch.
        self.cache.save_batch({}, translator.session_key, 4, memory("FUTURE_SECRET"))
        resumed = self.translator()
        payloads = []

        def complete(payload):
            payloads.append(deepcopy(payload))
            return response(payload, memory("已经约好见面。"))

        with patch.object(resumed, "request", side_effect=complete) as api:
            self.run_translation(resumed)
            self.assertEqual(api.call_count, 1)
        self.assertEqual([item["id"] for item in payloads[0]["items"]], [3, 4])
        self.assertEqual(payloads[0]["previous_story"], {"through_id": 2, **first})
        self.assertNotIn("FUTURE_SECRET", json.dumps(payloads))

    def test_truncated_parent_does_not_publish_memory_and_children_advance_in_order(self):
        self.args.batch_size = 4
        translator = self.translator()
        payloads = []

        def split(payload):
            payloads.append(deepcopy(payload))
            if len(payload["items"]) > 2:
                return response(payload, memory("UNVALIDATED_SECRET"), finish="length")
            return response(payload, memory(f"已处理到第{payload['items'][-1]['id']}条。"))

        with patch.object(translator, "request", side_effect=split), self.assertLogs(llmsrt.LOG, "WARNING"):
            self.run_translation(translator)
        self.assertEqual(len(payloads), 3)
        self.assertEqual(payloads[1]["previous_story"]["through_id"], 0)
        self.assertEqual(payloads[2]["previous_story"]["through_id"], 2)
        self.assertNotIn("UNVALIDATED_SECRET", json.dumps(payloads))
        self.assertEqual(self.cache.connection.execute("SELECT COUNT(*) FROM story_contexts").fetchone()[0], 2)

    def test_invalid_translations_never_commit_their_summary(self):
        self.args.batch_size = 1
        translator = self.translator()
        bad = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "items": [], "story_update": memory("UNVALIDATED_SECRET"),
        })}}]}
        with patch.object(translator, "request", return_value=bad):
            with self.assertRaises(llmsrt.LlmsrtError):
                self.run_translation(translator)
        for table in ("translations", "story_contexts"):
            self.assertEqual(self.cache.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.assertEqual(translator.story, llmsrt.empty_story())

    def test_invalid_memory_keeps_translations_and_previous_summary(self):
        self.args.batch_size = 1
        translator = self.translator()
        payloads = []

        def translate(payload):
            payloads.append(deepcopy(payload))
            story = memory("已经介绍工作。") if len(payloads) == 1 else memory("长" * 601)
            return response(payload, story)

        with patch.object(translator, "request", side_effect=translate) as api:
            output = self.run_translation(translator)
            self.assertEqual(api.call_count, 4)
        self.assertEqual(len(output), 4)
        self.assertTrue(all(payload["previous_story"]["through_id"] == 1 for payload in payloads[1:]))
        self.assertEqual(translator.story_through, 1)
        self.assertEqual(self.cache.connection.execute("SELECT COUNT(*) FROM translations").fetchone()[0], 4)

    def test_different_work_does_not_reuse_memory_or_translations(self):
        self.args.context_cues = 0
        translator = self.translator()
        with patch.object(translator, "request", side_effect=lambda payload: response(payload, memory("前片摘要。"))):
            self.run_translation(translator)
        old_session = translator.session_key
        changed = deepcopy(self.cues)
        changed[-1].content = "A completely different ending."
        new = self.translator()
        payloads = []

        def translate(payload):
            payloads.append(deepcopy(payload))
            return response(payload, memory("新片摘要。"))

        with patch.object(new, "request", side_effect=translate) as api:
            self.run_translation(new, changed)
            self.assertEqual(api.call_count, 2)
        self.assertNotEqual(new.session_key, old_session)
        self.assertEqual(payloads[0]["previous_story"]["through_id"], 0)
        self.assertNotIn("前片摘要", json.dumps(payloads, ensure_ascii=False))

    def test_summary_bounds_and_glossary_preservation(self):
        previous = memory("旧摘要。", characters={"Alice": {"ja": "アリス"}})
        update = memory("新摘要。", characters={"Alice": {"ja": "別名", "zh-cn": "爱丽丝"}})
        merged = llmsrt.merge_story_update(previous, update, ["ja", "zh-cn"])
        self.assertEqual(merged["characters"]["Alice"], {"ja": "アリス", "zh-cn": "爱丽丝"})
        self.assertEqual(previous["characters"]["Alice"], {"ja": "アリス"})
        for bad in (None, {}, memory("长" * 601), memory(""), memory("摘要", characters=[]),
                    memory("摘要", terms={"term": {"xx": "wrong"}}),
                    memory("摘要", characters={"Alice": {"ja": 5}}),
                    memory("摘要", terms={"term": {"ja": "长" * 81}})):
            with self.subTest(bad=bad):
                self.assertIsNone(llmsrt.merge_story_update(previous, bad, ["ja"]))
        full = memory("摘要", characters={f"Name{i}": {"ja": str(i)} for i in range(32)})
        merged = llmsrt.merge_story_update(full, memory("更新", characters={"New": {"ja": "新"}}), ["ja"])
        self.assertEqual(len(merged["characters"]), 32)
        self.assertNotIn("New", merged["characters"])

    def test_translation_and_memory_transaction_rolls_back_together(self):
        self.cache.connection.execute(
            "CREATE TRIGGER reject_memory BEFORE INSERT ON story_contexts "
            "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.cache.save_batch({"key": "translation"}, "session", 1, memory("摘要"))
        self.assertIsNone(self.cache.get("key"))
        self.assertIsNone(self.cache.get_story("session", 2))

    def test_corrupt_checkpoint_falls_back_to_earlier_valid_memory(self):
        translator = self.translator()
        translator.session_key, translator.targets = "session", ["ja"]
        self.cache.save_batch({}, "session", 1, memory("已知前情。"))
        self.cache.save_batch({}, "session", 2, {"summary": 123})
        translator.restore_story(3)
        self.assertEqual(translator.story_through, 1)
        self.assertEqual(translator.story["summary"], "已知前情。")

    def test_chinese_glossary_uses_same_script_conversion_as_subtitles(self):
        translator = self.translator()
        story = memory("爱丽丝介绍了自己。", characters={"Alice": {"zh-tw": "爱丽丝"}})

        def translate(payload):
            result = response(payload, story)
            decoded = json.loads(result["choices"][0]["message"]["content"])
            decoded["items"][0]["translations"]["zh-tw"] = "爱丽丝"
            result["choices"][0]["message"]["content"] = json.dumps(decoded)
            return result

        progress = llmsrt.ProgressReporter("test", 1, 1, interval=5, enabled=False)
        with patch.object(translator, "request", side_effect=translate):
            output = translator.translate_cues(self.cues[:1], "en", ["zh-tw", "en"], self.context, progress)
        self.assertEqual(output[0]["zh-tw"], "愛麗絲")
        self.assertEqual(translator.story["characters"]["Alice"]["zh-tw"], "愛麗絲")

    def test_private_memory_never_reaches_quip_generator_or_terminal(self):
        translator = self.translator()
        generator = Mock()
        stream = io.StringIO()
        console = Console(file=stream, force_terminal=True, color_system=None,
                          _environ={"TERM": "xterm-256color"})
        progress = llmsrt.ProgressReporter("test.mkv", 1, 1, interval=5, enabled=True,
                                          console=console, quip_generator=generator)
        with progress, patch.object(translator, "request", side_effect=lambda payload: response(
                payload, memory("PRIVATE_STORY_SECRET"))):
            translator.translate_cues(self.cues, "en", ["ja", "en"], self.context, progress)
        self.assertEqual(generator.start.call_count, 2)
        for call, expected in zip(generator.start.call_args_list, (self.cues[:2], self.cues[2:])):
            self.assertEqual(call.args[1], [cue.content for cue in expected])
            self.assertNotIn("PRIVATE_STORY_SECRET", str(call.args[1]))
        self.assertNotIn("PRIVATE_STORY_SECRET", stream.getvalue())

    def test_full_translation_bypasses_both_batch_limits_and_reuses_cache(self):
        self.args.full_translation = True
        self.args.batch_size = self.args.batch_chars = 1
        translator = self.translator()
        payloads = []

        def translate(payload):
            payloads.append(deepcopy(payload))
            return response(payload, memory("完整翻译的摘要。"))

        with patch.object(translator, "request", side_effect=translate) as api:
            output = self.run_translation(translator)
            self.assertEqual(api.call_count, 1)
        self.assertEqual([item["id"] for item in payloads[0]["items"]], [1, 2, 3, 4])
        self.assertEqual(payloads[0]["context_only"], [])
        self.assertEqual(len(output), 4)
        self.args.full_translation, self.args.offline = False, True
        resumed = self.translator()
        with patch.object(resumed, "request", side_effect=AssertionError("cache miss")):
            self.assertEqual(self.run_translation(resumed), output)

    def test_full_translation_includes_cached_edges_as_complete_source_context(self):
        self.args.batch_size = 1
        self.args.context_cues = 0
        original = self.translator()
        with patch.object(original, "request", side_effect=lambda payload: response(payload, memory("已有摘要。"))):
            expected = self.run_translation(original)
        with self.cache.connection:
            for index in (1, 2):
                self.cache.connection.execute("DELETE FROM translations WHERE cache_key = ?",
                                              (original.cache_key(self.cues, index, "en", "ja"),))
        self.args.full_translation = True
        resumed = self.translator()
        payloads = []

        def translate(payload):
            payloads.append(deepcopy(payload))
            return response(payload, memory("补齐后的摘要。"))

        with patch.object(resumed, "request", side_effect=translate) as api:
            self.assertEqual(self.run_translation(resumed), expected)
            self.assertEqual(api.call_count, 1)
        self.assertEqual([item["id"] for item in payloads[0]["items"]], [2, 3])
        self.assertEqual([item["id"] for item in payloads[0]["context_only"]], [1, 4])
        self.assertEqual(payloads[0]["previous_story"]["through_id"], 1)

    def test_full_translation_still_splits_truncated_output(self):
        self.args.full_translation = True
        self.args.batch_size = self.args.batch_chars = 1
        self.args.context_cues = 0
        translator = self.translator()
        payloads = []

        def translate(payload):
            payloads.append(deepcopy(payload))
            return response(payload, memory("已完成部分的摘要。"),
                            finish="length" if len(payload["items"]) > 2 else "stop")

        with patch.object(translator, "request", side_effect=translate), self.assertLogs(llmsrt.LOG, "WARNING"):
            output = self.run_translation(translator)
        self.assertEqual([len(payload["items"]) for payload in payloads], [4, 2, 2])
        self.assertEqual(payloads[2]["previous_story"]["through_id"], 2)
        self.assertEqual([entry["ja"] for entry in output], [f"訳文{i}" for i in range(1, 5)])

    def test_full_translation_config_and_cli_precedence(self):
        self.assertFalse(llmsrt.argument_parser().parse_args([]).full_translation)
        config = Path(self.temporary.name) / "config.json"
        config.write_text(json.dumps({"full_translation": True}))
        for extra, expected in (([], True), (["--no-full-translation"], False)):
            with self.subTest(extra=extra), patch("sys.argv", ["llmsrt", "--config", str(config), *extra]):
                args = llmsrt.configured_arguments(llmsrt.argument_parser())
                self.assertEqual(args.full_translation, expected)
                llmsrt.configure_llm(args)
        self.args.full_translation = "true"
        with self.assertRaisesRegex(llmsrt.LlmsrtError, "full_translation"):
            llmsrt.configure_llm(self.args)


if __name__ == "__main__":
    unittest.main()
