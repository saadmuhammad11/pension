"""How a confirmed upload changes the facts. Build specification §7.

R2: every issue must accept a document and be re-checked. The flow (§7.1) is

    upload -> store with SHA-256 -> read (stages 1 to 5 on that file) -> confirm the fields
    -> MERGE into the case facts -> re-evaluate the whole case -> new version

and this module is only the merge step. It contains no judgement: each function writes what
the officer confirmed into the facts, and the rules then decide. That is what §0 means by
"the same rule that raised an observation closes it" -- nothing here marks anything resolved.

Why the mapping is by name
--------------------------
A result's ``cure`` descriptor names its ``apply`` mapping, so the rule that raised the item
chooses how a document cures it. The officer cannot pick the wrong merge, and a check that
offers a cure it has no mapping for fails loudly at registration time
(:func:`missing_mappings`) rather than at the desk.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping

from .engine import num


def _yes(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("yes", "true", "1")


def _uploaded(file_name: str) -> str:
    """The page reference for a fact that came from an upload rather than a case page.

    A string, not a number: §4.4 keeps evidence honest about where it can be seen, and an
    upload has no page in the original bundle.
    """
    return f"upload: {file_name}"


# Each mapping takes (facts_dict, confirmed_values, file_name) and mutates the facts.
CureFn = Callable[[MutableMapping[str, Any], Mapping[str, Any], str], None]


def _add_sanction(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    sanction = dict(facts.setdefault("docs", {}).get("sanction") or {})
    sanction.update({"present": True, "page": _uploaded(file), "orderNo": values.get("orderNo"),
                     "date": values.get("date"), "amount": num(values.get("amount")),
                     "rule": values.get("rule")})
    facts["docs"]["sanction"] = sanction


def _set_sanction_rule(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    sanction = facts.setdefault("docs", {}).setdefault("sanction", {})
    if values.get("rule"):
        sanction["rule"] = values["rule"]
    if values.get("reason"):
        sanction["reason"] = values["reason"]


def _sanction_qr(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    codes = [c for c in (facts.get("qr") or []) if c.get("id") != "sanction-upload"]
    codes.append({
        "id": "sanction-upload", "page": _uploaded(file),
        "doc": "uploaded QR-coded sanction", "symbology": "QR code", "decoded": True,
        "payload": values.get("payload"),
        "compare": [{"field": "Content", "qrVal": values.get("payload") or "(not entered)",
                     "docVal": "the printed sanction", "docLabel": "sanction",
                     "match": _yes(values.get("agrees"))}],
    })
    facts["qr"] = codes
    facts.setdefault("docs", {}).setdefault("sanction", {})["qrId"] = "sanction-upload"


def _add_cnic(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    cards = list(facts.setdefault("docs", {}).get("cnics") or [])
    cards.append({"page": _uploaded(file), "whose": values.get("whose") or "subscriber",
                  "type": values.get("type") or "smart", "number": values.get("number"),
                  # An uploaded copy is not attested unless the officer says so. R5 makes
                  # that an observation, not a defect, so recording it truthfully costs
                  # nothing and asserting it falsely would hide a real gap.
                  "attested": _yes(values.get("attested"))})
    facts["docs"]["cnics"] = cards


def _add_form(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    label = "FORM PAY 05" if facts.get("kind") == "refundable" else "FORM PAY 06"
    form = dict(facts.setdefault("docs", {}).get("changeForm") or {})
    form.update({"present": True, "label": label, "page": _uploaded(file),
                 "personalNo": values.get("personalNo"),
                 "sigKind": "signature" if _yes(values.get("signed")) else "none",
                 "ddoSigned": _yes(values.get("ddoSigned"))})
    facts["docs"]["changeForm"] = form


def _ddo_signed(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    facts["docs"]["changeForm"]["ddoSigned"] = _yes(values.get("ddoSigned"))


def _form_signed(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    facts["docs"]["changeForm"]["sigKind"] = "signature" if _yes(values.get("signed")) else "none"


def _form_signatures(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    form = facts["docs"]["changeForm"]
    if _yes(values.get("ddoSigned")):
        form["ddoSigned"] = True
    # A thumb impression already on the form is NOT overwritten with "signature": R7 is
    # tracking whose thumb it is, and losing that would drop a verification task.
    if _yes(values.get("signed")) and form.get("sigKind") in (None, "", "none"):
        form["sigKind"] = "signature"


def _set_form_persno(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    facts["docs"]["changeForm"]["personalNo"] = values.get("personalNo")


def _set_form_cnic(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    facts["docs"]["changeForm"]["cnic"] = values.get("cnic")


def _add_gpf10(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    missing: list[str] = []
    if not _yes(values.get("signed")):
        missing.append("signature of subscriber or claimant")
    if not _yes(values.get("ddoSigned")):
        missing.append("signature of DDO")
    if not values.get("accountNo"):
        missing.append("GP Fund account no.")
    facts.setdefault("docs", {})["gpf10"] = {
        "present": True, "page": _uploaded(file), "accountNo": values.get("accountNo"),
        "missing": missing}


def _gpf10_complete(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    form = facts["docs"]["gpf10"]
    form["missing"] = [item for index, item in enumerate(form.get("missing") or [])
                       if not _yes(values.get(f"m{index}"))]


def _add_notification(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    facts.setdefault("docs", {})["notification"] = {
        "present": True, "page": _uploaded(file), "no": values.get("no"),
        "date": values.get("date"), "label": "Notification"}


def _set_oldac(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    facts["docs"]["changeForm"]["oldGpfNo"] = values.get("oldGpfNo")


def _add_servicebook(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    facts.setdefault("docs", {})["serviceBook"] = {
        "present": True, "pages": [_uploaded(file)],
        "entries": {"dor": _yes(values.get("dor")), "order": _yes(values.get("order")),
                    "leave": _yes(values.get("leave"))},
        "note": "uploaded pages"}


def _add_heir_cnic(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    for heir in (facts.get("docs", {}).get("death", {}).get("heirs") or []):
        if heir.get("name") == values.get("name"):
            heir["cnicCopy"] = True
            if values.get("number"):
                heir["cnic"] = values["number"]


def _add_affidavit(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    facts["docs"]["death"]["affidavit"] = {
        "present": True, "original": _yes(values.get("original")), "page": _uploaded(file),
        "label": "Affidavit for lawful widow"}


def _add_succession(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    if _yes(values.get("granted")):
        facts["docs"]["death"]["successionCert"] = "granted"
        facts["docs"]["death"]["successionPage"] = _uploaded(file)


def _set_period(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    facts["docs"]["challans"]["period"] = values.get("period")


def _challan_stamp(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    for copy in (facts["docs"]["challans"].get("copies") or []):
        if str(copy.get("page")) == str(values.get("page")) and _yes(values.get("bankStamp")):
            copy["bankStamp"] = True


def _challan_stamp_clear(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    for copy in (facts["docs"]["challans"].get("copies") or []):
        if str(copy.get("page")) == str(values.get("page")) and _yes(values.get("legible")):
            copy["stampFaint"] = False


def _to_verified(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    facts["docs"]["challans"]["toVerified"] = _yes(values.get("toVerified"))


def _add_challan(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    copies = facts["docs"]["challans"].setdefault("copies", [])
    copies.append({"page": _uploaded(file), "sr": values.get("sr"),
                   "amount": num(values.get("amount")),
                   "bankStamp": _yes(values.get("bankStamp"))})


def _proforma(facts: MutableMapping[str, Any], values: Mapping[str, Any], file: str) -> None:
    proforma = facts["docs"]["proforma"]
    for key in ("oldAc", "newAc", "lastDeduction"):
        if values.get(key):
            proforma[key] = values[key]


CURES: dict[str, CureFn] = {
    "add-sanction": _add_sanction,
    "set-sanction-rule": _set_sanction_rule,
    "sanction-qr": _sanction_qr,
    "add-cnic": _add_cnic,
    "add-form": _add_form,
    "ddo-signed": _ddo_signed,
    "form-signed": _form_signed,
    "form-signatures": _form_signatures,
    "set-form-persno": _set_form_persno,
    "set-form-cnic": _set_form_cnic,
    "add-gpf10": _add_gpf10,
    "gpf10-complete": _gpf10_complete,
    "add-notification": _add_notification,
    "set-oldac": _set_oldac,
    "add-servicebook": _add_servicebook,
    "add-heir-cnic": _add_heir_cnic,
    "add-affidavit": _add_affidavit,
    "add-succession": _add_succession,
    "set-period": _set_period,
    "challan-stamp": _challan_stamp,
    "challan-stamp-clear": _challan_stamp_clear,
    "to-verified": _to_verified,
    "add-challan": _add_challan,
    "proforma": _proforma,
}


def apply_cure(facts_dict: MutableMapping[str, Any], apply: str,
               values: Mapping[str, Any], file_name: str) -> None:
    """Merge one confirmed upload into the facts. §7.1 step 5."""
    if apply not in CURES:
        raise KeyError(
            f"no cure mapping named {apply!r}. A check offered a cure this build cannot apply; "
            f"the known mappings are {sorted(CURES)}.")
    CURES[apply](facts_dict, values, file_name)


def missing_mappings() -> tuple[str, ...]:
    """Cure names the rules offer that this module cannot apply.

    Checked by the test suite over every corpus case and every no-SAP variant, so a check
    that offers a cure with no mapping is caught in the harness rather than at a desk with a
    case open (§17).
    """
    from .contracts import Facts
    from .corpus import CORPUS_ORDER, corpus_facts
    from .engine import evaluate

    wanted: set[str] = set()
    for slug in CORPUS_ORDER:
        base = Facts(corpus_facts(slug))
        for facts in (base, base.without_sap()):
            for result in evaluate(facts):
                cure = result.cure or {}
                if cure.get("kind") == "doc" and cure.get("apply"):
                    wanted.add(str(cure["apply"]))
    return tuple(sorted(wanted - set(CURES)))
