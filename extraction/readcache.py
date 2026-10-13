"""A per-run cache of confirmed page reads (perf/read-cache, 9 Oct 2026).

The pipeline reads the same page with the vision model more than once: stage 3 identifies it,
stage 4 reads it for the determination figures (a confirming double read), and stage 6 reads it
again for the identifiers it cross-checks (another double read). The 7 Oct baseline
(``docs/PERF-BASELINE.md``) shows one Form D-I page read six times, three AG pay certificates
read three or four times each -- the same page, the same schema, re-sent to a GPU that is already
89-96% busy, which is pure wasted wall time.

This cache holds the result of each confirmed read for the life of one run, keyed on the page's
image BYTES and the schema it was read under. The first request for a (page, schema) does the real
double read; every later request for the same (page, schema) is served from the store. It changes
nothing about WHAT is read:

- The key is the image's content, not its path. Stage 4 hands an upright-corrected image to the
  reader and stage 6 the raw one; where the correction changed the pixels the two have different
  bytes and are cached apart, exactly as if there were no cache. Where the page was already upright
  the bytes match and the second stage reuses the first stage's read.
- The confirming double read (business decision H1, ``extract_page_confirmed``) still happens on
  the first, cached, read: two independent reads that must agree. It is the REPEAT of that work
  that this removes, never the confirmation itself.
- Every hit returns a deep copy. The stages mutate what they get back (they blank disputed fields,
  stamp the document and page onto the agreement), so the stored copy is kept pristine and no
  stage can see another stage's edits.

Without a cache the pipeline runs exactly as before: the stages fall back to calling
``extract_page_confirmed`` directly when no cache is passed.
"""

from __future__ import annotations

import copy
import hashlib
import threading
from pathlib import Path
from typing import Any, Callable

from extraction.client import Extraction, extract_page_confirmed


class ReadCache:
    """Confirmed page reads for one run, keyed on (image bytes, schema, read options)."""

    def __init__(self) -> None:
        self._store: dict[tuple[Any, ...], tuple[Extraction, dict]] = {}
        self._lock = threading.Lock()
        # Counters for the benchmark: how many reads the cache saved. A hit is a double read
        # (and its GPU seconds) that did not happen.
        self.hits = 0
        self.misses = 0

    def confirmed(
        self,
        image: str | Path,
        schema_name: str = "GENERIC_PAGE",
        *,
        reader: Callable[..., tuple[Extraction, dict]] = extract_page_confirmed,
        **kwargs: Any,
    ) -> tuple[Extraction, dict]:
        """Like :func:`extract_page_confirmed`, but returns a stored result on a repeat read.

        ``reader`` is the function that does the real read on a miss; it defaults to the double
        read and is injected only by the tests, which count how often it is called.
        """
        key = self._key(image, schema_name, kwargs)
        with self._lock:
            hit = self._store.get(key)
            if hit is not None:
                self.hits += 1
                ext, agreement = hit
                return copy.deepcopy(ext), copy.deepcopy(agreement)
            self.misses += 1

        # The real read runs OUTSIDE the lock: it is tens of seconds of GPU and must not block
        # the other worker thread's cache look-ups. Stage 6's jobs are de-duplicated by page
        # before they are submitted, so two threads never miss on the same key at once; if some
        # future caller did, the worst case is that one read is done twice -- never a wrong
        # answer, only a saving missed that once.
        ext, agreement = reader(image, schema_name, **kwargs)
        with self._lock:
            self._store.setdefault(key, (copy.deepcopy(ext), copy.deepcopy(agreement)))
        return ext, agreement

    @staticmethod
    def _key(image: str | Path, schema_name: str, kwargs: dict[str, Any]) -> tuple[Any, ...]:
        digest = hashlib.sha256(Path(image).read_bytes()).hexdigest()
        # Options that change the read (an extra instruction, a different token budget) belong in
        # the key; the private retry flag does not change the value and is ignored, as it is by
        # the reader itself.
        opts = tuple(sorted((k, v) for k, v in kwargs.items() if not k.startswith("_")))
        return (digest, schema_name, opts)
