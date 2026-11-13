"""Matplotlib dashboards (dark theme) drawn from core.analytics data."""
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates as mdates
from matplotlib.figure import Figure

from config import FLOORS, FLOOR_NAMES, RATES
from gui import theme as T

BG, PANEL, GRID, TXT, MUT = T.BG, T.PANEL, "#1E2A44", T.TEXT, T.MUTED
TYPE_COL = [T.TYPE_COLORS[k] for k in RATES]


def new_figure():
    fig = Figure(figsize=(12, 6), dpi=100, facecolor=BG)
    return fig


def _style(ax, title):
    ax.set_facecolor(PANEL)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUT, labelsize=7.5, length=3)
    ax.grid(axis="y", color=GRID, linewidth=0.6, alpha=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", color=TXT, fontsize=9.5, fontweight="bold", pad=9)


def _empty(ax, text="No data in this range yet"):
    ax.text(0.5, 0.5, text, ha="center", va="center", color=T.DIM, fontsize=9, transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])


def _thin(ax, labels, n=6):
    ax.set_xlim(-0.7, max(len(labels), 6) - 0.3)
    step = max(1, len(labels) // n)
    ax.set_xticks(range(0, len(labels), step))
    ax.set_xticklabels([labels[i] for i in range(0, len(labels), step)])


def draw_dashboard(fig, d):
    """d: dict with keys trend, dist, floors, flow, revenue, peaks, avgdur (see AnalyticsPage)."""
    fig.clear()
    gs = fig.add_gridspec(2, 4, left=0.035, right=0.99, top=0.94, bottom=0.08, hspace=0.5, wspace=0.34)

    # 1. occupancy trend
    ax = fig.add_subplot(gs[0, 0:2])
    _style(ax, "Occupancy trend (% of capacity)")
    if d["trend"]:
        xs = [p["t"] for p in d["trend"]]
        ys = [p["percent"] for p in d["trend"]]
        ax.plot(xs, ys, color=T.CYAN, linewidth=2, marker="o" if len(xs) < 25 else None, markersize=3.5)
        if len(xs) == 1:
            from datetime import timedelta
            ax.set_xlim(xs[0] - timedelta(minutes=1), xs[0] + timedelta(minutes=1))
        ax.fill_between(xs, ys, color=T.CYAN, alpha=0.14)
        ax.set_ylim(0, max(100, max(ys) + 5) if max(ys) > 100 else 100)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=6))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if d["span"] and d["span"] <= 90000 else "%d %b"))
    else:
        _empty(ax)

    # 2. vehicle categories
    ax = fig.add_subplot(gs[0, 2])
    _style(ax, "Vehicle categories")
    ax.grid(False)
    total = sum(d["dist"].values())
    if total:
        vals = [d["dist"][k] for k in RATES]
        ax.pie(vals, colors=TYPE_COL, startangle=90, counterclock=False,
               wedgeprops=dict(width=0.38, edgecolor=PANEL, linewidth=2))
        ax.text(0, 0, str(total), ha="center", va="center", color=TXT, fontsize=16, fontweight="bold")
        ax.legend([f"{k} {d['dist'][k]}" for k in RATES], loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=2,
                  frameon=False, labelcolor=MUT, fontsize=7.5, handlelength=0.8, columnspacing=1.2)
    else:
        _empty(ax)

    # 3. floor-wise occupancy (current)
    ax = fig.add_subplot(gs[0, 3])
    _style(ax, "Floor-wise occupancy (now)")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.grid(axis="y", visible=False)
    labels = [FLOOR_NAMES[f].split()[0] for f in FLOORS]
    occ = [d["floors"][f]["occupied"] for f in FLOORS]
    res = [d["floors"][f]["reserved"] for f in FLOORS]
    av = [d["floors"][f]["available"] for f in FLOORS]
    y = range(len(FLOORS))
    ax.barh(y, occ, color=T.RED, height=0.55, label="Occupied")
    ax.barh(y, res, left=occ, color=T.AMBER, height=0.55, label="Reserved")
    ax.barh(y, av, left=[a + b for a, b in zip(occ, res)], color="#1F7A52", height=0.55, label="Available")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 18)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=3, frameon=False, labelcolor=MUT, fontsize=7, handlelength=0.8, columnspacing=1)

    # 4. entries vs exits
    ax = fig.add_subplot(gs[1, 0])
    _style(ax, "Entries vs exits")
    if d["flow"]:
        labels = [p["label"] for p in d["flow"]]
        x = list(range(len(labels)))
        ax.bar([i - 0.2 for i in x], [p["entries"] for p in d["flow"]], width=0.4, color=T.CYAN, label="Entries")
        ax.bar([i + 0.2 for i in x], [p["exits"] for p in d["flow"]], width=0.4, color=T.AMBER, label="Exits")
        _thin(ax, labels, 5)
        ax.set_ylim(0, max(max(p["entries"], p["exits"]) for p in d["flow"]) * 1.35 + 1)
        ax.legend(frameon=False, labelcolor=MUT, fontsize=7, loc="upper right", ncol=2)
    else:
        _empty(ax)

    # 5. revenue
    ax = fig.add_subplot(gs[1, 1])
    _style(ax, "Revenue (INR)")
    if d["revenue"]:
        labels = [p["label"] for p in d["revenue"]]
        x = list(range(len(labels)))
        ax.bar(x, [p["revenue"] for p in d["revenue"]], color=T.PURPLE, width=0.6, alpha=0.9)
        ax2 = ax.twinx()
        ax2.plot(x, [p["cumulative"] for p in d["revenue"]], color=T.GREEN, linewidth=1.8)
        ax2.tick_params(colors=T.GREEN, labelsize=7, length=2)
        for s in ("top", "left", "bottom"):
            ax2.spines[s].set_visible(False)
        ax2.spines["right"].set_color(GRID)
        _thin(ax, labels, 5)
    else:
        _empty(ax)

    # 6. peak hours
    ax = fig.add_subplot(gs[1, 2])
    _style(ax, "Peak parking hours (entries by hour)")
    peaks = d["peaks"]
    if any(peaks):
        top = max(range(24), key=lambda h: peaks[h])
        ax.bar(range(24), peaks, color=["#2A7FB0" if h != top else T.AMBER for h in range(24)], width=0.75)
        ax.set_xticks(range(0, 24, 3))
        ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 3)])
    else:
        _empty(ax)

    # 7. average duration per type
    ax = fig.add_subplot(gs[1, 3])
    _style(ax, "Average parking duration (min)")
    per = d["avgdur"]
    if any(per.values()):
        ax.bar(list(RATES), [per[k] / 60 for k in RATES], color=TYPE_COL, width=0.55)
        for i, k in enumerate(RATES):
            if per[k]:
                ax.text(i, per[k] / 60, f"{per[k] / 60:.1f}", ha="center", va="bottom", color=TXT, fontsize=7.5)
    else:
        _empty(ax)
