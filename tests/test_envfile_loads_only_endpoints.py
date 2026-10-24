"""The deployment file supplies model addresses, and nothing else about the process.

The first version of extraction/envfile.py copied every PENSION_*/GPF_* line of
/etc/pension/pension.env into the environment. Importing extraction.client therefore set
PENSION_ENV=production, PENSION_DATABASE_URL and PENSION_JWT_SECRET in any process that
touched an extraction module: 157 tests failed on 20 Oct 2026 with "wrong username or
password", because production mode had come on underneath them and refuses the shared seed
password.

The database setting is the serious one. This box runs its suites as

    env -u PENSION_DATABASE_URL -u GPF_DB python3 -m unittest ...

which is how a test run is kept off the live PostgreSQL. An unset that something puts back is
worse than no unset at all, because the operator has every reason to believe it held.

    python3 -m unittest tests.test_envfile_loads_only_endpoints -v
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from extraction import envfile


class LoadsOnlyEndpoints(unittest.TestCase):
    #: A deployment file with the shape of the real one: endpoints among the posture settings.
    FILE = (
        "PENSION_ENV=production\n"
        "PENSION_DATABASE_URL=postgresql://pension:secret@127.0.0.1:5432/pension\n"
        "PENSION_JWT_SECRET=not-a-real-secret\n"
        "PENSION_SEED_PASSWORD=1234\n"
        "GPF_DB=postgresql://pension:secret@127.0.0.1:5432/pension\n"
        "PENSION_VISION_URL=http://model-host.internal:8000/v1/chat/completions\n"
        "PENSION_OCR_URL=http://model-host.internal:8001/v1/chat/completions\n"
        "PENSION_EMBED_URL=http://model-host.internal:8093/v1/embeddings\n"
        "PENSION_MODEL_API_KEY=not-a-real-key\n"
        "# a comment, and a blank line follow\n"
        "\n"
    )

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "pension.env"
        self.path.write_text(self.FILE)
        # A clean environment, and envfile's "already loaded" latch released, so each test
        # reads the file rather than an earlier test's result.
        self._env = mock.patch.dict(os.environ, {}, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_the_endpoints_are_taken(self) -> None:
        self.assertEqual(envfile.load(self.path), 4)
        self.assertEqual(os.environ["PENSION_VISION_URL"],
                         "http://model-host.internal:8000/v1/chat/completions")
        self.assertEqual(os.environ["PENSION_EMBED_URL"],
                         "http://model-host.internal:8093/v1/embeddings")
        # The key travels with the addresses: without it the servers reset the connection,
        # and endpoints nobody may call are no use to a module run by hand.
        self.assertEqual(os.environ["PENSION_MODEL_API_KEY"], "not-a-real-key")

    def test_nothing_else_in_the_file_is(self) -> None:
        """The posture of the process and the database it talks to are not this module's to set."""
        envfile.load(self.path)
        for name in ("PENSION_ENV", "PENSION_DATABASE_URL", "PENSION_JWT_SECRET",
                     "PENSION_SEED_PASSWORD", "GPF_DB"):
            with self.subTest(setting=name):
                self.assertNotIn(name, os.environ)

    def test_an_unset_database_url_stays_unset(self) -> None:
        """`env -u PENSION_DATABASE_URL` is how a suite is kept off the live database."""
        envfile.load(self.path)
        from api import db
        self.assertIsNone(os.environ.get("PENSION_DATABASE_URL"))
        self.assertIsNone(db.DATABASE_URL)

    def test_the_environment_still_wins(self) -> None:
        os.environ["PENSION_VISION_URL"] = "http://127.0.0.1:8011/v1/chat/completions"
        envfile.load(self.path)
        self.assertEqual(os.environ["PENSION_VISION_URL"],
                         "http://127.0.0.1:8011/v1/chat/completions")

    def test_a_missing_file_is_not_an_error(self) -> None:
        self.assertEqual(envfile.load(self.path.with_name("absent.env")), 0)


class ImportingAnExtractionModuleChangesNothing(unittest.TestCase):
    """The regression as it was actually met: an import, and production mode is on."""

    def test_production_mode_does_not_come_on_underneath_a_caller(self) -> None:
        import subprocess
        import sys
        code = (
            "from api import settings\n"
            "assert not settings.production(), 'production before the import'\n"
            "import extraction.client, extraction.ocr, rag.store\n"
            "import os\n"
            "assert not settings.production(), 'importing an extraction module set PENSION_ENV'\n"
            "assert not os.environ.get('PENSION_DATABASE_URL'), 'it also set the database URL'\n"
        )
        env = {k: v for k, v in os.environ.items()
               if k not in ("PENSION_ENV", "PENSION_DATABASE_URL", "GPF_DB")}
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              cwd=str(Path(__file__).resolve().parents[1]), env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
