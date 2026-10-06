"""Confirmation of open rule values by an authorised desk. BRAIN §14.1, SOP §4.6, §7.5.

The D-II rules ship PROVISIONAL (``family_pension_dii.yaml``): figures the project's own
documentation gives, that AG Punjab has not confirmed. The engine computes on them and says so
on the face of every determination. This module is how a value stops being provisional --
not by someone editing the yaml, but by the desk the SOP gives the question to recording that
it has been settled, and citing what settled it.

Three properties, matching ``api/decisions.py``:

*   **Append-only.** Every confirmation is one line in ``artifacts/rules/confirmations.jsonl``.
    A value confirmed and later corrected has two entries; the later one is in force and the
    earlier one is still there. FMT-04 wants a figure traceable to its rule years later, and
    that includes who made the rule usable.

*   **A desk, not a person, is authorised.** SOP §7.5 gives a question of interpretation to
    the DAG (Pension), who refers it to the Finance Department; BUILD's RBAC gives rule-pack
    maintenance to the reference-data administrator. Those two desks may confirm. There is no
    authentication in this build, so the desk is self-asserted at sign-in exactly as it is for
    decisions -- recorded as a claim, restricted on the claim, and left for Keycloak to verify.

*   **A confirmation carries its authority.** The notification or FD letter is required text,
    not an optional note. A value confirmed "because that is what the bundles show" is the
    guess this file exists to keep out.

Standard library only; no model, no network.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIRMATIONS_LOG = ROOT / "artifacts" / "rules" / "confirmations.jsonl"

#: The desks that may confirm a rule value, as the portal labels them at sign-in (the label is
#: what identity.ts stores and what a decision entry records). The ids are accepted too, for
#: a caller that has the id and not the label.
AUTHORISED_DESKS: dict[str, str] = {
    "DAG_PENSION": "Deputy Accountant General (Pension)",
    "REFERENCE_ADMIN": "Reference-data administrator",
}

#: The open items a confirmation can address, and the config each lives in. Only the D-II
#: file takes values this way today; the D-I pack's open items (BLOCKING-06, -03) are
#: two-readings ambiguities resolved in the pack itself and are listed for the screen only.
ITEMS: dict[str, dict[str, Any]] = {
    "BLOCKING-07": {
        "title": "Family pension on the death of a pensioner: share, base and commencement",
        "config": "family_pension_dii.yaml",
        "question": (
            "What share of which pension figure does the family take when a pensioner dies, "
            "and from what date? The documents give 75% of 'gross or net pension as "
            "applicable'; the operative Punjab notification is not on file."
        ),
        "resolve_with": (
            "The Punjab Finance Department notification fixing the family-pension rate and "
            "base (FD-SR-III series), or the AG office's written determination practice."
        ),
        # Confirmable keys and, where the value is one of a closed set, the set.
        "keys": {
            "share.widow_percent": {"kind": "percent"},
            "share.regrant_daughter_percent": {"kind": "percent"},
            "share.unmarried_child_percent": {"kind": "percent"},
            "share.parent_percent": {"kind": "percent"},
            "share.disabled_child_percent": {"kind": "percent"},
            "share.sister_percent": {"kind": "percent"},
            "base.definition": {"kind": "choice",
                                "choices": ("pension_in_payment", "net_pension")},
            "commencement.on_death_of_pensioner": {
                "kind": "choice", "choices": ("date_of_death", "day_after_death")},
            "commencement.on_regrant": {
                "kind": "choice",
                "choices": ("death_of_prior_pensioner", "date_of_eligibility",
                            "date_of_application")},
            # Rule 4.10(1) as substituted on 2 December 2024. The term itself is on file;
            # what the desk confirms is the date of death from which it is applied.
            "cessation.spouse_term_years": {"kind": "integer"},
            "cessation.spouse_term_applies_to_deaths_from": {"kind": "date"},
        },
    },
}

#: Long enough to be a citation, short enough not to be a wall.
MIN_AUTHORITY = 10


class ConfirmationError(ValueError):
    """The confirmation was not recordable. Never written to the log."""


class NotAuthorised(ConfirmationError):
    """The desk stated may not confirm a rule value."""


def desk_is_authorised(role: str | None) -> bool:
    text = (role or "").strip().casefold()
    if not text:
        return False
    return any(text in (k.casefold(), v.casefold()) for k, v in AUTHORISED_DESKS.items())


def load_confirmations(path: Path | None = None) -> list[dict]:
    """Every confirmation ever recorded, oldest first. Empty where none has been."""
    p = path or CONFIRMATIONS_LOG
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            # A torn line is left where it is and skipped: the log is evidence, and rewriting
            # it to tidy a torn write would be tampering with evidence.
            continue
    return out


def confirmed_values(path: Path | None = None) -> dict[str, dict]:
    """The confirmation in force for each dotted key: the latest entry wins."""
    in_force: dict[str, dict] = {}
    for entry in load_confirmations(path):
        key = entry.get("key")
        if key:
            in_force[key] = entry
    return in_force


def _validate_value(item: str, key: str, value: str) -> str:
    spec = ITEMS[item]["keys"].get(key)
    if spec is None:
        raise ConfirmationError(
            f"{key!r} is not a value {item} takes; confirmable keys are "
            f"{sorted(ITEMS[item]['keys'])}"
        )
    value = (value or "").strip()
    if not value or value.upper() == "UNSET":
        raise ConfirmationError("a confirmation must carry a value; UNSET is not one")
    if spec["kind"] == "percent":
        try:
            pct = Decimal(value)
        except InvalidOperation:
            raise ConfirmationError(f"{key} must be a percentage, got {value!r}") from None
        if not 0 < pct <= 100:
            raise ConfirmationError(f"{key} must be between 0 and 100, got {value}")
        return str(pct.normalize()) if pct != pct.to_integral() else str(int(pct))
    if spec["kind"] == "choice":
        if value not in spec["choices"]:
            raise ConfirmationError(
                f"{key} must be one of {list(spec['choices'])}, got {value!r}")
        return value
    if spec["kind"] == "integer":
        if not value.isdigit() or int(value) <= 0:
            raise ConfirmationError(f"{key} must be a whole number above zero, got {value!r}")
        return str(int(value))
    if spec["kind"] == "date":
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise ConfirmationError(f"{key} must be a date YYYY-MM-DD, got {value!r}") from None
    return value


def record_confirmation(
    *,
    item: str,
    key: str,
    value: str,
    officer: str,
    role: str,
    authority: str,
    note: str = "",
    path: Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Append one confirmation and return it. Raises rather than recording anything doubtful."""
    if item not in ITEMS:
        raise ConfirmationError(f"unknown item {item!r}; have {sorted(ITEMS)}")
    if not desk_is_authorised(role):
        raise NotAuthorised(
            f"the desk {role!r} may not confirm a rule value. SOP §7.5 gives a question of "
            f"interpretation to the {AUTHORISED_DESKS['DAG_PENSION']}; rule-pack maintenance "
            f"belongs to the {AUTHORISED_DESKS['REFERENCE_ADMIN']}. Sign in at one of those "
            f"desks to record the confirmation."
        )
    officer = (officer or "").strip()
    if not officer:
        raise ConfirmationError("the confirming officer must be named; a confirmation has an author")
    authority = re.sub(r"\s+", " ", (authority or "").strip())
    if len(authority) < MIN_AUTHORITY:
        raise ConfirmationError(
            f"a confirmation must cite its authority -- the notification or FD letter that "
            f"fixes the value -- in at least {MIN_AUTHORITY} characters. A value confirmed "
            f"without one is the guess this log exists to keep out."
        )
    value = _validate_value(item, key, value)
    entry = {
        "item": item,
        "key": key,
        "value": value,
        "officer": officer,
        "role": (role or "").strip(),
        "authority": authority,
        "note": (note or "").strip(),
        "at": (now or datetime.now()).isoformat(timespec="seconds"),
    }
    p = path or CONFIRMATIONS_LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def open_items(path: Path | None = None) -> list[dict]:
    """Every open item, each key with its provisional value and any confirmation in force.

    Read by the portal to show an authorised desk what is still provisional and to take the
    confirmation. The values come from the yaml as shipped; the confirmations overlay them.
    """
    from .dii import UNSET, DIIRules

    rules = DIIRules.load(confirmations=load_confirmations(path))
    in_force = confirmed_values(path)
    out: list[dict] = []
    for item, spec in ITEMS.items():
        keys = []
        for dotted, kspec in spec["keys"].items():
            section, name = dotted.split(".", 1)
            shipped = rules.shipped.get(section, {}).get(name, UNSET)
            keys.append({
                "key": dotted,
                "kind": kspec["kind"],
                "choices": list(kspec.get("choices", ())),
                "provisional_value": None if shipped == UNSET else shipped,
                "value_in_force": rules.values.get(section, {}).get(name),
                "confirmed": dotted in in_force or rules.file_confirmed,
                "confirmation": in_force.get(dotted),
            })
        out.append({
            "item": item,
            "title": spec["title"],
            "question": spec["question"],
            "resolve_with": spec["resolve_with"],
            "config": spec["config"],
            "provisional_source": rules.values.get("provisional_source"),
            "authorised_desks": list(AUTHORISED_DESKS.values()),
            "keys": keys,
        })
    return out
