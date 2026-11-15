"""Slide chart: estimated hospitals needing a manual check, by prompt version and model, scaled to all 211 hospitals,
with the model cost for the two v7 rows. Transparent PNG, dark ink for light slides. Writes manual_checks.png:
    uv run --no-project --with matplotlib python -I docs/figures/manual_checks.py

A hospital "needs a check" when at least one of its 17 graded answers is open (UNCLEAR, NOT_FOUND, or a YES/NO
whose quote did not verify; `hfal.score.effective_answer`), counted Nov 13.
- v2 / v5 / v7 Sonnet 5.5: the 15-hospital pilot.
- v7 Kimi K3 (max): the random 40 dev hospitals of the final run (not the 77: the fill run was chosen by cost).
The 95% range is a Wilson interval on k of n; the count and both range ends are scaled to 211, which assumes the
other hospitals are like the ones measured. Costs per report and for all 211 are the owner's figures.
"""
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
N_ALL = 211  # every hospital in CSSNY's September 2025 review

# label, hospitals measured, of them needing a check, open items in total, (cost per report, cost for all) or None
DATA = [
    ("v2  Sonnet 5.5", 15, 13, 24, None),
    ("v5  Sonnet 5.5", 15, 12, 19, None),
    ("v7  Sonnet 5.5", 15, 5, 10, (0.27, 58)),
    ("v7  Kimi K3 (max)", 40, 18, 35, (0.61, 129)),
]

INK, INK2 = "#0b0b0b", "#3a3936"
GRID, AXIS, BLUE = "#d6d5ce", "#a9a8a0", "#2a78d6"

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 15,
    "text.color": INK,
    "axes.labelcolor": INK2,
    "xtick.color": INK2,
    "xtick.labelsize": 14,
    "savefig.transparent": True,
})


def wilson(k, n, z=1.959964):
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def in_ten(share):
    return math.floor(share * 10 + 0.5)


fig, ax = plt.subplots(figsize=(14, 6.4), dpi=300)
ticks = [0, 50, 100, 150, N_ALL]
for x in ticks:
    ax.axvline(x, color=GRID, linewidth=0.8, zorder=0)

tr = ax.get_yaxis_transform()
for i, (label, n, k, items, cost) in enumerate(DATA):
    share = k / n
    lo, hi = wilson(k, n)
    est, lo_s, hi_s = share * N_ALL, lo * N_ALL, hi * N_ALL
    ax.plot([lo_s, hi_s], [i, i], color=BLUE, linewidth=2.5, solid_capstyle="round", zorder=2)
    for end in (lo_s, hi_s):
        ax.plot([end, end], [i - 0.12, i + 0.12], color=BLUE, linewidth=2.5, zorder=2)
    ax.plot(est, i, "o", markersize=13, color=BLUE, markeredgecolor="#ffffff",
            markeredgewidth=1.5, zorder=3)
    ax.text(est, i - 0.25, f"{est:.0f}  ({share:.0%})", ha="center", va="bottom", fontsize=15,
            fontweight="bold", color=INK)
    # row label: model in bold, hospitals measured underneath
    ax.text(-0.02, i - 0.1, label, transform=tr, ha="right", va="bottom", fontsize=16,
            fontweight="bold", color=INK)
    ax.text(-0.02, i - 0.05, f"{n} hospitals", transform=tr, ha="right", va="top", fontsize=13, color=INK2)
    # note on the right: how many in 10, items each, and cost
    rough = f"about {in_ten(share)} in 10 hospitals"
    if in_ten(lo) != in_ten(hi):
        rough += f" (range {in_ten(lo)}–{in_ten(hi)})"
    lines = [(rough, "normal", INK2), (f"~{round(items / k)} of 17 items in each", "normal", INK2)]
    if cost:  # "\$" keeps matplotlib from reading a pair of dollar signs as a formula
        lines.append((f"\\${cost[0]:.2f} per report · \\${cost[1]:,} for all {N_ALL}", "bold", INK))
    step = 22  # points between lines
    for j, (text, weight, color) in enumerate(lines):
        offset = step * ((len(lines) - 1) / 2 - j)
        ax.annotate(text, xy=(1.03, i), xycoords=tr, xytext=(0, offset), textcoords="offset points",
                    ha="left", va="center", fontsize=14, fontweight=weight, color=color,
                    annotation_clip=False)

ax.set_yticks(range(len(DATA)), [""] * len(DATA))
ax.set_ylim(len(DATA) - 0.5, -0.8)
ax.set_xlim(0, N_ALL)
ax.set_xticks(ticks, [str(t) if t != N_ALL else f"all {N_ALL}" for t in ticks])
ax.set_xlabel(
    f"Estimated hospitals needing a manual check, of all {N_ALL}\n"
    f"Scaled up from the hospitals measured; assumes the other hospitals are similar.",
    fontsize=14, linespacing=1.6)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color(AXIS)
ax.tick_params(axis="y", length=0)
ax.tick_params(axis="x", length=0, pad=8)
ax.legend(handles=[
    Line2D([], [], color=BLUE, marker="o", markersize=12, linewidth=2.5,
           markeredgecolor="#ffffff", label="Estimate, with 95% range"),
], frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=15, borderaxespad=0.3)
fig.tight_layout()
fig.subplots_adjust(right=0.70)
fig.savefig(OUT / "manual_checks.png")
plt.close(fig)
print("wrote", OUT / "manual_checks.png")
