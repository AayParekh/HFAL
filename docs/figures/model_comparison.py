"""Two slide charts from the v2/v5/v7 comparison table. Transparent PNGs, dark ink for light slides.

Edit the numbers in DATA if the table changes; "correct" is derived as 270 minus the three miss counts.
Writes misses_stacked.png and accuracy_dots.png next to this file:
    uv run --no-project --with matplotlib python -I docs/figures/model_comparison.py
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
N = 270

# label, false YES, false NO, flagged, accuracy %, CI low, CI high, corrected accuracy %
DATA = [
    ("v2  Sonnet 5.5", 27, 33, 26, 68, 60, 76, 83),
    ("v5  Sonnet 5.5", 34, 28, 20, 70, 61, 77, 89),
    ("v7  Sonnet 5.5", 37, 17, 14, 76, 64, 84, 93),
    ("v7  Kimi 3",     35, 19, 11, 75, 64, 84, 92),
]

INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
BLUE, ORANGE = "#2a78d6", "#eb6834"
FLAG, OK = "#898781", "#e1e0d9"

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 13,
    "text.color": INK,
    "axes.labelcolor": INK2,
    "xtick.color": MUTED,
    "ytick.color": INK,
    "savefig.transparent": True,
})


def clean(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", colors=MUTED, length=0)
    ax.invert_yaxis()


# ---------- 1. stacked bars: what happened to the 270 judgments ----------
fig, ax = plt.subplots(figsize=(11, 4.6), dpi=300)
gap = 0.9  # data units, about a 2px gap between segments
segs = [("False YES", BLUE, "#ffffff"), ("False NO", ORANGE, "#ffffff"),
        ("Flagged for review", FLAG, "#ffffff"), ("Correct", OK, INK2)]
for i, (label, fy, fn, fl, *_rest) in enumerate(DATA):
    vals = [fy, fn, fl, N - fy - fn - fl]
    left = 0
    for v, (name, color, txt) in zip(vals, segs):
        ax.barh(i, v - gap, left=left, height=0.62, color=color, linewidth=0)
        ax.text(left + (v - gap) / 2, i, str(v), ha="center", va="center",
                color=txt, fontsize=12, fontweight="bold" if name != "Correct" else "normal")
        left += v
ax.set_yticks(range(len(DATA)), [d[0] for d in DATA])
ax.set_xlim(0, N)
ax.set_xticks([0, 50, 100, 150, 200, 250, 270])
ax.set_xlabel(f"Judgments (15 hospitals × 18 criteria = {N}), scored against the sheet as is", fontsize=11)
clean(ax)
ax.legend(handles=[Patch(color=c, label=n) for n, c, _ in segs], ncol=4, frameon=False,
          loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=12, handlelength=1.2,
          handleheight=1.0, borderaxespad=0.3)
fig.tight_layout()
fig.savefig(OUT / "misses_stacked.png")
plt.close(fig)

# ---------- 2. dot and whisker: accuracy with 95% range ----------
fig, ax = plt.subplots(figsize=(11, 4.6), dpi=300)
for x in range(50, 101, 10):
    ax.axvline(x, color=GRID, linewidth=0.8, zorder=0)
for i, (label, *_c, acc, lo, hi, corr) in enumerate(DATA):
    ax.plot([lo, hi], [i, i], color=BLUE, linewidth=2, solid_capstyle="round", zorder=2)
    for end in (lo, hi):
        ax.plot([end, end], [i - 0.12, i + 0.12], color=BLUE, linewidth=2, zorder=2)
    ax.plot(acc, i, "o", markersize=11, color=BLUE, markeredgecolor="#ffffff",
            markeredgewidth=1.5, zorder=3)
    ax.plot(corr, i, "o", markersize=11, markerfacecolor="none", markeredgecolor=ORANGE,
            markeredgewidth=2.2, zorder=3)
    ax.text(acc, i - 0.27, f"{acc}%", ha="center", va="bottom", fontsize=11, color=INK)
    ax.text(corr, i - 0.27, f"{corr}%", ha="center", va="bottom", fontsize=11, color=INK2)
ax.set_yticks(range(len(DATA)), [d[0] for d in DATA])
ax.set_ylim(len(DATA) - 0.5, -0.75)
ax.set_xlim(50, 100)
ax.set_xticks(range(50, 101, 10), [f"{x}%" for x in range(50, 101, 10)])
ax.set_xlabel("Accuracy over 270 judgments (15 hospitals)", fontsize=11)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color(AXIS)
ax.tick_params(axis="y", length=0)
ax.tick_params(axis="x", colors=MUTED, length=0)
ax.legend(handles=[
    Line2D([], [], color=BLUE, marker="o", markersize=10, linewidth=2,
           markeredgecolor="#ffffff", label="Sheet as is, with 95% range"),
    Line2D([], [], color=ORANGE, marker="o", markersize=10, linewidth=0,
           markerfacecolor="none", markeredgewidth=2.2, label="Corrected labels (upper estimate)"),
], ncol=2, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=12,
    borderaxespad=0.3)
fig.tight_layout()
fig.savefig(OUT / "accuracy_dots.png")
plt.close(fig)
print("wrote", OUT / "misses_stacked.png", OUT / "accuracy_dots.png")
