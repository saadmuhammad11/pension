"""The colour palettes the department portals wear. Edit hex codes here and nowhere else.

Each palette fills the same slots the frontend's ``Theme`` type expects (``portals/src/shared/
theme/types.ts``): a dark primary for the header and buttons, two lighter steps, two tints for
backgrounds, an accent pair, and the text/line/page greys. A department names a palette in
``api.departments``; change a value here and every department on that palette follows.

Sources (25 Sep 2026): ``police`` from punjabpolice.gov.pk's theme stylesheet; ``education``
from schools.punjab.gov.pk's theme stylesheets; ``ag`` is the AG Pension Portal's approved
palette. The sector palettes are chosen, not sourced -- adjust as departments send their branding.
"""
from __future__ import annotations

# The text, line and page greys of the 28 Sep 2026 modern layer, shared by every palette.
_GREYS = {"ink": "#17211C", "muted": "#5F6B64", "line": "#E3E7E4", "bg": "#F5F6F4"}

THEMES: dict[str, dict] = {
    # The greens are the office's own, read off the sign-in mock-up it sent on 22 Oct 2026
    # (--brand-900/800/700/600 there, --brand-100 as the second tint). They are darker and
    # cooler than the ramp they replace: #1B4332/#2D6A4F/#40916C was a brighter, more
    # saturated green and the live screen did not look like the sheet the office drew.
    # #40916C in particular measured 3.4:1 on the page background, under what AA asks of
    # 14px text, and it was the colour of the sign-in kicker; #1F6B4D measures 5.9:1.
    "ag": {"primary": "#0E3527", "primary2": "#18573F", "primary3": "#1F6B4D",
           "tint": "#EDF4EE", "tint2": "#E2EEE8", "accent": "#C9A227", "accent2": "#E7C55B",
           **_GREYS,
           # The system's name became SERVE PUNJAB on 22 Oct 2026, and the words it stands for
           # were put in this subtitle so the acronym could lead and the expansion be read once.
           # Once was not what happened: this subtitle is the second line of the header on every
           # screen of the portal, so the expansion was read on all of them, ahead of the office
           # whose name the line is for -- and a DDO signing in at the single portal got it too.
           # It belongs on the sign-in page, which says it in full under the name (Login.tsx),
           # and nowhere after that. What a header says is whose office this is.
           "subtitle": "Government of the Punjab, Office of the Accountant General, Lahore"},
    "police": {"primary": "#140D44", "primary2": "#0C2466", "primary3": "#2E3192",
               "tint": "#EEF0F8", "tint2": "#DCE0F2", "accent": "#D4A017", "accent2": "#E8BE4B",
               **_GREYS,
               "subtitle": "Punjab Police · Government of the Punjab"},
    "education": {"primary": "#032B2B", "primary2": "#053739", "primary3": "#4A968D",
                  "tint": "#EAF4F2", "tint2": "#D6E8E4", "accent": "#D5A316", "accent2": "#E9BE45",
                  **_GREYS,
                  "subtitle": "School Education Department · Government of the Punjab"},
    "health": {"primary": "#0B4F6C", "primary2": "#136F8C", "primary3": "#2B8FAE",
               "tint": "#EAF3F7", "tint2": "#D5E7EE", "accent": "#C9A227", "accent2": "#E7C55B",
               **_GREYS, "subtitle": "Health · Government of the Punjab"},
    "hospital": {"primary": "#0F5E5A", "primary2": "#177D78", "primary3": "#2E9C96",
                 "tint": "#E9F5F4", "tint2": "#D2ECEA", "accent": "#C9A227", "accent2": "#E7C55B",
                 **_GREYS, "subtitle": "Specialized Healthcare & Medical Education · Government of the Punjab"},
    "rescue": {"primary": "#7F1D1D", "primary2": "#A32A2A", "primary3": "#C64545",
               "tint": "#FBEEEE", "tint2": "#F4D9D9", "accent": "#1F3A5F", "accent2": "#3C5F8F",
               **_GREYS, "subtitle": "Punjab Emergency Service · Government of the Punjab"},
    "justice": {"primary": "#4A1C2B", "primary2": "#6B2437", "primary3": "#8E3A50",
                "tint": "#F6EEF0", "tint2": "#EBD9DE", "accent": "#C9A227", "accent2": "#E7C55B",
                **_GREYS, "subtitle": "Government of the Punjab"},
    "finance": {"primary": "#0F2A4A", "primary2": "#16406E", "primary3": "#2D5F95",
                "tint": "#ECF1F7", "tint2": "#D8E3F0", "accent": "#C9A227", "accent2": "#E7C55B",
                **_GREYS, "subtitle": "Government of the Punjab"},
    "agriculture": {"primary": "#245C2E", "primary2": "#357F41", "primary3": "#4F9E5A",
                    "tint": "#ECF4EC", "tint2": "#D7E9D8", "accent": "#C9A227", "accent2": "#E7C55B",
                    **_GREYS, "subtitle": "Government of the Punjab"},
    "infrastructure": {"primary": "#263B57", "primary2": "#35527A", "primary3": "#4E71A0",
                       "tint": "#EEF2F7", "tint2": "#DCE4EE", "accent": "#C9A227", "accent2": "#E7C55B",
                       **_GREYS, "subtitle": "Government of the Punjab"},
    "secretariat": {"primary": "#1E3D34", "primary2": "#2C5A4C", "primary3": "#3F7A67",
                    "tint": "#EDF3F1", "tint2": "#DAE8E3", "accent": "#C9A227", "accent2": "#E7C55B",
                    **_GREYS, "subtitle": "Government of the Punjab"},
}

SLOTS = ("primary", "primary2", "primary3", "tint", "tint2", "accent", "accent2", "ink", "muted", "line", "bg")


def theme_for(theme_key: str, *, title: str, subtitle: str | None = None) -> dict:
    """The full theme object the frontend applies, with the portal's title filled in."""
    base = THEMES.get(theme_key) or THEMES["secretariat"]
    return {**{k: base[k] for k in SLOTS}, "title": title, "subtitle": subtitle or base["subtitle"]}
