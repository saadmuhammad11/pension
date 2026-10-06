"""The delegation-of-authority register and its lookup. Build specification §8.

Two layers, and the specification is explicit that both are needed (§8.1):

* **the Rule layer** -- Appendix-IV of the Rules (substituted 31.05.1983, item 3 substituted
  19.02.2000) names who may sanction advances by scale and posting: district and regional
  heads for staff up to scale 18 under them, administrative departments for scales 19 and 20.
  That is competence.
* **the register layer** -- the office's own list refines it to named posts and people,
  including who may sign **for** an authority, with specimen signatures. That is identity.

What this module never does
---------------------------
It never decides whether ink matches ink. §8.4: an offline signature-verification model may
add a similarity score as an aid, the score never passes or fails a signature on its own, and
it is never shown without the images. The officer records the decision, and the decision
becomes a fact. §14 rule 6 states the same prohibition.

It never raises a hard stop from a provisional register. §8.3 and §14 rule 7: while the
register is provisional -- which it is, until the office supplies its list under GPF-O14 --
every signature becomes a verification task.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

PROVISIONAL = "provisional"
FINAL = "final"

#: Lookup outcomes, §8.3.
LISTED_WITH_SPECIMEN = "listed_with_specimen"
LISTED_NO_SPECIMEN = "listed_no_specimen"
SIGNATORY_NOT_LISTED = "signatory_not_listed"
AUTHORITY_NOT_LISTED = "authority_not_listed"

#: How the designations actually print on the stamps in these bundles, expanded before
#: matching (§8.3 step 1). "for", "f/o" and "on behalf of" are dropped: they say that
#: somebody signed FOR an authority, which the ``may_sign_for_authority`` flag records, and
#: leaving them in the text made "SP Headquarters for DIG Operations" score against the DIG's
#: own entry instead of the SP's.
_ABBREVIATIONS: tuple[tuple[str, str], ...] = (
    (r"\bs\.?\s?p\b\.?", "superintendent of police"),
    (r"\bd\.?i\.?g\b\.?", "deputy inspector general"),
    (r"\bc\.?e\.?o\b\.?", "chief executive officer"),
    (r"\bd\.?e\.?a\b\.?", "district education authority"),
    (r"\bc\.?t\.?o\b\.?", "chief traffic officer"),
    (r"\bs\.?t\.?o\b\.?", "senior traffic officer"),
    (r"\bd\.?d\.?o\b\.?", "drawing and disbursing officer"),
    (r"\bd\.?a\.?o\b\.?", "district accounts officer"),
    (r"\bx\.?e\.?n\b\.?", "executive engineer"),
    (r"\bs\.?d\.?o\b\.?", "sub divisional officer"),
    (r"\badmn\b\.?", "admin"),
    (r"\bhq\b|\bheadquarters?\b|\bheadquarter\b", "headquarters"),
    (r"\bf\s*/\s*o\b|\bfor\b|\bon behalf of\b", " "),
)

#: Words too short to carry meaning in a designation match.
_MIN_WORD = 3


def normalise(text: Any) -> str:
    """A designation reduced to comparable words. §8.3 step 1."""
    lowered = re.sub(r"[(),.:;]", " ", str(text or "").lower())
    for pattern, replacement in _ABBREVIATIONS:
        lowered = re.sub(pattern, replacement, lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def score(left: Any, right: Any) -> float:
    """How far the shorter designation is contained in the longer. 0.0 to 1.0.

    Asymmetric on purpose: a stamp reads "Chief Traffic Officer, Lahore" and the register
    says "Chief Traffic Officer, Lahore (DDO L04087)", and the stamp should match the
    register entry in full. Dividing by the SHORTER word set does that; dividing by the union
    would penalise the register for being more specific than the rubber stamp.
    """
    left_words = {w for w in normalise(left).split(" ") if len(w) > _MIN_WORD - 1}
    right_words = {w for w in normalise(right).split(" ") if len(w) > _MIN_WORD - 1}
    if not left_words or not right_words:
        return 0.0
    hits = len(left_words & right_words)
    return hits / min(len(left_words), len(right_words))

#: Below this, a designation is not the same designation. Chosen so that every signatory in
#: the corpus matches its own authority and none matches another's; ``tests/test_doa.py``
#: pins that, which is the §17 line "DOA lookup on designation strings seen in the corpus".
MATCH_THRESHOLD = 0.6


@dataclass(frozen=True)
class Signatory:
    """One person or post that may sign. §8.2."""

    id: str
    post: str
    name: str = ""
    may_sign_for_authority: bool = False
    powers: str = ""
    specimen: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass(frozen=True)
class Authority:
    """One authority a document may be issued in the name of. §8.2."""

    id: str
    department: str
    authority: str
    signatories: tuple[Signatory, ...]
    aliases: tuple[str, ...] = ()
    appendix_iv_item: str | None = None
    source: str = ""
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass(frozen=True)
class Match:
    """What the register says about one signature. Never a verdict on the ink. §8.3."""

    status: str
    authority: Authority | None = None
    signatory: Signatory | None = None
    authority_score: float = 0.0
    signatory_score: float = 0.0

    @property
    def has_specimen(self) -> bool:
        return self.status == LISTED_WITH_SPECIMEN

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "authority": self.authority.authority if self.authority else None,
            "authority_id": self.authority.id if self.authority else None,
            "signatory": self.signatory.post if self.signatory else None,
            "signatory_id": self.signatory.id if self.signatory else None,
            "may_sign_for_authority": bool(self.signatory and self.signatory.may_sign_for_authority),
            "specimen": self.signatory.specimen if self.signatory else None,
        }

    def sentence(self) -> str:
        """What the register says, in words an officer can act on."""
        if self.status == AUTHORITY_NOT_LISTED:
            return "The authority is not yet on the DOA register."
        if self.status == SIGNATORY_NOT_LISTED:
            assert self.authority is not None
            return (f"The person who signed is not listed as an approved signatory for "
                    f"{self.authority.authority}.")
        assert self.authority is not None and self.signatory is not None
        if self.signatory.may_sign_for_authority:
            who = (f"{self.signatory.post} is on the register as authorised to sign for "
                   f"{self.authority.authority}.")
        else:
            who = (f"{self.signatory.post} is on the register for {self.authority.authority}, "
                   f"signing in own name.")
        if self.status == LISTED_NO_SPECIMEN:
            return f"{who} No specimen signature is on the register yet."
        return f"{who} Compare the signature with the specimen."


class Register:
    """The office's delegation-of-authority register. §8.2.

    ``status`` is ``provisional`` until the office publishes its list. While provisional the
    register cannot produce a hard stop, and :meth:`raises_hard_stop` is the single place
    that rule lives so no check can forget it.
    """

    def __init__(self, payload: Mapping[str, Any] | None = None) -> None:
        payload = payload or {"status": PROVISIONAL, "authorities": []}
        self.status = str(payload.get("status") or PROVISIONAL)
        self.version = str(payload.get("version") or "")
        self.authorities: tuple[Authority, ...] = tuple(
            Authority(
                id=str(a.get("id") or ""),
                department=str(a.get("dept") or a.get("department") or ""),
                authority=str(a.get("authority") or ""),
                aliases=tuple(a.get("aliases") or ()),
                appendix_iv_item=a.get("appendix_iv_item"),
                source=str(a.get("source") or ""),
                effective_from=a.get("effective_from"),
                effective_to=a.get("effective_to"),
                signatories=tuple(
                    Signatory(
                        id=str(s.get("id") or ""),
                        post=str(s.get("post") or ""),
                        name=str(s.get("name") or ""),
                        # The prototype's key is `mayFor`; the specification's data model
                        # calls it `may_sign_for_authority`. Both are read so the office's
                        # register can arrive in either shape.
                        may_sign_for_authority=bool(
                            s.get("may_sign_for_authority", s.get("mayFor", False))),
                        powers=str(s.get("powers") or ""),
                        specimen=s.get("specimen"),
                        effective_from=s.get("effective_from"),
                        effective_to=s.get("effective_to"),
                    )
                    for s in (a.get("signatories") or ())
                ),
            )
            for a in (payload.get("authorities") or ())
        )

    @property
    def is_provisional(self) -> bool:
        return self.status != FINAL

    def raises_hard_stop(self, match: Match) -> bool:
        """Whether this outcome may stop the case. §8.3, §14 rule 7.

        Only a FINAL register, and only where the person who signed is not on it. An
        authority that is simply not yet listed is a gap in the register, not a defect in the
        department's paperwork, and charging the department for the office's incomplete
        register is exactly what §14 rule 7 forbids.
        """
        return not self.is_provisional and match.status == SIGNATORY_NOT_LISTED

    def lookup(self, authority_text: Any, signatory_text: Any) -> Match:
        """Match the authority, then the person who actually signed. §8.3."""
        best: Authority | None = None
        best_score = 0.0
        for entry in self.authorities:
            candidates = [entry.authority, *entry.aliases]
            entry_score = max(score(authority_text, name) for name in candidates)
            if entry_score > best_score:
                best, best_score = entry, entry_score
        if best is None or best_score < MATCH_THRESHOLD:
            return Match(AUTHORITY_NOT_LISTED, authority_score=best_score)

        signatory: Signatory | None = None
        signatory_score = 0.0
        for person in best.signatories:
            person_score = score(signatory_text, f"{person.post} {person.name}".strip())
            if person_score > signatory_score:
                signatory, signatory_score = person, person_score
        if signatory is None or signatory_score < MATCH_THRESHOLD:
            return Match(SIGNATORY_NOT_LISTED, authority=best,
                         authority_score=best_score, signatory_score=signatory_score)
        return Match(
            LISTED_WITH_SPECIMEN if signatory.specimen else LISTED_NO_SPECIMEN,
            authority=best, signatory=signatory,
            authority_score=best_score, signatory_score=signatory_score,
        )


#: The register the rules consult. Provisional, built from the corpus (§8.5), replaced by the
#: office's own list through :func:`use_register`.
_ACTIVE: Register | None = None


def active_register() -> Register:
    global _ACTIVE
    if _ACTIVE is None:
        from .corpus import provisional_doa
        _ACTIVE = Register(provisional_doa())
    return _ACTIVE


def use_register(register: Register | Mapping[str, Any] | None) -> Register:
    """Install a register. Pass ``None`` to fall back to the provisional corpus one."""
    global _ACTIVE
    _ACTIVE = None if register is None else (
        register if isinstance(register, Register) else Register(register))
    return active_register()
