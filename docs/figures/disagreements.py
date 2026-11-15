"""Slide chart: where and why the tool and CSSNY's sheet disagree. Transparent PNG, dark ink for light slides.
Writes disagreements.png next to this file:
    uv run --no-project --with matplotlib python -I docs/figures/disagreements.py

Counts only (no hospital, label or note), Nov 13, from the repo's own scorer (`hfal.score.classify`,
`schema.effective_answer`) on the random 40 dev hospitals of the final run (prompt v7, Kimi K3 max,
run 20261113T045436Z), against CSSNY's sheet as it is: 720 judgments, 112 YES/NO disagreements (79 tool YES / sheet
NO, 33 tool NO / sheet YES) and 36 open answers (not shown).
Where: the 10 criteria with the most YES/NO disagreements (91 of the 112); the other 8 have 21, at most 4 each.
Why: the 20-row random sample of the 112, reviewed by the owner (Nov 13, data/review/final40_sample_review.csv
`human_bucket`): 18 golden_or_site, 1 rubric_differs, 1 ambiguous. The owner read the judge's explanation and its
verified evidence but did not re-read every source document (PLAN.md).
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent

# plain-language question, tool YES / sheet NO, tool NO / sheet YES (of 40 hospitals each)
WHERE = [
    ("Documents agree with each other", 2, 17),
    ("Uses current poverty figures", 14, 1),
    ("No deadline to apply", 3, 8),
    ("Service area meets the 2007 rule", 10, 0),
    ("Summary describes the service area", 8, 0),
    ("No asset checks", 2, 5),
    ("Application gives contact information", 6, 0),
    ("Policy posted", 5, 0),
    ("Application has income and discount tables", 5, 0),
    ("Assistance reaches 400% of poverty level", 5, 0),
]
WHY = [  # the 20 hand-checked YES/NO disagreements
    (18, "Tool was right: the website has changed\nsince September, or the sheet was off", "#13804f"),
    (1, "Our rubric reads the rule differently", "#b26205"),
    (1, "The documents themselves are unclear", "#8a8980"),
]

INK, INK2 = "#0b0b0b", "#3a3936"
GRID, AXIS = "#d6d5ce", "#a9a8a0"
BLUE, ORANGE = "#2a78d6", "#eb6834"

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 15,
    "text.color": INK,
    "axes.labelcolor": INK2,
    "xtick.color": INK2,
    "xtick.labelsize": 13,
    "savefig.transparent": True,
})

fig = plt.figure(figsize=(16, 6.9), dpi=300)
gs = fig.add_gridspec(1, 2, width_ratios=[1.45, 1], wspace=0.08, left=0.265, right=0.985, top=0.8, bottom=0.21)

# ---------- where: stacked bars per question ----------
ax = fig.add_subplot(gs[0])
segs = [("Tool YES, CSSNY NO", BLUE), ("Tool NO, CSSNY YES", ORANGE)]
for i, (_name, *vals) in enumerate(WHERE):
    left = 0
    for v, (_n, color) in zip(vals, segs):
        if v:
            ax.barh(i, v - 0.12, left=left, height=0.66, color=color, linewidth=0)
            if v >= 2:
                ax.text(left + (v - 0.12) / 2, i, str(v), ha="center", va="center", color="#ffffff",
                        fontsize=13, fontweight="bold")
        left += v
ax.set_yticks(range(len(WHERE)), [w[0] for w in WHERE], fontsize=15, color=INK)
ax.set_ylim(len(WHERE) - 0.5, -0.6)
ax.set_xlim(0, 20)
ax.set_xticks(range(0, 21, 5))
for x in range(5, 21, 5):
    ax.axvline(x, color=GRID, linewidth=0.8, zorder=0)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color(AXIS)
ax.tick_params(axis="y", length=0, pad=8)
ax.tick_params(axis="x", length=0, pad=6)
ax.set_xlabel("Hospitals (of 40) where the answers differ", fontsize=14)
fig.text(0.015, 0.925, "Where they differ most", fontsize=21, fontweight="bold", va="bottom")
ax.legend(handles=[Patch(color=c, label=n) for n, c in segs], ncol=2, frameon=False, loc="lower left",
          bbox_to_anchor=(-0.6, 1.0), fontsize=14, handlelength=1.1, handleheight=1.0, columnspacing=1.6,
          borderaxespad=0.2)

# ---------- why: waffle of the 20 hand-checked disagreements ----------
wx = fig.add_subplot(gs[1])
wx.set_xlim(-0.6, 13.5)
wx.set_ylim(9.2, -0.9)
wx.set_aspect("equal")
wx.set_anchor("N")
wx.axis("off")
S, G, COLS = 0.82, 0.18, 10

k = 0
for n, _label, color in WHY:
    for _ in range(n):
        r, c = divmod(k, COLS)
        wx.add_patch(FancyBboxPatch((c * (S + G), 1.6 + r * (S + G)), S, S, boxstyle="round,pad=0,rounding_size=0.12",
                                    facecolor=color, linewidth=0))
        k += 1
y = 1.6 + ((k - 1) // COLS + 1) * (S + G) + 0.4
for n, label, color in WHY:
    mid = y + 0.4 + 0.31 * label.count("\n")
    wx.add_patch(FancyBboxPatch((0, mid - 0.28), 0.55, 0.55, boxstyle="round,pad=0,rounding_size=0.1",
                                facecolor=color, linewidth=0))
    wx.text(0.85, mid, f"{n}", fontsize=15, fontweight="bold", va="center")
    wx.text(1.9, mid, label, fontsize=14, va="center", color=INK2, linespacing=1.25)
    y += 1.0 + 0.62 * label.count("\n")
fig.text(0.703, 0.925, "Why", fontsize=21, fontweight="bold", va="bottom")
wx.text(-0.6, 0.0, "A random 20 of the 112 YES/NO disagreements,\nchecked by hand", fontsize=14.5, fontweight="bold",
        va="top")

fig.text(0.015, 0.03,
         "Random 40 development hospitals, against CSSNY's September 2025 sheet as it is. The 10 questions shown hold 91 of "
         "the 112 YES/NO disagreements; the other 8 have at most 4 each.\nHand check: Nov 13, on an AI reviewer's "
         "explanation and its evidence, which software confirmed word for word. 20 is a small sample (95% range for 18 of 20: 70–97%).",
         fontsize=11.5, color=INK2, linespacing=1.5)
fig.savefig(OUT / "disagreements.png")
plt.close(fig)
print("wrote", OUT / "disagreements.png")
