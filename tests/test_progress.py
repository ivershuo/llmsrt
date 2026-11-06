import io
import logging
import threading
import unittest
from unittest.mock import patch

from rich.console import Console
from rich.logging import RichHandler

from llmsrt import LOG, QUIP_DELAY, QUIP_INTERVAL, WAITING_QUIPS, ProgressReporter, subtitle_quips


class ProgressTests(unittest.TestCase):
    def reporter(self, *, terminal=False, enabled=True, width=100):
        output = io.StringIO()
        console = Console(file=output, force_terminal=terminal, color_system=None,
                          width=width, _environ={"TERM": "xterm-256color"})
        progress = ProgressReporter("电影[red].mkv", 1, 2, interval=0.01,
                                    enabled=enabled, console=console)
        return progress, output

    def test_live_render_and_logs_preserve_literal_text(self):
        progress, output = self.reporter(terminal=True)
        handler = RichHandler(console=progress.console, show_time=False, show_path=False,
                              markup=False, highlighter=None)
        with patch.object(LOG, "handlers", [handler]), patch.object(LOG, "level", logging.INFO), \
                patch.object(LOG, "propagate", False):
            with progress:
                progress.set_stage("translating subtitles", total=100, completed=20,
                                   detail="waiting for model [blue]")
                progress.update(completed=40)
                progress.record_usage({"prompt_tokens": 1234, "completion_tokens": 56})
                progress.live.refresh()
                LOG.warning("Retrying [yellow] batch")
                self.assertIsNone(progress.thread)
        rendered = output.getvalue()
        for text in ("电影[red].mkv", "40/100 entries (40.0%)", "waiting for model [blue]",
                     "Tokens 1,234 in / 56 out", "Retrying [yellow] batch", "✓", "done"):
            self.assertIn(text, rendered)
        self.assertIn("\x1b[?25h", rendered)  # Cursor is restored after Live stops.
        self.assertEqual(rendered.count("· done"), 1)
        self.assertFalse(progress.live.is_started)

    def test_plain_output_heartbeat_and_summary(self):
        progress, output = self.reporter()
        with self.assertLogs(LOG, logging.INFO) as logs:
            with progress:
                progress.set_stage("translating subtitles", total=10)
                progress.update(completed=4, detail="waiting for model", emit=True)
                heartbeat = threading.Event()
                original_emit = progress.emit

                def emit():
                    original_emit()
                    heartbeat.set()

                with patch.object(progress, "emit", side_effect=emit):
                    self.assertTrue(heartbeat.wait(1))
                progress.record_usage({"prompt_tokens": 10, "completion_tokens": 5})
        text = "\n".join(logs.output)
        self.assertIn("4/10 entries (40.0%)", text)
        self.assertIn("tokens 10 in / 5 out", text)
        self.assertNotIn("\x1b", text)
        self.assertEqual(output.getvalue(), "")
        self.assertFalse(progress.thread.is_alive())

    def test_disabled_progress_stays_silent(self):
        progress, output = self.reporter(terminal=True, enabled=False)
        with patch.object(LOG, "info") as info:
            with progress:
                progress.set_stage("translating subtitles", total=10)
                progress.update(completed=10, emit=True)
            info.assert_not_called()
        self.assertIsNone(progress.live)
        self.assertIsNone(progress.thread)
        self.assertEqual(output.getvalue(), "")

    def test_finish_once_for_skip_failure_and_interrupt(self):
        for status, error in (("skipped", None), ("failed", RuntimeError),
                              ("interrupted", KeyboardInterrupt)):
            with self.subTest(status=status):
                progress, output = self.reporter(terminal=True)
                if error:
                    with self.assertRaises(error):
                        with progress:
                            raise error("test")
                else:
                    with progress:
                        progress.finish("skipped")
                self.assertFalse(progress.live.is_started)
                self.assertTrue(progress.stop.is_set())
                self.assertEqual(output.getvalue().count(f"· {status}"), 1)

    def test_eta_excludes_cache_and_progress_is_bounded(self):
        progress, _ = self.reporter(enabled=False)
        progress.set_stage("translating subtitles", total=100, completed=50)
        self.assertEqual(progress.eta(10), "estimating")
        progress.update(completed=60)
        self.assertEqual(progress.eta(10), "00:00:40")
        progress.update(completed=55)
        self.assertEqual(progress.completed, 60)
        progress.update(completed=110)
        self.assertEqual(progress.completed, 100)
        self.assertEqual(progress.eta(10), "00:00:00")

    def test_zero_total_and_narrow_terminal(self):
        for width in (30, 80):
            with self.subTest(width=width):
                progress, output = self.reporter(terminal=True, width=width)
                with progress:
                    progress.set_stage("reading translation cache", total=0)
                    progress.live.refresh()
                self.assertIn("0/0", output.getvalue())
                self.assertFalse(progress.live.is_started)

    def test_token_usage_accepts_only_nonnegative_integers(self):
        progress, _ = self.reporter(enabled=False)
        for usage in ({"prompt_tokens": 10, "completion_tokens": 5},
                      {"prompt_tokens": 20}, {"prompt_tokens": None, "completion_tokens": "9"},
                      {"prompt_tokens": -1, "completion_tokens": True}):
            progress.record_usage(usage)
        self.assertEqual((progress.input_tokens, progress.output_tokens), (30, 5))

    def test_quips_rotate_after_delay_and_clear_when_wait_ends(self):
        progress, _ = self.reporter()
        with patch("llmsrt.time.monotonic", return_value=100):
            with progress.waiting(["Hello, Morgan. The secret ending is SPOILER_123."]):
                self.assertIsNone(progress.waiting_quip(100 + QUIP_DELAY - 0.1))
                first = progress.waiting_quip(100 + QUIP_DELAY)
                self.assertEqual(first, "一句你好，也有好几种打开方式。")
                self.assertEqual(progress.waiting_quip(100 + QUIP_DELAY + QUIP_INTERVAL - 0.1), first)
                self.assertNotEqual(progress.waiting_quip(100 + QUIP_DELAY + QUIP_INTERVAL), first)
                for second in range(3, 200):
                    quip = progress.waiting_quip(100 + second)
                    self.assertNotIn("Morgan", quip)
                    self.assertNotIn("SPOILER_123", quip)
            self.assertIsNone(progress.waiting_quip(1000))
            with progress.waiting(["Hello again"]):
                self.assertNotEqual(progress.waiting_quip(100 + QUIP_DELAY), first)

    def test_waiting_clears_after_exception_and_interrupt(self):
        for error in (RuntimeError, KeyboardInterrupt):
            with self.subTest(error=error):
                progress, _ = self.reporter()
                with self.assertRaises(error):
                    with progress.waiting(["coffee"]):
                        raise error()
                self.assertIsNone(progress.wait_started)

    def test_quip_themes_are_fixed_and_unknown_text_uses_generic_pool(self):
        self.assertEqual(subtitle_quips(["The ending: SPOILER_123"]), WAITING_QUIPS)
        for text in ("Coffee?", "泡茶", "你好", "thanks", "抱歉"):
            with self.subTest(text=text):
                self.assertGreater(len(subtitle_quips([text])), len(WAITING_QUIPS))
        self.assertEqual(subtitle_quips(["The sheriff arrived"]), WAITING_QUIPS)

    def test_quips_only_appear_in_live_display(self):
        for terminal in (True, False):
            with self.subTest(terminal=terminal):
                progress, output = self.reporter(terminal=terminal)
                with self.assertLogs(LOG, logging.INFO) as logs, progress:
                    progress.set_stage("translating subtitles", total=2)
                    LOG.info("Waiting for the translation request")
                    with progress.waiting(["Coffee?"]):
                        now = progress.wait_started + QUIP_DELAY
                        with patch("llmsrt.time.monotonic", return_value=now):
                            if terminal:
                                progress.live.refresh()
                            else:
                                progress.emit()
                self.assertNotIn("给译文磨豆中", "\n".join(logs.output))
                self.assertEqual("给译文磨豆中" in output.getvalue(), terminal)

    def test_asr_has_generic_quips_and_writing_has_none(self):
        progress, _ = self.reporter()
        with patch("llmsrt.time.monotonic", return_value=100):
            progress.set_stage("transcribing speech", total=60, unit="seconds")
            self.assertEqual(progress.waiting_quip(100 + QUIP_DELAY), WAITING_QUIPS[0])
            progress.set_stage("writing subtitles", total=2)
            self.assertIsNone(progress.waiting_quip(1000))


if __name__ == "__main__":
    unittest.main()
