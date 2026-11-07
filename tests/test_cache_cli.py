from contextlib import closing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import llmsrt


class CacheCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "config.json"
        self.config.write_text("{}")
        self.cache_dir = self.root / "cache"

    def clear_cache(self, *, use_default=False):
        argv = ["llmsrt", "--config", str(self.config), "--clear-cache"]
        if not use_default:
            argv.extend(["--cache-dir", str(self.cache_dir)])
        with patch.object(sys, "argv", argv), \
                patch("llmsrt.logging.basicConfig"), \
                patch("llmsrt.dependency", side_effect=AssertionError("unexpected dependency")), \
                patch("llmsrt.shutil.which", side_effect=AssertionError("unexpected FFmpeg check")):
            return llmsrt.main()

    def test_help_starts_without_the_sqlite_extension(self):
        script = """
import runpy
import sys

sys.modules['_sqlite3'] = None
script, config = sys.argv[1:]
sys.argv = [script, '--config', config, '--help']
runpy.run_path(script, run_name='__main__')
"""
        project = Path(llmsrt.__file__).parent
        result = subprocess.run([sys.executable, "-c", script, llmsrt.__file__, str(self.config)],
                                cwd=project, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--clear-cache", result.stdout)

    def test_clear_cache_reclaims_disk_and_preserves_unrelated_files(self):
        database = self.cache_dir / "translations.sqlite3"
        with closing(llmsrt.TranslationCache(database)) as cache:
            cache.save_batch({"translated": "x" * 200_000})
            with cache.connection:
                cache.connection.execute("CREATE TABLE story_contexts (context TEXT)")
                cache.connection.execute("INSERT INTO story_contexts VALUES ('old story')")
            original_size = database.stat().st_size
            media = self.cache_dir / "media"
            media.mkdir()
            record = media / ("a" * 64 + ".json")
            record.write_text("{}")
            other = media / "notes.json"
            other.write_text('{"keep": true}')
            subtitle = self.cache_dir / "movie.srt"
            subtitle.write_text("Subtitle output")

            with self.assertLogs(llmsrt.LOG, "INFO"):
                self.assertEqual(self.clear_cache(), 0)

            self.assertLess(database.stat().st_size, original_size)
            self.assertIsNone(cache.get("translated"))
            self.assertEqual(cache.connection.execute("SELECT * FROM story_contexts").fetchall(), [])
            self.assertFalse(record.exists())
            self.assertEqual(other.read_text(), '{"keep": true}')
            self.assertEqual(subtitle.read_text(), "Subtitle output")

    def test_default_clear_covers_temporary_and_legacy_caches(self):
        home = self.root / "home"
        legacy = home / ".cache" / "llmsrt"
        with patch("llmsrt.tempfile.gettempdir", return_value=str(self.root)), \
                patch("llmsrt.Path.home", return_value=home):
            temporary = llmsrt.temporary_translation_cache_directory(create=True)
            databases = [directory / "translations.sqlite3" for directory in (temporary, legacy, self.cache_dir)]
            for database in databases:
                with closing(llmsrt.TranslationCache(database)) as cache:
                    cache.put("cue", "translation")
            media = legacy / "media"
            media.mkdir()
            record = media / ("a" * 64 + ".json")
            record.write_text("{}")

            with self.assertLogs(llmsrt.LOG, "INFO"):
                self.assertEqual(self.clear_cache(use_default=True), 0)

        for database in databases[:2]:
            with closing(llmsrt.TranslationCache(database)) as cache:
                self.assertIsNone(cache.get("cue"))
        with closing(llmsrt.TranslationCache(databases[2])) as cache:
            self.assertEqual(cache.get("cue"), "translation")
        self.assertFalse(record.exists())

    def test_clear_media_cache_without_sqlite_reports_an_existing_database(self):
        media = self.cache_dir / "media"
        media.mkdir(parents=True)
        record = media / ("b" * 64 + ".json")
        record.write_text("{}")
        database = self.cache_dir / "translations.sqlite3"

        with patch.object(llmsrt, "sqlite3", None):
            with self.assertLogs(llmsrt.LOG, "INFO"):
                self.assertEqual(self.clear_cache(), 0)
            self.assertFalse(record.exists())
            self.assertFalse(database.exists())

            record.write_text("{}")
            database.write_bytes(b"previous cache")
            with self.assertLogs(llmsrt.LOG, "ERROR") as logs:
                self.assertEqual(self.clear_cache(), 1)
            self.assertIn("SQLite is required", logs.output[0])
            self.assertFalse(record.exists())
            self.assertEqual(database.read_bytes(), b"previous cache")
