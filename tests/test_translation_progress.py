import io
import json
import logging
from pathlib import Path
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
        for mode in ("terminal", "pipe", "disabled", "local"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                video = Path(temporary) / "movie.mkv"
                video.touch()
                destination = Path(temporary) / "translated.srt"
                output = io.StringIO()
                console = Console(file=output, force_terminal=mode in {"terminal", "local"}, width=100,
                                  _environ={"TERM": "xterm-256color"})
                argv = [str(video), "--source", "en", "--targets", "ja,en", "--no-metadata",
                        "--output", str(destination), "--cache-dir", temporary,
                        "--api-key-env", "LLMSRT_TEST_API_KEY", "--batch-size", "1"]
                if mode == "disabled":
                    argv.append("--no-progress")
                if mode == "local":
                    argv.append("--no-model-quips")
                with patch("rich.console.Console", return_value=console), \
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
                    self.assertEqual(generators.call_count, 1 if mode == "terminal" else 0)
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
                    if mode not in {"terminal", "local"}:
                        self.assertNotIn("\x1b", text)
                    root.handlers = []
                    with patch("llmsrt.configured_arguments", return_value=llmsrt.argument_parser().parse_args(
                            argv + ["--overwrite", "--offline"])):
                        self.assertEqual(llmsrt.main(), 0)
                    self.assertEqual(api.call_count, 2)  # Second run uses only the translation cache.
                    self.assertEqual(generators.call_count, 1 if mode == "terminal" else 0)


if __name__ == "__main__":
    unittest.main()
