"""Render the system architecture diagram. Style follows the provided voice.png reference.

    /home/tmc/vllm_env/bin/python3 docs/architecture.py

Same visual grammar as the reference: one entry box, a fan-out orchestrator, a row of ROLES,
a row of the MODELS that fill them, a converge arrow into a single engine, then a row of what
that engine produces. Mapping this system onto that shape puts the point of the architecture
on the page without a caption -- every model sits in the upper half, and everything below the
converge line is deterministic code with no model in it (BUILD §15 rule 1).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# Palette lifted from the reference so the two diagrams sit together in one deck.
BG_TOP, BG_BOTTOM = "#FDF6E9", "#F3EAD8"
BLUE, GREEN, ORANGE = "#2E6DA4", "#5FA777", "#F5BE66"
PURPLE, TEAL, BROWN = "#5C2A4E", "#1CA8A0", "#96683A"
SLATE = "#3F5E73"
EDGE, INK = "#5A5A5A", "#2B2B2B"

W, H = 15.0, 9.9


def box(ax, x, y, w, h, colour, title, subtitle=None, text_colour="white", fontsize=13):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.012,rounding_size=0.03",
        facecolor=colour, edgecolor=EDGE, linewidth=1.1, zorder=3,
    ))
    cy = y + h / 2
    if subtitle:
        ax.text(x + w / 2, cy + 0.10, title, ha="center", va="center",
                fontsize=fontsize, fontweight="bold", color=text_colour, zorder=4)
        ax.text(x + w / 2, cy - 0.155, subtitle, ha="center", va="center",
                fontsize=fontsize - 4.2, color=text_colour, zorder=4)
    else:
        ax.text(x + w / 2, cy, title, ha="center", va="center",
                fontsize=fontsize, fontweight="bold", color=text_colour, zorder=4)


def arrow(ax, x1, y1, x2, y2):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=13,
        color=EDGE, linewidth=1.15, shrinkA=0, shrinkB=0, zorder=2,
    ))


def elbow(ax, x1, y1, x2, y2, y_mid):
    """Orthogonal connector: down, across, then down into the target."""
    ax.plot([x1, x1], [y1, y_mid], color=EDGE, lw=1.15, zorder=2)
    ax.plot([x1, x2], [y_mid, y_mid], color=EDGE, lw=1.15, zorder=2)
    arrow(ax, x2, y_mid, x2, y2)


def build() -> Path:
    fig = plt.figure(figsize=(W, H), facecolor=BG_TOP)
    # Axes fill the whole figure, so the gradient reaches every edge. With a tight bbox and a
    # default inset the gradient stopped at the axes and left a hard seam across the middle.
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

    # Soft vertical gradient, as in the reference. 256 rows so the ramp is smooth rather than
    # a two-tone split.
    ramp = [[v] for v in range(256)]
    ax.imshow(ramp, extent=(0, W, 0, H), aspect="auto", zorder=0, interpolation="bilinear",
              cmap=matplotlib.colors.LinearSegmentedColormap.from_list(
                  "bg", [BG_TOP, BG_BOTTOM]))

    ax.text(W / 2, H - 0.34, "AI Pension Portal — AG Punjab",
            ha="center", va="center", fontsize=16, fontweight="bold", color=INK)
    ax.text(W / 2, H - 0.72,
            "sovereign document-intelligence pipeline · DGX Spark · nothing leaves the perimeter",
            ha="center", va="center", fontsize=9.5, color="#6B6B6B")

    cx = W / 2
    bw, bh = 3.55, 0.72          # standard box
    wide = 4.9

    # -- entry -------------------------------------------------------------------------
    y1 = H - 1.85
    box(ax, cx - wide / 2, y1, wide, bh, BLUE,
        "React Portal", "case intake · analysis · review · decision")

    # -- orchestrator ------------------------------------------------------------------
    y2 = y1 - 1.18
    arrow(ax, cx, y1, cx, y2 + bh)
    box(ax, cx - wide / 2, y2, wide, bh, GREEN,
        "FastAPI Pipeline Orchestrator", "resumable stages · SSE events · GPU telemetry")

    # -- roles -------------------------------------------------------------------------
    y3 = y2 - 1.30
    lx, rx = cx - 4.95, cx + 4.95
    for x, title, sub in (
        (lx, "OCR & Layout", "first pass · form-number check"),
        (cx, "Document Classification", "43 pages → 40 documents"),
        (rx, "Field Extraction", "per-document schemas · read twice"),
    ):
        box(ax, x - bw / 2, y3, bw, bh, ORANGE, title, sub, text_colour=INK)
    mid = y2 - 0.55
    ax.plot([lx, rx], [mid, mid], color=EDGE, lw=1.15, zorder=2)
    ax.plot([cx, cx], [y2, mid], color=EDGE, lw=1.15, zorder=2)
    for x in (lx, cx, rx):
        arrow(ax, x, mid, x, y3 + bh)

    # -- the models that fill those roles ----------------------------------------------
    y4 = y3 - 1.12
    for x, title, sub in (
        (lx, "PaddleOCR-VL", ":8012 · independent reader"),
        (cx, "Qwen3-VL 30B-A3B", ":8011 · closed type enum"),
        (rx, "Qwen3-VL 30B-A3B", ":8011 · schema-constrained"),
    ):
        box(ax, x - bw / 2, y4, bw, bh, PURPLE, title, sub)
        arrow(ax, x, y3, x, y4 + bh)

    # -- converge ----------------------------------------------------------------------
    y5 = y4 - 1.36
    conv = y4 - 0.62
    ax.plot([lx, rx], [conv, conv], color=EDGE, lw=1.15, zorder=2)
    for x in (lx, rx):
        ax.plot([x, x], [y4, conv], color=EDGE, lw=1.15, zorder=2)
    ax.plot([cx, cx], [y4, conv], color=EDGE, lw=1.15, zorder=2)
    arrow(ax, cx, conv, cx, y5 + bh)

    ax.text(W - 0.35, conv + 0.16, "AI extracts  ↑", ha="right", va="bottom",
            fontsize=9, style="italic", color="#7A6A55")
    ax.text(W - 0.35, conv - 0.16, "code calculates  ↓", ha="right", va="top",
            fontsize=9, style="italic", color="#7A6A55")

    box(ax, cx - wide / 2 - 0.55, y5, wide + 1.1, bh, TEAL,
        "Deterministic Rules Layer", "no model · no network · byte-identical, forever")

    # -- what the deterministic layer produces -----------------------------------------
    y6 = y5 - 1.30
    qw = 3.15
    slots = (cx - 5.25, cx - 1.75, cx + 1.75, cx + 5.25)
    for x, (title, sub) in zip(slots, [
        ("Checklist Engine", "16 items · MISSING ≠ DEFECTIVE"),
        ("Flag Battery", "cross-document · precedence"),
        ("Rules Engine", "effective-dated rule packs"),
        ("Notifications", "bilingual · dept + claimant"),
    ]):
        box(ax, x - qw / 2, y6, qw, bh, BROWN, title, sub, fontsize=11.5)
    fan = y5 - 0.55
    ax.plot([slots[0], slots[-1]], [fan, fan], color=EDGE, lw=1.15, zorder=2)
    ax.plot([cx, cx], [y5, fan], color=EDGE, lw=1.15, zorder=2)
    for x in slots:
        arrow(ax, x, fan, x, y6 + bh)

    # -- rules-corpus RAG ----------------------------------------------------------------
    # Drawn BELOW the outputs with the arrow pointing up, because retrieval annotates what the
    # deterministic layer produced -- it never contributes to a figure (BUILD §15 rule 1).
    y7 = y6 - 1.32
    box(ax, cx - wide / 2 - 1.35, y7, wide + 2.7, bh, SLATE,
        "Rules-Corpus Retrieval",
        "Qwen3-Embedding :8093 → Qwen3-Reranker :8094 · 208 chunks")
    up = y7 + bh + 0.30
    ax.plot([slots[0], slots[-1]], [up, up], color=EDGE, lw=1.15, zorder=2)
    ax.plot([cx, cx], [y7 + bh, up], color=EDGE, lw=1.15, zorder=2)
    for x in slots:
        arrow(ax, x, up, x, y6)
    ax.text(cx + 5.9, up + 0.02, "citations", ha="left", va="center",
            fontsize=8.5, style="italic", color="#7A6A55")

    # -- footer ------------------------------------------------------------------------
    ax.text(cx, 0.26,
            "every figure carries its rule id and computation  ·  unresolved rules emit BOTH "
            "readings, never one  ·  append-only audit",
            ha="center", va="center", fontsize=9, color="#6B6B6B")

    out = Path(__file__).parent / "architecture.png"
    fig.savefig(out, dpi=170, facecolor=BG_TOP)
    plt.close(fig)
    return out


if __name__ == "__main__":
    print("wrote", build())
