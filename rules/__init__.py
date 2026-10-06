"""The AG Punjab pension rules engine. BUILD §6.

The most important component in the system, and the one with no AI in it. Pure Python over
versioned, effective-dated rule packs: no model calls, no network, no randomness, no system
clock in the computation. Given the same inputs and the same pack, the output is byte-identical
forever -- which is what lets an auditor recompute a 2026 determination in 2031 with nothing
but this package and the pack id recorded on the case.

    from datetime import date, datetime
    from rules import select_pack, determine_family_pension_death_in_service

    pack = select_pack(effective_date=date(2026, 2, 18))
    det = determine_family_pension_death_in_service(case, pack, computed_at=datetime.now())

    det.amount("CALC-01")        # 134421
    det.provisional              # True - BLOCKING-06 and BLOCKING-03 are engaged
    det.ambiguity("FAM-IS-04")   # two readings, 148.5x apart; no single figure
"""

from .caserecord import (
    Alias,
    Assertion,
    CaseRecord,
    Document,
    FamilyMember,
    PsaSignature,
    Recovery,
    Source,
    TimelineEvent,
)
from .case_type import (
    FAMILY_PENSION_DEATH_AFTER_RETIREMENT,
    FAMILY_PENSION_DEATH_IN_SERVICE,
    CaseTypeResult,
    assign_cnic_roles,
    resolve_parties,
    suggest_variant,
    claimant_from_form,
    dates_from_form,
    death_date_from_form,
    entitlement_date_from_form,
    printed_form_figures,
    pay_scale_from_form,
    classify_case_type,
)
from .checklist import Checklist, ChecklistItem, run_checklist
from .emoluments import Emoluments, PayComponent, reckon
from .engine import DeathInServiceCase, determine_family_pension_death_in_service
from .loader import (
    PackError,
    RulePack,
    UnknownReferenceValue,
    load_all,
    load_pack,
    select_pack,
)
from .flags import Flag, run_battery
from .money import MoneyError, exact, fmt, money, rupees
from .notifications import (
    Notification,
    notify,
    notify_claimant,
    notify_department,
)
from .service import ServiceLength, reckoned_years, span, superannuation_date
from .verdict import Recommendation, recommend
from .types import (
    Ambiguity,
    AmbiguityCollapseError,
    Determination,
    Reading,
    Rule,
    Step,
)

__all__ = [
    "assign_cnic_roles",
    "resolve_parties",
    "suggest_variant",
    "Alias",
    "Ambiguity",
    "AmbiguityCollapseError",
    "Assertion",
    "CaseRecord",
    "CaseTypeResult",
    "Checklist",
    "ChecklistItem",
    "DeathInServiceCase",
    "Determination",
    "Document",
    "Emoluments",
    "FAMILY_PENSION_DEATH_AFTER_RETIREMENT",
    "FAMILY_PENSION_DEATH_IN_SERVICE",
    "FamilyMember",
    "PsaSignature",
    "Flag",
    "MoneyError",
    "Notification",
    "PackError",
    "PayComponent",
    "Reading",
    "Recommendation",
    "Recovery",
    "Rule",
    "RulePack",
    "ServiceLength",
    "Source",
    "Step",
    "TimelineEvent",
    "UnknownReferenceValue",
    "claimant_from_form",
    "dates_from_form",
    "death_date_from_form",
    "entitlement_date_from_form",
    "printed_form_figures",
    "pay_scale_from_form",
    "classify_case_type",
    "determine_family_pension_death_in_service",
    "exact",
    "fmt",
    "load_all",
    "load_pack",
    "money",
    "notify",
    "notify_claimant",
    "notify_department",
    "reckon",
    "reckoned_years",
    "recommend",
    "run_battery",
    "run_checklist",
    "rupees",
    "select_pack",
    "span",
    "superannuation_date",
]
