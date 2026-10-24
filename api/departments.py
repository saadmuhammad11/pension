"""Every department on the system, and which portal each one is. THE configuration file.

One entry per department: its stable code (never changes; cases reference it), the name the
screens print, the slug that is its portal name and its officer's username, the port its portal
listens on, the theme key (see ``api.themes``) and whether it is a Punjab Police unit. Edit here
and nowhere else: the seed, the login rule, the static portal server and the frontend all read
this list (the frontend through ``GET /api/v2/portals`` and the config the portal server injects).

Ports are written out, not computed at import, so adding a department later never shifts the
others: pick the next free number (``next_free_port()``) and append. ``tests/test_departments.py``
recomputes the rule and fails if the written values drift from it.

Decision of 25 Sep 2026: AG Upload is gone. Every department files its own cases from its own
portal; the AG Pension Wing and the administrator sign in at the AG portal on :5184.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Department:
    code: str        # stable id, referenced by cases
    name: str        # as printed on screens
    slug: str        # portal name and the officer's username
    port: int        # the department portal's port
    theme: str       # key into api.themes.THEMES
    is_police: bool  # Punjab Police units share one theme
    #: The AG office's Pension section that works this department's cases (Pension-I .. V), from
    #: PENSION_SECTIONS below; None for the legacy bucket. The AG Review sidebar groups by it.
    pension_section: str | None = None


#: THE portal (decision of 25 Sep 2026, evening): one address, :5184, for everyone -- department
#: officers, the Pension Wing and the administrator all sign in here with their own account, and
#: what they see follows from it. The per-department ports below are kept in the config and can be
#: switched on with PENSION_DEPARTMENT_PORTS=1, but are off by default.
AG_PORTAL_SLUG = "ag"
AG_PORTAL_PORT = 5184
SINGLE_PORTAL = os.environ.get("PENSION_DEPARTMENT_PORTS", "").lower() not in ("1", "true", "yes")

#: Ports never assigned to a department: the AG portal, and ports another service holds on this box.
RESERVED_PORTS = frozenset({5184, 5201})

#: Pinned ports: these two departments had portals before the list grew.
PINNED_PORTS = {"PUNJAB_POLICE": 5180, "SCHOOL_EDUCATION": 5181}
FIRST_FREE_PORT = 5182

DEPARTMENTS: tuple[Department, ...] = (
    Department("AGRICULTURE", "Agriculture Department", "agriculture", 5182, "agriculture", False),
    Department("LIVESTOCK_DAIRY", "Livestock & Dairy Development", "livestock-dairy", 5183, "agriculture", False),
    Department("WILDLIFE_PARKS", "Punjab Wildlife & Parks Department", "wildlife-parks", 5185, "agriculture", False),
    Department("FOREST", "Punjab Forest Department", "forest", 5186, "agriculture", False),
    Department("EXCISE_TAXATION", "Excise & Taxation Department", "excise-taxation", 5187, "finance", False),
    Department("LABOUR_HUMAN_RESOURCE", "Labour & Human Resource Department", "labour-human-resource", 5188, "secretariat", False),
    Department("AQUACULTURE_FISHERIES", "Aquaculture & Fisheries Department", "aquaculture-fisheries", 5189, "agriculture", False),
    Department("SOIL_SURVEY", "Soil Survey of Punjab", "soil-survey", 5190, "agriculture", False),
    Department("BAGH_E_JINNAH", "Bagh-e-Jinnah Lahore", "bagh-e-jinnah", 5191, "agriculture", False),
    Department("PRINTING_PRESS", "Punjab Printing Press", "printing-press", 5192, "infrastructure", False),
    Department("IRRIGATION", "Irrigation Department", "irrigation", 5193, "infrastructure", False),
    Department("C_AND_W", "Communication & Works Department", "c-and-w", 5194, "infrastructure", False),
    Department("ASSEMBLY", "Punjab Assembly", "assembly", 5195, "secretariat", False),
    Department("GOVERNOR_HOUSE", "Governor House", "governor-house", 5196, "secretariat", False),
    Department("CM_INSPECTION", "Chief Minister Inspection Team", "cm-inspection", 5197, "secretariat", False),
    Department("SGAD", "S&GAD", "sgad", 5198, "secretariat", False),
    Department("MPDD", "Management & Professional Development Department", "mpdd", 5199, "secretariat", False),
    Department("BOARD_OF_REVENUE", "Board of Revenue", "board-of-revenue", 5200, "finance", False),
    Department("COOPERATIVES", "Cooperatives Department", "cooperatives", 5202, "finance", False),
    Department("MTO", "Motor Transport Office", "mto", 5203, "infrastructure", False),
    Department("TEVTA", "TEVTA", "tevta", 5204, "secretariat", False),
    Department("CIVIL_DEFENCE", "Civil Defence", "civil-defence", 5205, "secretariat", False),
    Department("PPSC", "Punjab Public Service Commission", "ppsc", 5206, "secretariat", False),
    Department("DG_PROTOCOL", "Director General Protocol", "dg-protocol", 5207, "secretariat", False),
    Department("HIGHER_EDUCATION", "Higher Education Department", "higher-education", 5208, "secretariat", False),
    Department("SCHOOL_EDUCATION", "School Education Department", "school-education", 5181, "education", False),
    Department("PRISONS", "Prisons Department", "prisons", 5209, "justice", False),
    Department("SOCIAL_WELFARE", "Social Welfare Department", "social-welfare", 5210, "secretariat", False),
    Department("SPECIAL_EDUCATION", "Special Education Department", "special-education", 5211, "secretariat", False),
    Department("SPORTS", "Sports Department", "sports", 5212, "secretariat", False),
    Department("DGPR", "DGPR", "dgpr", 5213, "secretariat", False),
    Department("INFORMATION_CULTURE", "Information & Culture Department", "information-culture", 5214, "secretariat", False),
    Department("MAYO_HOSPITAL", "Mayo Hospital", "mayo-hospital", 5215, "hospital", False),
    Department("GANGA_RAM_HOSPITAL", "Sir Ganga Ram Hospital", "ganga-ram-hospital", 5216, "hospital", False),
    Department("PIC", "Punjab Institute of Cardiology", "pic", 5217, "hospital", False),
    Department("JINNAH_HOSPITAL", "Jinnah Hospital", "jinnah-hospital", 5218, "hospital", False),
    Department("DG_HEALTH_SERVICES", "DG Health Services", "dg-health-services", 5219, "health", False),
    Department("SERVICES_HOSPITAL", "Services Hospital", "services-hospital", 5220, "hospital", False),
    Department("CHILDRENS_HOSPITAL", "Children's Hospital", "childrens-hospital", 5221, "hospital", False),
    Department("RESCUE_1122", "Rescue 1122", "rescue-1122", 5222, "rescue", False),
    Department("DG_NURSING", "DG Nursing", "dg-nursing", 5223, "health", False),
    Department("BLOOD_TRANSFUSION", "Institute of Blood Transfusion Services", "blood-transfusion", 5224, "health", False),
    Department("HEALTH_SECRETARIAT", "Health Secretariat", "health-secretariat", 5225, "health", False),
    Department("FINANCE", "Finance Department", "finance", 5226, "finance", False),
    Department("ADVOCATE_GENERAL", "Advocate General Punjab", "advocate-general", 5227, "justice", False),
    Department("DC_LAHORE", "Deputy Commissioner Office Lahore", "dc-lahore", 5228, "secretariat", False),
    Department("INDUSTRIES", "Industries Department", "industries", 5229, "infrastructure", False),
    Department("ACE", "Anti-Corruption Establishment", "ace", 5230, "justice", False),
    Department("LOCAL_GOVERNMENT", "Local Government Department", "local-government", 5231, "infrastructure", False),
    Department("ARCHAEOLOGY", "Archaeology Department", "archaeology", 5232, "secretariat", False),
    Department("BUREAU_STATISTICS", "Bureau of Statistics", "bureau-statistics", 5233, "finance", False),
    Department("FOOD", "Food Department", "food", 5234, "agriculture", False),
    Department("ENVIRONMENT_PROTECTION", "Environment Protection Department", "environment-protection", 5235, "agriculture", False),
    Department("TRANSPORT", "Transport Department", "transport", 5236, "infrastructure", False),
    Department("WAPDA", "Old WAPDA", "wapda", 5237, "infrastructure", False),
    Department("PHE", "Public Health Engineering", "phe", 5238, "infrastructure", False),
    Department("POPULATION_WELFARE", "Population Welfare Department", "population-welfare", 5239, "health", False),
    Department("MINES_MINERALS", "Mines & Minerals Department", "mines-minerals", 5240, "infrastructure", False),
    Department("ZAKAT_USHR", "Zakat & Ushr Department", "zakat-ushr", 5241, "finance", False),
    Department("PLANNING_DEVELOPMENT", "Planning & Development Department", "planning-development", 5242, "finance", False),
    Department("LAHORE_HIGH_COURT", "Lahore High Court", "lahore-high-court", 5243, "justice", False),
    Department("PUNJAB_POLICE", "Punjab Police", "punjab-police", 5180, "police", True),
    Department("CTP_LAHORE", "City Traffic Office", "ctp-lahore", 5244, "police", True),
    Department("CTP_HQ", "City Traffic Office HQ", "ctp-hq", 5245, "police", True),
    Department("POLICE_MT", "Police Motor Transport", "police-mt", 5246, "police", True),
    Department("HIGHWAY_PATROL", "Punjab Highway Patrol", "highway-patrol", 5247, "police", True),
    Department("SPU", "Special Protection Unit", "spu", 5248, "police", True),
    Department("PFSA", "Punjab Forensic Science Agency", "pfsa", 5249, "police", True),
    Department("ELITE_PTS", "Elite Police Training School", "elite-pts", 5250, "police", True),
    Department("BATTALION_01", "Battalion 01", "battalion-01", 5251, "police", True),
    Department("BATTALION_05", "Battalion 05", "battalion-05", 5252, "police", True),
    Department("BATTALION_07", "Battalion 07", "battalion-07", 5253, "police", True),
    Department("DIG_SECURITY", "DIG Security Division", "dig-security", 5254, "police", True),
    Department("RAILWAY_POLICE", "Old Railway", "railway-police", 5255, "police", True),
    Department("CTD", "Counter Terrorism Department", "ctd", 5256, "police", True),
    Department("DIG_OPERATIONS", "DIG Operations", "dig-operations", 5257, "police", True),
    Department("DPO_CPO", "District Police Office / CPO", "dpo-cpo", 5258, "police", True),
    Department("SSP_TELECOM", "SSP Telecommunication", "ssp-telecom", 5259, "police", True),
    Department("IG_AIG", "IG / AIG Offices", "ig-aig", 5260, "police", True),
    Department("RANGERS", "Rangers", "rangers", 5261, "police", True),
    Department("CCPO", "Capital City Police Office", "ccpo", 5262, "police", True),
    Department("POLICE_TRAINING", "Police Training Schools / Colleges", "police-training", 5263, "police", True),
    Department("DIG_INVESTIGATION", "DIG Investigation Lahore", "dig-investigation", 5264, "police", True),
    Department("VIP_SECURITY", "VIP / VVIP / CM Security", "vip-security", 5265, "police", True),
    Department("SPECIAL_BRANCH", "Special Branch", "special-branch", 5266, "police", True),
    Department("SPECIAL_BRANCH_HQ", "Special Branch HQ", "special-branch-hq", 5267, "police", True),
)

#: Which Pension section of the AG office handles each department (29 Sep 2026, as the office
#: gave the list). Keyed by department name exactly as printed above; applied to DEPARTMENTS
#: below, and every department must be listed once -- the module refuses to load otherwise.
PENSION_SECTIONS: dict[str, tuple[str, ...]] = {
    'Pension-I': (
        'Agriculture Department', 'Livestock & Dairy Development',
        'Punjab Wildlife & Parks Department', 'Punjab Forest Department',
        'Excise & Taxation Department', 'Labour & Human Resource Department',
        'Aquaculture & Fisheries Department', 'Soil Survey of Punjab', 'Bagh-e-Jinnah Lahore',
        'Punjab Printing Press',
    ),
    'Pension-II': (
        'Irrigation Department', 'Communication & Works Department', 'Punjab Assembly',
        'Governor House', 'Chief Minister Inspection Team', 'S&GAD',
        'Management & Professional Development Department', 'Board of Revenue',
        'Cooperatives Department', 'Motor Transport Office', 'TEVTA', 'Civil Defence',
        'Punjab Public Service Commission', 'Director General Protocol',
    ),
    'Pension-III': (
        'Higher Education Department', 'School Education Department', 'Prisons Department',
        'Social Welfare Department', 'Special Education Department', 'Sports Department', 'DGPR',
        'Information & Culture Department',
    ),
    'Pension-IV': (
        'Mayo Hospital', 'Sir Ganga Ram Hospital', 'Punjab Institute of Cardiology',
        'Jinnah Hospital', 'DG Health Services', 'Services Hospital', "Children's Hospital",
        'Rescue 1122', 'DG Nursing', 'Institute of Blood Transfusion Services',
        'Health Secretariat', 'Finance Department', 'Advocate General Punjab',
        'Deputy Commissioner Office Lahore', 'Industries Department',
        'Anti-Corruption Establishment', 'Local Government Department', 'Archaeology Department',
        'Bureau of Statistics', 'Food Department', 'Environment Protection Department',
        'Transport Department', 'Old WAPDA', 'Public Health Engineering',
        'Population Welfare Department', 'Mines & Minerals Department', 'Zakat & Ushr Department',
        'Planning & Development Department', 'Lahore High Court',
    ),
    'Pension-V': (
        'Punjab Police', 'City Traffic Office', 'City Traffic Office HQ', 'Police Motor Transport',
        'Punjab Highway Patrol', 'Special Protection Unit', 'Punjab Forensic Science Agency',
        'Elite Police Training School', 'Battalion 01', 'Battalion 05', 'Battalion 07',
        'DIG Security Division', 'Old Railway', 'Counter Terrorism Department', 'DIG Operations',
        'District Police Office / CPO', 'SSP Telecommunication', 'IG / AIG Offices', 'Rangers',
        'Capital City Police Office', 'Police Training Schools / Colleges',
        'DIG Investigation Lahore', 'VIP / VVIP / CM Security', 'Special Branch',
        'Special Branch HQ',
    ),
}

PENSION_SECTION_BY_NAME: dict[str, str] = {n: s for s, ns in PENSION_SECTIONS.items() for n in ns}
PENSION_SECTION_ORDER: tuple[str, ...] = tuple(PENSION_SECTIONS)
_missing = [d.name for d in DEPARTMENTS if d.name not in PENSION_SECTION_BY_NAME]
_unknown = [n for n in PENSION_SECTION_BY_NAME if n not in {d.name for d in DEPARTMENTS}]
if _missing or _unknown or len(PENSION_SECTION_BY_NAME) != sum(len(v) for v in PENSION_SECTIONS.values()):
    raise RuntimeError(f"PENSION_SECTIONS does not match DEPARTMENTS: unlisted {_missing}, unknown {_unknown}")
DEPARTMENTS = tuple(replace(d, pension_section=PENSION_SECTION_BY_NAME[d.name]) for d in DEPARTMENTS)
PENSION_SECTION_OF: dict[str, str | None] = {d.code: d.pension_section for d in DEPARTMENTS}


#: The department of a case that was run on the old single-case portal, before departments and
#: logins existed. Imported once by ``api.legacy``; visible to the AG and the administrator only.
LEGACY_DEPARTMENT = ("LEGACY", "Legacy (pre-departments)", False)

#: Department codes from the earlier 33-entry list that are not on the new one. Kept as inactive
#: rows so cases filed under them still resolve; nobody signs in for them.
RETIRED_CODES: dict[str, str] = {
    "HIGHER_EDUCATION": "Higher Education Department", "HEALTH": "Primary & Secondary Healthcare Department",
    "SPECIALIZED_HEALTHCARE": "Specialized Healthcare & Medical Education Department",
    "IRRIGATION": "Irrigation Department", "AGRICULTURE": "Agriculture Department",
    "LIVESTOCK": "Livestock & Dairy Development Department", "FOREST": "Forestry, Wildlife & Fisheries Department",
    "COMMUNICATION_WORKS": "Communication & Works Department", "LOCAL_GOVERNMENT": "Local Government & Community Development Department",
    "REVENUE": "Board of Revenue", "FINANCE": "Finance Department", "S_AND_GAD": "Services & General Administration Department",
    "HOME": "Home Department", "LAW": "Law & Parliamentary Affairs Department", "EXCISE_TAXATION": "Excise, Taxation & Narcotics Control Department",
    "SOCIAL_WELFARE": "Social Welfare & Bait-ul-Maal Department", "SPECIAL_EDUCATION": "Special Education Department",
    "FOOD": "Food Department", "INDUSTRIES": "Industries, Commerce, Investment & Skills Development Department",
    "LABOUR": "Labour & Human Resource Department", "TRANSPORT": "Transport Department",
    "HOUSING": "Housing, Urban Development & Public Health Engineering Department", "MINES": "Mines & Minerals Department",
    "INFORMATION": "Information & Culture Department", "ZAKAT_USHR": "Zakat & Ushr Department",
    "WOMEN_DEVELOPMENT": "Women Development Department", "ENVIRONMENT": "Environment Protection Department",
    "POPULATION_WELFARE": "Population Welfare Department", "PLANNING_DEVELOPMENT": "Planning & Development Board",
    "ENERGY": "Energy Department", "AUQAF": "Auqaf & Religious Affairs Department",
}

BY_CODE: dict[str, Department] = {d.code: d for d in DEPARTMENTS}
BY_SLUG: dict[str, Department] = {d.slug: d for d in DEPARTMENTS}
BY_PORT: dict[int, Department] = {d.port: d for d in DEPARTMENTS}
DEPARTMENT_NAMES: dict[str, str] = {**{d.code: d.name for d in DEPARTMENTS}, LEGACY_DEPARTMENT[0]: LEGACY_DEPARTMENT[1], **RETIRED_CODES}

#: The roles a user can hold. AG_DAG (7 Oct 2026, decisions C1/G1/G6): the Deputy Accountant General
#: (Pension) -- a reviewer with the senior officer's powers: the case override, and the DAG band in
#: GP Fund, where only the DAG may clear a hard stop.
#: The three tiers of a pension wing (scope change C3, 9 Oct 2026) replaced the single reviewer.
#: AG_REVIEWER is the Accountant General's own desk (decision of 9 Oct 2026, afternoon): bound to
#: no wing and no tier, it acts wherever a case is and overrides like the Deputy AG; the office's
#: senior officers share its one login, ag.reviewer.
TIER_ROLES = ("AG_SENIOR_AUDITOR", "AG_ASSISTANT_AO", "AG_AO")
ROLES = ("DEPT_OFFICER",) + TIER_ROLES + ("AG_DAG", "AG_REVIEWER", "AG_ADDL", "ADMIN")
#: The roles the administrator may create.
CREATABLE_ROLES = ROLES
#: The AG's side of a case: the tiers, the Deputy AG and the AG's desk. The administrator manages users, not cases (G6).
AG_ROLES = TIER_ROLES + ("AG_DAG", "AG_REVIEWER", "AG_ADDL")
ROLE_LABELS = {"DEPT_OFFICER": "DDO", "AG_SENIOR_AUDITOR": "Senior Auditor", "AG_ASSISTANT_AO": "Assistant Accounts Officer",
               # Not "(Pension)": the role is bound to no wing (workflow.ANY_TIER), so the
               # parenthesis said something untrue as well as something long (24 Oct 2026).
               # MIRROR_ROLE_LABELS in api/v2 keeps the longer form: that one is not this
               # label but the deciding desk the rules record, which has its own vocabulary.
               "AG_AO": "Accounts Officer", "AG_DAG": "Deputy Accountant General", "ADMIN": "Administrator",
               # One role for two offices until 24 Oct 2026, so the register could not say
               # which of them had acted. Separated by name, not by power.
               "AG_REVIEWER": "Accountant General", "AG_ADDL": "Additional Accountant General"}


def portal_for(role: str, department_code: str | None) -> str | None:
    """The portal slug this user signs in at, or None where the account cannot sign in anywhere.

    One portal for everyone (SINGLE_PORTAL): the AG portal. A department officer still needs a
    department, or there is nothing to show them.
    """
    if role in AG_ROLES or role == "ADMIN":
        return AG_PORTAL_SLUG
    dept = BY_CODE.get(department_code or "")
    if dept is None:
        return None
    return AG_PORTAL_SLUG if SINGLE_PORTAL else dept.slug


def portal_url(slug: str, host: str) -> str:
    port = AG_PORTAL_PORT if (slug == AG_PORTAL_SLUG or SINGLE_PORTAL) else BY_SLUG[slug].port
    return f"http://{host}:{port}/"


# -- the rules the written values follow (checked by tests) ----------------------------------

_STOP_WORDS = frozenset({"department", "of", "the", "punjab", "office", "&", "and"})

#: Names whose generated slug would be long or ambiguous get a short, readable one.
SLUG_OVERRIDES: dict[str, str] = {
    "City Traffic Office": "ctp-lahore",
    "City Traffic Office HQ": "ctp-hq",
    "Police Motor Transport": "police-mt",
    "Punjab Highway Patrol": "highway-patrol",
    "Special Protection Unit": "spu",
    "Punjab Forensic Science Agency": "pfsa",
    "Elite Police Training School": "elite-pts",
    "DIG Security Division": "dig-security",
    "Counter Terrorism Department": "ctd",
    "DIG Operations": "dig-operations",
    "District Police Office / CPO": "dpo-cpo",
    "SSP Telecommunication": "ssp-telecom",
    "IG / AIG Offices": "ig-aig",
    "Capital City Police Office": "ccpo",
    "Police Training Schools / Colleges": "police-training",
    "DIG Investigation Lahore": "dig-investigation",
    "VIP / VVIP / CM Security": "vip-security",
    "Special Branch": "special-branch",
    "Special Branch HQ": "special-branch-hq",
    "Old Railway": "railway-police",
    "Punjab Police": "punjab-police",
    "School Education Department": "school-education",
    "S&GAD": "sgad",
    "DGPR": "dgpr",
    "TEVTA": "tevta",
    "Old WAPDA": "wapda",
    "Rescue 1122": "rescue-1122",
    "Bagh-e-Jinnah Lahore": "bagh-e-jinnah",
    "Livestock & Dairy Development": "livestock-dairy",
    "Punjab Wildlife & Parks Department": "wildlife-parks",
    "Sir Ganga Ram Hospital": "ganga-ram-hospital",
    "Punjab Institute of Cardiology": "pic",
    "Children's Hospital": "childrens-hospital",
    "Deputy Commissioner Office Lahore": "dc-lahore",
    "Advocate General Punjab": "advocate-general",
    "Chief Minister Inspection Team": "cm-inspection",
    "Director General Protocol": "dg-protocol",
    "Institute of Blood Transfusion Services": "blood-transfusion",
    "Management & Professional Development Department": "mpdd",
    "Punjab Public Service Commission": "ppsc",
    "Anti-Corruption Establishment": "ace",
    "Communication & Works Department": "c-and-w",
    "Public Health Engineering": "phe",
    "Lahore High Court": "lahore-high-court",
    "Board of Revenue": "board-of-revenue",
    "Motor Transport Office": "mto",
}


def slugify(name: str) -> str:
    """Lower-case, drop the generic words, join with '-', at most three words; overrides win."""
    if name in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[name]
    words = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in name.replace("/", " ").split()]
    words = [w for w in words if w and w not in _STOP_WORDS]
    return "-".join(words[:3])


def assign_ports(departments: tuple[Department, ...]) -> dict[str, int]:
    """Pinned first; then sequential from FIRST_FREE_PORT in list order, skipping reserved ports."""
    out = dict(PINNED_PORTS)
    p = FIRST_FREE_PORT
    for d in departments:
        if d.code in out:
            continue
        while p in RESERVED_PORTS or p in out.values():
            p += 1
        out[d.code] = p
        p += 1
    return out


def next_free_port() -> int:
    used = set(BY_PORT) | RESERVED_PORTS
    p = FIRST_FREE_PORT
    while p in used:
        p += 1
    return p


if __name__ == "__main__":
    print(f"{'port':>5}  {'username':<22} theme          department")
    for d in sorted(DEPARTMENTS, key=lambda x: x.name.lower()):
        print(f"{d.port:>5}  {d.slug:<22} {d.theme:<14} {d.name}")
    print(f"{AG_PORTAL_PORT:>5}  {'reviewers / admin':<22} ag             AG Review and Administration")
