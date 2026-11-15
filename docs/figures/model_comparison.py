"""Two slide charts comparing prompt versions and models. Transparent PNGs, dark ink for light slides.

Writes misses_stacked.png and accuracy_dots.png next to this file:
    uv run --no-project --with matplotlib python -I docs/figures/model_comparison.py

Numbers (Nov 13) from the repo's own scorer (`hfal.score.pooled`, current quote checks and corrected labels), all 18
criteria, against CSSNY's sheet as it is:
- v2 / v5 / v7 Sonnet 5.5: the 15-hospital pilot (270 judgments).
- v7 Kimi K3 (max): the random 40 dev hospitals of the final run (720 judgments), the project's headline. Not the 77:
  the 22-hospital fill run was chosen by cost, not at random. Its corrected-label accuracy is the estimate in PLAN.md
  (93.4%, 90.3-94.5%), extrapolated from a reviewed random sample of 20 disagreements; the pilot rows were fully
  reviewed. The Kimi run has rule B of the form check (Nov 13); the Sonnet runs do not.
95% ranges resample whole hospitals.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent

# label, hospitals, judgments, false YES, false NO, flagged, accuracy %, 95% low, 95% high, corrected %, corrected is estimate
DATA = [
    ("v2  Sonnet 5.5", 15, 270, 27, 33, 26, 68.1, 59.6, 75.6, 83.9, False),
    ("v5  Sonnet 5.5", 15, 270, 34, 28, 20, 69.6, 60.7, 77.0, 89.0, False),
    ("v7  Sonnet 5.5", 15, 270, 36, 19, 10, 75.9, 64.8, 85.2, 95.3, False),
    ("v7  Kimi K3 (max)", 40, 720, 79, 33, 36, 79.4, 73.9, 84.3, 93.4, True),
]

INK, INK2 = "#0b0b0b", "#3a3936"
GRID, AXIS = "#d6d5ce", "#a9a8a0"
BLUE, ORANGE = "#2a78d6", "#eb6834"
FLAG, OK = "#6f6e69", "#e1e0d9"

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 15,
    "text.color": INK,
    "axes.labelcolor": INK2,
    "xtick.color": INK2,
    "xtick.labelsize": 14,
    "savefig.transparent": True,
})


def row_labels(ax):
    """Model name in bold, with the number of hospitals underneath."""
    ax.set_yticks(range(len(DATA)), [""] * len(DATA))
    tr = ax.get_yaxis_transform()
    for i, row in enumerate(DATA):
        ax.text(-0.02, i - 0.1, row[0], transform=tr, ha="right", va="bottom", fontsize=16,
                fontweight="bold", color=INK)
        ax.text(-0.02, i - 0.05, f"{row[1]} hospitals", transform=tr, ha="right", va="top",
                fontsize=13, color=INK2)


def clean(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", length=0, pad=8)


# ---------- 1. stacked bars: share of judgments by outcome ----------
fig, ax = plt.subplots(figsize=(12, 5.2), dpi=300)
gap = 0.35  # percentage points, a small gap between segments
segs = [("False YES", BLUE, "#ffffff"), ("False NO", ORANGE, "#ffffff"),
        ("Flagged for review", FLAG, "#ffffff"), ("Correct", OK, INK)]
for i, (_l, _h, n, fy, fn, fl, *_rest) in enumerate(DATA):
    vals = [fy, fn, fl, n - fy - fn - fl]
    left = 0.0
    for v, (name, color, txt) in zip(vals, segs):
        w = 100 * v / n
        ax.barh(i, w - gap, left=left, height=0.62, color=color, linewidth=0)
        ax.text(left + (w - gap) / 2, i, f"{w:.0f}%", ha="center", va="center", color=txt,
                fontsize=15 if w >= 5 else 12, fontweight="bold")
        left += w
row_labels(ax)
ax.set_xlim(0, 100)
ax.set_xticks(range(0, 101, 20), [f"{x}%" for x in range(0, 101, 20)])
ax.invert_yaxis()
ax.set_xlabel("Share of judgments (hospitals × 18 criteria), scored against CSSNY's sheet as is", fontsize=14)
clean(ax)
ax.legend(handles=[Patch(color=c, label=n) for n, c, _ in segs], ncol=4, frameon=False,
          loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=15, handlelength=1.2,
          handleheight=1.0, borderaxespad=0.3)
fig.tight_layout()
fig.savefig(OUT / "misses_stacked.png")
plt.close(fig)

# ---------- 2. dot and whisker: accuracy with 95% range ----------
fig, ax = plt.subplots(figsize=(12, 5.6), dpi=300)
for x in range(50, 101, 10):
    ax.axvline(x, color=GRID, linewidth=0.8, zorder=0)
for i, (*_x, acc, lo, hi, corr, corr_est) in enumerate(DATA):
    ax.plot([lo, hi], [i, i], color=BLUE, linewidth=2.5, solid_capstyle="round", zorder=2)
    for end in (lo, hi):
        ax.plot([end, end], [i - 0.12, i + 0.12], color=BLUE, linewidth=2.5, zorder=2)
    ax.plot(acc, i, "o", markersize=13, color=BLUE, markeredgecolor="#ffffff",
            markeredgewidth=1.5, zorder=3)
    ax.plot(corr, i, "o", markersize=13, markerfacecolor="none", markeredgecolor=ORANGE,
            markeredgewidth=2.6, zorder=3)
    ax.text(acc, i - 0.25, f"{acc:.0f}%", ha="center", va="bottom", fontsize=15,
            fontweight="bold", color=INK)
    ax.text(corr, i - 0.25, f"{'≈' if corr_est else ''}{corr:.0f}%", ha="center", va="bottom",
            fontsize=15, fontweight="bold", color=INK)
row_labels(ax)
ax.set_ylim(len(DATA) - 0.5, -0.8)
ax.set_xlim(50, 100)
ax.set_xticks(range(50, 101, 10), [f"{x}%" for x in range(50, 101, 10)])
ax.set_xlabel("Accuracy over all judgments (hospitals × 18 criteria)\n"
              "≈ Kimi's corrected figure is estimated from a reviewed random sample of its disagreements.",
              fontsize=14, linespacing=1.6)
clean(ax)
ax.legend(handles=[
    Line2D([], [], color=BLUE, marker="o", markersize=12, linewidth=2.5,
           markeredgecolor="#ffffff", label="Sheet as is, with 95% range"),
    Line2D([], [], color=ORANGE, marker="o", markersize=12, linewidth=0,
           markerfacecolor="none", markeredgewidth=2.6, label="Corrected labels (upper estimate)"),
], ncol=2, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=15,
    borderaxespad=0.3)
fig.tight_layout()
fig.savefig(OUT / "accuracy_dots.png")
plt.close(fig)
print("wrote", OUT / "misses_stacked.png", OUT / "accuracy_dots.png")
