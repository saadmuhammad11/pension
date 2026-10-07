"""The golden case fixture. BRAIN §13, from the real 46-page scan (AG diary 41759).

Every figure here is transcribed from BRAIN §13, where it was arithmetically verified. This
module holds *facts read off the documents* -- never derived amounts. The engine computes the
gross pension; this file must not contain 134,421 anywhere, or the test would be checking the
fixture against itself.

Case: Mst. Nargas Waqar, Principal (BS-19), School Education Department. Died in service
29-07-2021. Her widower, Waqar Abdul Basit, is the claimant. The file took 75 days to reach
the Accountant General.
"""

from __future__ import annotations

from datetime import date

from rules import PayComponent

CASE_REF = "AG-41759"
DIARY_NO = "41759"
FORWARDING_DEPARTMENT = "the School Education Department"
FORWARDING_DEPARTMENT_UR = "محکمہ سکول ایجوکیشن"
CLAIMANT_NAME = "Waqar Abdul Basit"
CLAIMANT_CONTACT = "0300-0000001"

# -- §13.2 the deceased servant ------------------------------------------------------------
DATE_OF_BIRTH = date(1966, 2, 19)
DATE_OF_FIRST_ENTRY = date(1993, 12, 8)
DATE_OF_DEATH = date(2021, 7, 29)
#: §13.2 -- pay continued to the family via the OSD post until this date (FAM-IS-01).
NOTIONAL_SUPERANNUATION = date(2026, 2, 18)
BPS = 19
EOL_DAYS = 0
#: The department's own figure. Recorded for comparison; never used in the computation.
STATED_QUALIFYING_SERVICE = "32y 2m 11d"

# -- §13.3 emoluments ----------------------------------------------------------------------
# The reckonable/non-reckonable split is the highest-stakes call in the system: the excluded
# allowances below total 161,765 against reckonable pay of 192,030.
PAY_COMPONENTS = [
    PayComponent("Basic Pay (BS-19, stage 20)", "basic_pay", 178_440, page=15),
    PayComponent("Personal Pay (maximum of grade)", "personal_pay", 13_590, page=15),
    PayComponent("House Rent 45%", "non_reckonable_allowance", 13_284, page=15),
    PayComponent("Medical 15%", "non_reckonable_allowance", 4_963, page=15),
    PayComponent("Special Allowance 2021 25%", "non_reckonable_allowance", 14_803, page=15),
    PayComponent("Ad-hoc Reliefs 2022/23/24/25", "non_reckonable_allowance", 128_715, page=15),
]

#: Form D-I prints "Total Pay 192030". The independent witness the sum is checked against.
PRINTED_TOTAL_PAY = 192_030

#: §13.3 -- stated so the test can assert the exclusion, not so the engine can use it.
EXPECTED_EXCLUDED_TOTAL = 161_765

# -- §13.6 expected determination outputs --------------------------------------------------
EXPECTED_RECKONABLE_TOTAL = 192_030
EXPECTED_QUALIFYING_YEARS_CAPPED = 30
EXPECTED_GROSS_PENSION = 134_421
EXPECTED_FAMILY_PENSION = 100_816          # half-up from 100,815.75 (FMT-01)
EXPECTED_GRATUITY_LITERAL = 33_605
EXPECTED_GRATUITY_CAPITALISED = 4_989_130
EXPECTED_MEDICAL_ON_FAMILY_PENSION = 20_163
EXPECTED_MEDICAL_ON_GROSS_PENSION = 26_884
EXPECTED_COMMENCEMENT = date(2026, 2, 19)

# -- §13.5 the seven flags, plus one ----------------------------------------------------------
# Since 7 Oct 2026 (decision H6) the claimant's relation is checked against the fixed list of
# eligible relations. This fixture's papers state none -- the widower is not among the family
# rows and the fixture carries no FRC applicant -- so an eighth finding, MEDIUM, says so; the two
# LOW findings move down one id. §13.5's seven are unchanged in substance.
EXPECTED_FLAGS = {
    "F-1": ("HIGH", "CONTRA-IDENTITY", True),
    "F-2": ("HIGH", "CONTRA-FAMILY", True),
    "F-3": ("HIGH", "RULE-UNDECLARED", True),
    "F-4": ("MEDIUM", "RULE-CAP", False),
    "F-5": ("MEDIUM", "SLA-BREACH", False),
    "F-6": ("MEDIUM", "RELATIONSHIP-UNPROVED", False),
    "F-7": ("LOW", "ALIAS-RESOLVED", False),
    "F-8": ("LOW", "SCOPE-CONFUSION", False),
}
EXPECTED_BLOCKING_FLAGS = ["F-1", "F-2", "F-3"]

# -- §13.7 verdict -------------------------------------------------------------------------
EXPECTED_VERDICT = "RETURN_FOR_CORRECTION"
EXPECTED_CASE_TYPE = "FAMILY_PENSION_DEATH_IN_SERVICE"
EXPECTED_CHECKLIST_TOTAL = 16

# -- §13.8 assertion 11 --------------------------------------------------------------------
EXPECTED_BLOCKING_ENGAGED = ["BLOCKING-01", "BLOCKING-03", "BLOCKING-06"]


# ==============================================================================================
# The case record the checklist and the check battery run over. BRAIN §13.4, §13.5.
# Facts as each document states them -- never pre-reconciled. F-1 exists only because the file
# cover and Form D-I are recorded here saying something different from the payroll documents.
# ==============================================================================================

from rules import Alias, Assertion, CaseRecord, Document, FamilyMember, Recovery, Source, TimelineEvent  # noqa: E402

_COVER = Source(2, "FILE_COVER")
_D_I = Source(19, "FORM_D_I")
_LPC = Source(6, "LPC")
_SERVICE = Source(9, "SERVICE_STATEMENT")
_BANK = Source(11, "BANK_OPTION_FORM")
_SALARY = Source(15, "SALARY_STATEMENT")
_NDC = Source(35, "NDC")
_ANNEX_A = Source(21, "ANNEX_A")
_FRC = Source(10, "NADRA_FRC")

#: §13.5 F-1. Two documents say ...857; five say ...853. Under §8.3 the payroll chain governs,
#: so the majority here is incidental -- the precedence is what decides it.
PERSONNEL_NO_ASSERTIONS = (
    Assertion("personnel_no", "90000857", _COVER),
    Assertion("personnel_no", "90000857", _D_I),
    Assertion("personnel_no", "90000853", _LPC),
    Assertion("personnel_no", "90000853", _SERVICE),
    Assertion("personnel_no", "90000853", _BANK),
    Assertion("personnel_no", "90000853", _SALARY),
    Assertion("personnel_no", "90000853", _NDC),
)

#: §13.2 -- DOB identical on CNIC, FRC, matric and salary statement. No contradiction: this is
#: here so the battery is exercised on a field that agrees as well as one that does not.
DOB_ASSERTIONS = (
    Assertion("date_of_birth", "1966-02-19", Source(5, "CNIC_DECEASED")),
    Assertion("date_of_birth", "1966-02-19", _FRC),
    Assertion("date_of_birth", "1966-02-19", _SALARY),
    Assertion("date_of_birth", "1966-02-19", Source(16, "MATRIC_CERTIFICATE")),
)

DOCUMENTS = (
    Document("FORM_D_I", (19, 20), signatory="Addl. Secretary (Admn), School Education Dept",
             signatory_is_psa=True, countersigned_by=("DEO(SE)", "DPI")),
    Document("ANNEX_A", (21, 22), attested=True),
    Document("NADRA_DEATH_CERTIFICATE", (17,)),
    Document("SALARY_STATEMENT", (15,)),
    Document("LPC", (6,)),
    Document("CNIC_DECEASED", (5,)),
    Document("CNIC_CLAIMANT", (4,)),
    Document("SERVICE_STATEMENT", (9,)),
    Document("FORWARDING_LETTER", (1,)),
    Document("DEATH_OFFICE_ORDER", (13,)),
    Document("PHOTOGRAPHS", (18,)),
    Document("SPECIMEN_SIGNATURES", (22,)),
    Document("BANK_OPTION_FORM", (11, 12)),
    Document("NON_REMARRIAGE_CERTIFICATE", (23,)),
    Document("NDC", (24, 36)),
    Document("NADRA_FRC", (10,)),
)

#: §13.5 F-2. Annex-A calls Asad a daughter, unmarried. The FRC records a married son.
ANNEX_A_FAMILY = (
    FamilyMember("Mahnoor Waqar", "daughter", "MARRIED", _ANNEX_A, birth_year=1992),
    FamilyMember("Usman Waqar", "Daughter", "UN-MARRIED", _ANNEX_A, birth_year=1994),
    FamilyMember("Mehwish Waqar", "daughter", "UNMARRIED", _ANNEX_A, birth_year=1997),
)
FRC_FAMILY = (
    FamilyMember("Mahnoor Waqar", "daughter", "MARRIED", _FRC, birth_year=1992),
    FamilyMember("Usman Waqar", "son", "MARRIED", _FRC, birth_year=1994),
    FamilyMember("Mehwish Waqar", "daughter", "UNMARRIED", _FRC, birth_year=1997),
)

#: §13.5 F-3 -- the flag §13.8 calls "the one that costs money".
RECOVERIES = (
    Recovery(
        amount=126_355,
        reason="pay disbursed 19-02-2026 to 28-02-2026, ten days beyond notional "
               "superannuation on 18-02-2026",
        source=_LPC,
        declared_on_sanction=False,
    ),
)

#: §13.5 F-5. The 15-day family-pension sanction requirement (BRAIN §4).
TIMELINE = (
    TimelineEvent("ANNEX_A_SIGNED", date(2026, 3, 18), source=_ANNEX_A),
    TimelineEvent("PSA_SANCTION", date(2026, 4, 20), source=_D_I,
                  sla_days=15, sla_from="ANNEX_A_SIGNED"),
    TimelineEvent("FORWARDED_TO_AG", date(2026, 5, 20), source=Source(1, "FORWARDING_LETTER")),
    TimelineEvent("RECEIVED_AT_AG", date(2026, 6, 2), source=Source(1, "FORWARDING_LETTER")),
)

#: §13.5 F-6.
ALIASES = (
    Alias("Nargis Waqar", "spelling_variant",
          resolved_by="name-change order 1995, p.40"),
    Alias("Nargis Kamal", "maiden_name",
          resolved_by="name-change order 1995, p.40; father's name matches Ch. Kamal Ahmad"),
    Alias("Waqar Abdulbasit", "spelling_variant",
          resolved_by="salary statement p.15 against claimant CNIC p.4"),
)

#: §13.5 F-7. NADRA succession certificate, 16-11-2021.
SUCCESSION_CERTIFICATE = Source(36, "SUCCESSION_CERTIFICATE")


def build_case_record(emoluments) -> CaseRecord:
    """Assemble the golden case record. ``emoluments`` comes from ``reckon``."""
    return CaseRecord(
        case_ref=CASE_REF,
        case_type=EXPECTED_CASE_TYPE,
        assertions=PERSONNEL_NO_ASSERTIONS + DOB_ASSERTIONS,
        documents=DOCUMENTS,
        annex_a_family=ANNEX_A_FAMILY,
        frc_family=FRC_FAMILY,
        recoveries=RECOVERIES,
        timeline=TIMELINE,
        aliases=ALIASES,
        emoluments=emoluments,
        stated_qualifying_service_years=32,
        succession_certificate=SUCCESSION_CERTIFICATE,
        diary_no=DIARY_NO,
        forwarding_department=FORWARDING_DEPARTMENT,
        forwarding_department_ur=FORWARDING_DEPARTMENT_UR,
        claimant_name=CLAIMANT_NAME,
        claimant_contact=CLAIMANT_CONTACT,
    )
