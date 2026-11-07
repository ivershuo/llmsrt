from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
import io
import json
import logging
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from rich.console import Console
from rich.live import Live
import srt

import llmsrt


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.output = io.StringIO()
        self.console = Console(file=self.output, force_terminal=True, color_system=None,
                               width=100, height=24, _environ={"TERM": "xterm-256color"})

    def args(self, *extra):
        args = llmsrt.argument_parser().parse_args([
            str(self.directory), "--cache-dir", str(self.directory / "cache"),
            "--source", "en", "--targets", "ja,en", "--no-metadata", *extra])
        llmsrt.configure_llm(args)
        llmsrt.configure_metadata(args)
        llmsrt.configure_media_and_progress(args)
        args.targets = args.targets.split(",")
        return args

    def videos(self, count):
        videos = [self.directory / f"episode{i}.mkv" for i in range(count)]
        for video in videos:
            video.touch()
        return videos

    def test_concurrency_default_config_cli_and_positive_integer_validation(self):
        self.assertEqual(self.args().concurrency, 5)
        self.assertEqual(self.args("-j", "2").concurrency, 2)
        config = self.directory / "config.json"
        config.write_text('{"concurrency": 3}')
        for extra, expected in (([], 3), (["--concurrency", "1"], 1)):
            with patch("sys.argv", ["llmsrt", "--config", str(config), *extra]):
                args = llmsrt.configured_arguments(llmsrt.argument_parser())
                self.assertEqual(args.concurrency, expected)
                llmsrt.configure_llm(args)
        for value in (0, -1, True, 2.5, "5"):
            args.concurrency = value
            with self.subTest(value=value), self.assertRaisesRegex(llmsrt.LlmsrtError, "concurrency"):
                llmsrt.configure_llm(args)

    def test_workers_overlap_respect_limit_and_isolate_sqlite_and_story(self):
        for concurrency in (1, 3, 5):
            with self.subTest(concurrency=concurrency):
                args = self.args("--concurrency", str(concurrency), "--no-progress")
                videos = self.videos(7)
                barrier = threading.Barrier(concurrency)
                lock = threading.Lock()
                active = peak = 0
                translators, connections, owner_threads = [], [], []

                def process(video, destination, args, translator, recognizer, metadata, progress):
                    nonlocal active, peak
                    with lock:
                        active += 1
                        peak = max(peak, active)
                        translators.append(translator)
                        connections.append(translator.cache.connection)
                        owner_threads.append(threading.get_ident())
                        initial = len(translators) <= concurrency
                    try:
                        self.assertEqual(translator.story, llmsrt.empty_story())
                        if initial:
                            barrier.wait(timeout=2)
                        if video == videos[5]:
                            progress.finish("skipped")
                            return False
                        if video == videos[6]:
                            raise llmsrt.LlmsrtError("one video failed")
                        translator.story["summary"] = video.name
                        translator.cache.save_batch({video.name: video.name})
                        self.assertEqual(translator.cache.get(video.name), video.name)
                        return True
                    finally:
                        with lock:
                            active -= 1

                with patch("llmsrt.process_video", side_effect=process), self.assertLogs(llmsrt.LOG, "ERROR"):
                    result = llmsrt.process_videos(videos, self.directory, args, self.console)
                self.assertEqual(result, (5, 1, 1))
                self.assertEqual(peak, concurrency)
                self.assertEqual(len({id(t) for t in translators}), 7)
                self.assertEqual(len({id(c) for c in connections}), 7)
                if concurrency == 1:
                    self.assertEqual(set(owner_threads), {threading.get_ident()})
                else:
                    self.assertNotIn(threading.get_ident(), owner_threads)
                for connection in connections:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        connection.execute("SELECT 1")

    def test_one_live_keeps_five_slots_stable_when_completed_slot_is_reused(self):
        for height in (18, 24):
            with self.subTest(height=height):
                self.console.height = height
                with patch("rich.live.Live", wraps=Live) as lives, ExitStack() as stack:
                    dashboard = stack.enter_context(llmsrt.ProgressDashboard(
                        self.console, 5, enabled=True, quips=False))
                    initial_height = len(self.console.render_lines(dashboard.render()))
                    reporters = []
                    for slot in range(5):
                        reporter = stack.enter_context(llmsrt.ProgressReporter(
                            f"episode{slot}.mkv", slot + 1, 6, interval=5, enabled=True,
                            console=self.console, dashboard=dashboard, slot=slot))
                        reporter.set_stage("translating subtitles", total=100, completed=slot * 10)
                        reporter.begin_response(10)
                        reporter.receive_response(3, 100, 0)
                        reporters.append(reporter)
                    with self.console.capture() as capture:
                        self.console.print(dashboard.render())
                    text = capture.get()
                    for slot in range(5):
                        self.assertIn(f"episode{slot}.mkv", text)
                        self.assertIn(f"{slot * 10 + 3}/100", text)
                        self.assertIs(reporters[slot].live, dashboard.live)
                    self.assertEqual(len(self.console.render_lines(dashboard.render())), initial_height)
                    reporters[0].finish("done")
                    self.assertTrue(dashboard.live.is_started)
                    reporters[1].receive_response(8, 200, 0)
                    replacement = stack.enter_context(llmsrt.ProgressReporter(
                        "episode5.mkv", 6, 6, interval=5, enabled=True,
                        console=self.console, dashboard=dashboard, slot=0))
                    self.assertIs(dashboard.slots[0], replacement)
                    self.assertFalse(reporters[1].finished)
                    self.assertEqual(len(self.console.render_lines(dashboard.render())), initial_height)
                    self.assertEqual(lives.call_count, 1)
                self.assertFalse(dashboard.live.is_started)

    def test_live_only_shows_three_remaining_videos_after_queue_drains(self):
        videos = self.videos(10)
        final_wave = threading.Barrier(5)
        release = threading.Event()
        frames = []
        retire = llmsrt.ProgressDashboard.retire

        def process(video, destination, args, translator, recognizer, metadata, progress):
            progress.set_stage("translating subtitles", total=100, completed=30)
            if video in videos[5:]:
                final_wave.wait(timeout=5)
                if video in videos[7:]:
                    self.assertTrue(release.wait(timeout=5))
            return True

        def record_retirement(dashboard, slot):
            retire(dashboard, slot)
            lines = self.console.render_lines(dashboard.render())
            frames.append("\n".join("".join(segment.text for segment in line) for line in lines))
            if len(frames) == 2:
                release.set()

        with patch("llmsrt.process_video", side_effect=process), \
                patch.object(llmsrt.ProgressDashboard, "retire", record_retirement):
            self.assertEqual(llmsrt.process_videos(videos, self.directory, self.args(), self.console), (10, 0, 0))

        self.assertEqual(len(frames), 5)
        for video in videos[:7]:
            self.assertNotIn(video.name, frames[1])
        for video in videos[7:]:
            self.assertIn(video.name, frames[1])
        self.assertEqual(frames[1].count("30/100 entries"), 3)
        self.assertNotIn("[slot", frames[1])
        self.assertEqual(frames[-1], "")

    def test_real_streaming_pipeline_keeps_each_video_memory_and_resumes_offline(self):
        videos = self.videos(3)
        barrier = threading.Barrier(3)
        root = logging.getLogger()
        previous_handlers, previous_level = root.handlers[:], root.level
        self.addCleanup(lambda: setattr(root, "handlers", previous_handlers))
        self.addCleanup(root.setLevel, previous_level)

        def source(video, *unused):
            return llmsrt.SubtitleSource([
                srt.Subtitle(i, timedelta(seconds=i), timedelta(seconds=i + 1), f"{video.name}: line {i}")
                for i in (1, 2)], "en", "test")

        def respond(request, **unused):
            body = json.loads(request.data)
            self.assertTrue(body["stream"])
            payload = json.loads(body["messages"][1]["content"])
            filename = payload["media_context"]["video_filename"]
            item = payload["items"][0]
            if item["id"] == 1:
                self.assertEqual(payload["previous_story"], {"through_id": 0, **llmsrt.empty_story()})
                barrier.wait(timeout=2)
            else:
                self.assertEqual(payload["previous_story"]["summary"], f"PRIVATE_{filename}")
            content = json.dumps({"items": [{"id": item["id"], "translations": {
                "ja": f"訳文 {filename} {item['id']}"}}], "story_update": {
                "summary": f"PRIVATE_{filename}", "characters": {}, "terms": {}}})
            events = [{"choices": [{"index": 0, "delta": {"content": content[offset:offset + 20]}}]}
                      for offset in range(0, len(content), 20)]
            events += [{"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                       {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}]
            return io.BytesIO(b"".join(("data: " + json.dumps(value) + "\n\n").encode()
                                      for value in events) + b"data: [DONE]\n\n")

        argv = [str(self.directory), "--cache-dir", str(self.directory / "cache"), "--source", "en",
                "--targets", "ja,en", "--no-metadata", "--batch-size", "1", "--api-key-env", "TEST_KEY"]
        with patch("rich.console.Console", return_value=self.console), \
                patch("rich.live.Live", wraps=Live) as lives, \
                patch("llmsrt.shutil.which", return_value="/mock/ffmpeg"), \
                patch("llmsrt.probe_video", return_value=[]), \
                patch("llmsrt.acquire_text_subtitles", side_effect=source), \
                patch("urllib.request.OpenerDirector.open", side_effect=respond) as api, \
                patch.dict("os.environ", {"TEST_KEY": "test-key"}), patch("sys.stdout", self.output), \
                patch("llmsrt.current_umask", wraps=llmsrt.current_umask) as umask:
            root.handlers = []
            with patch("llmsrt.configured_arguments", return_value=llmsrt.argument_parser().parse_args(argv)):
                self.assertEqual(llmsrt.main(), 0)
            self.assertEqual(api.call_count, 6)
            self.assertEqual(lives.call_count, 1)
            self.assertEqual(umask.call_count, 1)
            for video in videos:
                output = list(srt.parse(video.with_name(video.name + ".ja.en.srt").read_text()))
                self.assertEqual([cue.content for cue in output], [
                    f"訳文 {video.name} {i}\n{video.name}: line {i}" for i in (1, 2)])
            self.assertNotIn("PRIVATE_", self.output.getvalue())
            with patch("llmsrt.configured_arguments", return_value=llmsrt.argument_parser().parse_args(
                    argv + ["--overwrite", "--offline"])):
                self.assertEqual(llmsrt.main(), 0)
            self.assertEqual(api.call_count, 6)
        self.assertIn("Completed 3, skipped 0, failed 0", self.output.getvalue())

    def test_interrupt_cancels_active_waits_and_does_not_start_remaining_videos(self):
        videos = self.videos(7)
        ready = threading.Barrier(3)
        started = []
        connections = []
        displays = []

        def display(*args, **kwargs):
            live = Live(*args, **kwargs)
            displays.append(live)
            return live

        def process(video, destination, args, translator, recognizer, metadata, progress):
            started.append(video)
            connections.append(translator.cache.connection)
            ready.wait(timeout=2)
            progress.control.pause(30)
            self.fail("cancelled work resumed")

        def interrupt(*unused, **kwargs):
            ready.wait(timeout=2)
            raise KeyboardInterrupt()

        with patch("llmsrt.process_video", side_effect=process), patch("llmsrt.wait", side_effect=interrupt), \
                patch("rich.live.Live", side_effect=display), \
                self.assertRaises(KeyboardInterrupt):
            llmsrt.process_videos(videos, self.directory, self.args("-j", "2"), self.console)
        self.assertEqual(len(started), 2)
        self.assertTrue(all(not live.is_started for live in displays))
        for connection in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_cancellation_wakes_active_response_and_stops_new_reads(self):
        control = llmsrt.RunControl()
        response = Mock()
        with control.reading(response):
            control.cancel()
            response.fp.raw._sock.shutdown.assert_called_once()
            response.close.assert_called_once()
        self.assertEqual(control.responses, set())
        with self.assertRaises(CancelledError), control.reading(Mock()):
            self.fail("reading after cancellation")

    def test_parallel_pipe_and_disabled_modes_never_create_live_displays(self):
        videos = self.videos(3)
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                console = Console(file=self.output, force_terminal=False)
                args = self.args(*([] if enabled else ["--no-progress"]))

                def process(video, destination, args, translator, recognizer, metadata, progress):
                    progress.set_stage("translating subtitles", total=10)
                    progress.update(completed=10, emit=True)
                    return True

                with patch("llmsrt.process_video", side_effect=process), \
                        patch("rich.live.Live", wraps=Live) as live, patch.object(llmsrt.LOG, "info") as info:
                    self.assertEqual(llmsrt.process_videos(videos, self.directory, args, console), (3, 0, 0))
                live.assert_not_called()
                self.assertEqual(info.called, enabled)
                self.assertNotIn("\x1b", self.output.getvalue())

    def test_request_interval_is_shared_between_independent_translators(self):
        control = llmsrt.RunControl()
        limiter = llmsrt.RequestLimiter(0.5, control)
        args = self.args("--request-interval", "0.5")
        translators = [llmsrt.LLMTranslator(args, Mock(), limiter=limiter, control=control) for _ in range(2)]
        clock = [0.0]
        starts = []

        def pause(seconds):
            clock[0] += seconds

        def respond(*unused, **kwargs):
            starts.append(clock[0])
            return io.BytesIO(b'{"choices": []}')

        with patch("llmsrt.time.monotonic", side_effect=lambda: clock[0]), \
                patch.object(control, "pause", side_effect=pause), \
                patch("urllib.request.OpenerDirector.open", side_effect=respond), \
                patch.dict("os.environ", {args.api_key_env: "test-key"}):
            for translator in (translators[0], translators[1], translators[0]):
                translator.request({"items": [{"id": 1, "targets": ["ja"]}]})
        self.assertEqual(starts, [0.0, 0.5, 1.0])

    def test_concurrent_metadata_reuses_failed_searches_and_asr_is_serialized(self):
        args = self.args("--metadata")
        resolver = llmsrt.MetadataResolver(self.directory, timeout=15, cache_days=30,
                                           offline=False, refresh=False)

        def enrich(index):
            progress = llmsrt.ProgressReporter("test", 1, 1, interval=5, enabled=False)
            context = llmsrt.media_context_for(Path(f"Star.Trek.The.Next.Generation.S02E{index:02}.mkv"), args)
            return resolver.enrich(context, args, progress)

        with patch.object(resolver, "search", return_value=[]) as search, \
                self.assertLogs(llmsrt.LOG, "WARNING"), ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(enrich, range(1, 4)))
        self.assertEqual(search.call_count, 2)  # One failure per source across episodes.
        recognizer = llmsrt.SpeechRecognizer(args)
        gate = threading.Barrier(3)

        def transcribe(index):
            progress = llmsrt.ProgressReporter("test", 1, 1, interval=5, enabled=False)
            gate.wait(timeout=2)
            return recognizer.transcribe(Path("test"), [], self.directory, progress)

        def inference(*unused):
            self.assertFalse(entered.is_set())
            entered.set()
            time.sleep(0.01)
            entered.clear()
            return "subtitles"

        entered = threading.Event()
        with patch.object(recognizer, "_transcribe", side_effect=inference), \
                ThreadPoolExecutor(max_workers=3) as executor:
            self.assertEqual(list(executor.map(transcribe, range(3))), ["subtitles"] * 3)


if __name__ == "__main__":
    unittest.main()
