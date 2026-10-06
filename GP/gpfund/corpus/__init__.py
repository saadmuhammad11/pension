"""The eight corpus cases as facts fixtures. Build specification §16.

"Eight cases, 58 pages, supplied again by the office with longer files." Each JSON file here
is one case's facts object (§4.3) exactly as the reading stage produced it for the prototype,
which is what §16.2 makes the acceptance standard: *a build that does not produce these
results from these facts is not working*.

The files carry no page images and no evidence crops -- only the facts the rules read, plus
the crop FILE NAMES so a result can cite a region that exists under
``GP/agofficegpfund/prototype/evidence/``.

**The corpus is retrospective** (§16.1). Every file carries AG receipt marks and all six
re-calculation reports were run by one SAP user on 10-09-2026, after the office had already
processed the cases. SAP therefore shows the advances and final payments under examination.
Two consequences the rules must honour, and do:

* a limit is tested against the balance BEFORE the posting (§6.5);
* a permanent advance equal to the claim IS the claim, confirmed by its pay order, and never
  a double-payment accusation (§12).

**Data protection** (§16.1). The refundable case's CNIC page carries a stray fragment of
another employee's SAP report. The reading stage quarantines a personnel number that does not
belong to the case and extracts nothing from that region; these fixtures are the output of
that stage and carry no such fragment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts import Facts

HERE = Path(__file__).resolve().parent

#: Presentation order, as the office reads the eight cases.
CORPUS_ORDER: tuple[str, ...] = tuple(json.loads((HERE / "order.json").read_text()))


def corpus_facts(slug: str) -> dict[str, Any]:
    """The raw facts mapping for one corpus case."""
    path = HERE / f"{slug}.json"
    if not path.exists():
        raise KeyError(f"no corpus case {slug!r}; the corpus is {list(CORPUS_ORDER)}")
    return json.loads(path.read_text())


def load_corpus_case(slug: str) -> Facts:
    """One corpus case as a :class:`~gpfund.contracts.Facts`."""
    return Facts(corpus_facts(slug))


def provisional_doa() -> dict[str, Any]:
    """The PROVISIONAL delegation-of-authority register built from the corpus. §8.5.

    Built from the signatories that appear in the eight case files. No specimen exists for
    anyone yet, which is why the register's status is ``provisional`` and why §8.3 and §14
    rule 7 forbid a hard stop from it: every signature becomes a verification task instead.
    Open item GPF-O14.
    """
    return json.loads((HERE / "doa-provisional.json").read_text())
