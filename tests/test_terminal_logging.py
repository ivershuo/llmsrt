import io
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from rich.console import Console

import llmsrt
from media_metadata import MetadataResolver


class TerminalLoggingTests(unittest.TestCase):
    def console(self, width=80):
        stream = io.StringIO()
        console = Console(file=stream, force_terminal=True, color_system="truecolor", width=width,
                          record=True, _environ={"TERM": "xterm-256color"})
        return console, stream

    def test_compact_notices_are_single_lines_without_padding_or_number_highlights(self):
        console, stream = self.console(width=60)
        logger = logging.Logger("test", logging.INFO)
        logger.addHandler(llmsrt.TerminalLogHandler(console))
        logger.info("Source [red] 7.1 (subrip), 699 subtitles")
        logger.warning("metadata unavailable:\n\t" + "long reason " * 20)
        lines = console.export_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "· Source [red] 7.1 (subrip), 699 subtitles")
        self.assertTrue(lines[1].startswith("! metadata unavailable:"))
        self.assertTrue(lines[1].endswith("…"))
        self.assertTrue(all(len(line) <= 60 and line == line.rstrip() for line in lines))
        self.assertNotIn("\x1b[1", stream.getvalue())
        self.assertNotIn("WARNING", stream.getvalue())

    def test_verbose_keeps_full_warning_and_traceback(self):
        console, _ = self.console(width=50)
        logger = logging.Logger("test", logging.DEBUG)
        logger.addHandler(llmsrt.TerminalLogHandler(console, verbose=True))
        logger.warning("Full metadata diagnostic including title and exact IDs.",
                       extra={"display_message": "Short notice"})
        try:
            raise RuntimeError("details are preserved")
        except RuntimeError:
            logger.exception("Model request failed")
        text = console.export_text()
        self.assertIn("WARNING Full metadata diagnostic", text)
        self.assertIn("exact IDs.", text)
        self.assertNotIn("Short notice", text)
        self.assertIn("Traceback", text)
        self.assertIn("details are preserved", text)

    def test_errors_keep_full_diagnostics_even_without_verbose(self):
        console, _ = self.console(width=50)
        logger = logging.Logger("test", logging.INFO)
        logger.addHandler(llmsrt.TerminalLogHandler(console))
        logger.error("An important error with enough detail to wrap; FINAL_REASON",
                     extra={"display_message": "Short notice"})
        text = console.export_text()
        self.assertIn("FINAL_REASON", text)
        self.assertNotIn("Short notice", text)
        self.assertNotIn("…", text)

    def test_metadata_misses_are_brief_in_terminal_and_complete_in_pipes(self):
        filename = ("Star.Trek.The.Next.Generation.S02E17.Samaritan.Snare.1080p.BluRay."
                    "REMUX.AVC.DTS-HD.MA.7.1-NOGRP.mkv")
        args = llmsrt.argument_parser().parse_args([])
        llmsrt.configure_metadata(args)
        for mode in ("terminal", "verbose", "pipe"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                console, stream = self.console(width=120)
                if mode == "pipe":
                    handler = logging.StreamHandler(stream)
                else:
                    handler = llmsrt.TerminalLogHandler(console, verbose=mode == "verbose")
                resolver = MetadataResolver(Path(directory), timeout=15, cache_days=30,
                                            offline=False, refresh=False)
                with patch.object(llmsrt.LOG, "handlers", [handler]), \
                        patch.object(llmsrt.LOG, "level", logging.INFO), \
                        patch.object(llmsrt.LOG, "propagate", False), \
                        patch.object(resolver, "search", return_value=[]):
                    resolver.enrich(llmsrt.media_context_for(Path(filename), args), args, Mock())
                if mode == "terminal":
                    text = console.export_text()
                    self.assertEqual(len(text.splitlines()), 2)
                    self.assertIn("! IMDb: no unique match; add --imdb", text)
                    self.assertIn("! Douban: no unique match; add --douban", text)
                    self.assertNotIn("continuing with other sources", text)
                else:
                    text = stream.getvalue()
                    if mode == "verbose":
                        text = console.export_text()
                    self.assertIn("No unique match for 'Star Trek The Next Generation'", text)
                    self.assertIn("manual background", text)


if __name__ == "__main__":
    unittest.main()
