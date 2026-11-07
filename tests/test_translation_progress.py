import io
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from rich.console import Console
from rich.text import Text
import srt

import llmsrt


class TranslationProgressTests(unittest.TestCase):
    def test_translation_output_and_cache_in_all_display_modes(self):
        source = list(srt.parse("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n"
                                "2\n00:00:03,000 --> 00:00:04,000\nGoodbye\n"))

        def response(request, **kwargs):
            items = json.loads(request.data)["messages"][1]["content"]
            payload = json.loads(items)
            self.assertEqual(payload["previous_story"]["through_id"], payload["items"][0]["id"] - 1)
            translated = [{"id": item["id"], "translations": {"ja": f"訳文{item['id']}"}}
                          for item in payload["items"]]
            return io.BytesIO(json.dumps({
                "choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps({"items": translated, "story_update": {
                        "summary": "INTERNAL_STORY_ONLY", "characters": {}, "terms": {},
                    }})}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            }).encode())

        root = logging.getLogger()
        original_handlers, original_level = root.handlers[:], root.level
        self.addCleanup(lambda: setattr(root, "handlers", original_handlers))
        self.addCleanup(root.setLevel, original_level)
        for mode in ("terminal", "pipe", "disabled", "local", "quips", "without-sqlite", "temporary-cache"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                video = Path(temporary) / "movie.mkv"
                video.touch()
                destination = Path(temporary) / "translated.srt"
                output = io.StringIO()
                console = Console(file=output, force_terminal=mode in {"terminal", "local", "quips"}, width=100,
                                  _environ={"TERM": "xterm-256color"})
                home = Path(temporary) / "home"
                argv = [str(video), "--source", "en", "--targets", "ja,en", "--no-metadata",
                        "--output", str(destination),
                        "--api-key-env", "LLMSRT_TEST_API_KEY", "--batch-size", "1"]
                cache_dir = Path(temporary)
                if mode == "temporary-cache":
                    cache_dir /= f"llmsrt-{os.getuid()}"
                else:
                    argv.extend(["--cache-dir", temporary])
                if mode == "disabled":
                    argv.append("--no-progress")
                if mode == "local":
                    argv.extend(["--quips", "--no-model-quips"])
                if mode == "quips":
                    argv.append("--quips")
                has_sqlite = mode != "without-sqlite"
                with patch.object(llmsrt, "sqlite3", llmsrt.sqlite3 if has_sqlite else None), \
                        patch("llmsrt.tempfile.gettempdir", return_value=temporary), \
                        patch("llmsrt.Path.home", return_value=home), \
                        patch("rich.console.Console", return_value=console), \
                        patch("llmsrt.shutil.which", return_value="/mock/ffmpeg"), \
                        patch("llmsrt.probe_video", return_value=[]), \
                        patch("llmsrt.acquire_text_subtitles", return_value=llmsrt.SubtitleSource(source, "en", "test")), \
                        patch("urllib.request.OpenerDirector.open", side_effect=response) as api, \
                        patch("llmsrt.ModelQuips", wraps=llmsrt.ModelQuips) as generators, \
                        patch.dict("os.environ", {"LLMSRT_TEST_API_KEY": "test-key"}), \
                        patch("sys.stdout", output):
                    root.handlers = []
                    with patch("llmsrt.configured_arguments", return_value=llmsrt.argument_parser().parse_args(argv)):
                        self.assertEqual(llmsrt.main(), 0)
                    self.assertEqual(api.call_count, 2)
                    self.assertEqual(generators.call_count, 1 if mode == "quips" else 0)
                    result = list(srt.parse(destination.read_text()))
                    self.assertEqual([cue.content for cue in result], ["訳文1\nHello", "訳文2\nGoodbye"])
                    self.assertEqual([(cue.start, cue.end) for cue in result],
                                     [(cue.start, cue.end) for cue in source])
                    text = output.getvalue()
                    plain = Text.from_ansi(text).plain
                    self.assertIn("Completed 1, skipped 0, failed 0", plain)
                    self.assertNotIn("tokens this call", plain)
                    self.assertNotIn("INTERNAL_STORY_ONLY", plain)
                    self.assertNotIn("INTERNAL_STORY_ONLY", destination.read_text())
                    if mode != "disabled":
                        self.assertIn("tokens 200 in / 40 out", plain)
                    if mode not in {"terminal", "local", "quips"}:
                        self.assertNotIn("\x1b", text)
                    database = cache_dir / "translations.sqlite3"
                    self.assertEqual(database.exists(), has_sqlite)
                    root.handlers = []
                    offline_argv = argv + ["--overwrite", "--offline"]
                    with patch("llmsrt.configured_arguments", return_value=llmsrt.argument_parser().parse_args(offline_argv)):
                        self.assertEqual(llmsrt.main(), 0 if has_sqlite else 1)
                    self.assertEqual(api.call_count, 2)  # Offline never calls the model.
                    if not has_sqlite:
                        self.assertIn("the translation cache is unavailable", output.getvalue())
                    if mode == "temporary-cache":
                        self.assertEqual(cache_dir.stat().st_mode & 0o077, 0)
                        legacy_database = home / ".cache" / "llmsrt" / "translations.sqlite3"
                        self.assertFalse(legacy_database.exists())
                        legacy_database.parent.mkdir(parents=True)
                        shutil.copyfile(database, legacy_database)
                        shutil.rmtree(cache_dir)  # Simulate the system cleaning the temporary directory.
                        root.handlers = []
                        with patch("llmsrt.configured_arguments", return_value=llmsrt.argument_parser().parse_args(offline_argv)):
                            self.assertEqual(llmsrt.main(), 1)
                        root.handlers = []
                        legacy_argv = offline_argv + ["--cache-dir", str(legacy_database.parent)]
                        with patch("llmsrt.configured_arguments", return_value=llmsrt.argument_parser().parse_args(legacy_argv)):
                            self.assertEqual(llmsrt.main(), 0)
                        self.assertEqual(api.call_count, 2)
                        self.assertTrue(legacy_database.exists())
                    self.assertEqual(generators.call_count, 1 if mode == "quips" else 0)


if __name__ == "__main__":
    unittest.main()
