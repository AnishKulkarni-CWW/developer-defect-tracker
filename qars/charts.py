"""
Every chart and icon in the product, rendered by matplotlib into PNG bytes.

Matplotlib is used deliberately over a browser-based charting stack: it needs no
Chromium, no network and very little memory, and it freezes cleanly into a
one-file .exe later on. The Agg backend is forced before pyplot is imported so
nothing ever tries to open a window on a headless machine.
"""

from __future__ import annotations

import io
import math
import os
import tempfile

# Point matplotlib's cache somewhere guaranteed writable before it is imported.
# On a hosted container HOME can be read-only, and matplotlib then prints a
# warning into the app's logs on every single chart.
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "qars-mpl"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                        # noqa: E402
from matplotlib.ticker import MaxNLocator               # noqa: E402
from matplotlib.patches import (Circle, Ellipse, FancyBboxPatch,  # noqa: E402
                                Polygon, Rectangle)

from . import theme as T                               # noqa: E402

DPI = 190
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.edgecolor": T.hx(T.BORDER),
    "axes.linewidth": 0.8,
    "text.color": T.hx(T.TEXT),
    "axes.labelcolor": T.hx(T.TEXT_MUTED),
    "xtick.color": T.hx(T.TEXT_MUTED),
    "ytick.color": T.hx(T.TEXT_MUTED),
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
})


def _out(fig, transparent=False, tight=True):
    """
    Save at exactly `figsize`, so a chart asked for at 4.5x3.9in always comes
    back at that aspect. bbox_inches="tight" would crop to the ink instead,
    which makes the placed height on a slide impossible to predict.

    `tight=False` is for figures whose axes were positioned by hand to reserve
    margin for labels drawn outside them; re-fitting those would reclaim the
    margin and clip the labels.
    """
    if tight:
        try:
            fig.tight_layout(pad=0.3)
        except Exception:                                    # noqa: BLE001
            pass
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, transparent=transparent)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _lead_out(ax, items, radius, fontsize):
    """
    Annotate slices too narrow to hold their own figure.

    Labels are stacked in two columns either side of the ring rather than left
    where the slice happens to point, because two thin slices next to each
    other put their text in the same place. Within a column they are laid out
    top-down in the order the slices come round the ring, so the leader lines
    cannot cross, and the whole column is slid back inside the axes if it runs
    past the top — a label drawn off the canvas is the same as no label.

    Drawn with annotation_clip off so they sit in the figure margin and the
    ring itself stays full size.

    items: [(angle_rad, text, colour)]
    """
    if not items:
        return
    gap, col_x, limit = 0.235, 1.20, 0.96
    for side in (1, -1):
        group = [i for i in items if (math.cos(i[0]) >= 0) == (side > 0)]
        if not group:
            continue
        group.sort(key=lambda i: -math.sin(i[0]))            # top of the ring first
        ys, prev = [], None
        for ang, _txt, _c in group:
            y = math.sin(ang) * col_x
            if prev is not None and y > prev - gap:
                y = prev - gap
            ys.append(y)
            prev = y
        over = ys[0] - limit
        if over > 0:
            ys = [y - over for y in ys]
        under = -limit - ys[-1]
        if under > 0:
            ys = [min(limit, y + under) for y in ys]
        for (ang, txt, colour), y in zip(group, ys):
            ax.annotate(txt,
                        xy=(math.cos(ang) * radius, math.sin(ang) * radius),
                        xytext=(side * col_x, y),
                        ha="left" if side > 0 else "right", va="center",
                        fontsize=fontsize, fontweight="bold", color=T.hx(colour),
                        annotation_clip=False,
                        arrowprops={"arrowstyle": "-", "lw": 0.9, "shrinkA": 0,
                                    "shrinkB": 1, "color": T.hx(colour)})


def _empty(w, h, msg="No data for this selection"):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.axis("off")
    ax.text(0.5, 0.5, msg, ha="center", va="center",
            fontsize=11, color=T.hx(T.TEXT_MUTED))
    return _out(fig)


# ==========================================================================
# 1. Monthly quality score column chart
# ==========================================================================
def quality_trend(rows, w=6.4, h=3.5):
    """Column chart of quality score per month, values printed above each bar."""
    rows = [r for r in rows if r.get("score") is not None]
    if not rows:
        return _empty(w, h)

    multi_year = len({r.get("year") for r in rows if r.get("year")}) > 1
    if len(rows) == 1:
        labels = [rows[0]["label"]]
    elif multi_year:
        labels = [r["label"].replace(" ", "\n") for r in rows]
    else:
        labels = [r["label"].split(" ")[0] for r in rows]
    vals = [r["score"] for r in rows]

    fig, ax = plt.subplots(figsize=(w, h))
    bw = 0.56 if len(vals) > 2 else (0.34 if len(vals) == 2 else 0.22)
    # The latest month carries the full brand colour and the earlier ones a
    # lighter tint of it, so the eye lands on "where we are now" before it
    # reads the history.
    cols = [T.hx(T.mix(T.BRAND, T.WHITE, 0.55))] * len(vals)
    cols[-1] = T.hx(T.BRAND)
    bars = ax.bar(range(len(vals)), vals, width=bw, color=cols, zorder=3)
    ax.set_xlim(-0.6, len(vals) - 0.4)

    lo = max(0, math.floor(min(vals) / 5) * 5 - 5)
    hi = 100
    if lo >= min(vals):
        lo = max(0, min(vals) - 5)
    ax.set_ylim(lo, hi + (hi - lo) * 0.13)

    for i, (b, v) in enumerate(zip(bars, vals)):
        ax.text(b.get_x() + b.get_width() / 2, v + (hi - lo) * 0.025, f"{v:.2f}%",
                ha="center", va="bottom", fontsize=8.6, fontweight="bold",
                color=T.hx(T.BRAND if i == len(vals) - 1 else T.TEXT))

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=9, fontweight="bold")
    ax.set_ylabel("Quality Score (%)", fontsize=8.6)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10]))
    ax.yaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(axis="y", color=T.hx(T.GRID), lw=0.8, zorder=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(T.hx(T.BORDER))
    ax.spines["bottom"].set_color(T.hx(T.BORDER))
    return _out(fig)


# ==========================================================================
# 2. Defect category donut
# ==========================================================================
def category_donut(rows, w=3.5, h=3.5, centre_total=None):
    rows = [r for r in rows if r.get("total", 0) > 0]
    if not rows:
        return _empty(w, h, "No defects")

    vals = [r["total"] for r in rows]
    cols = [T.hx(T.CATEGORY_COLORS.get(r["category"], T.TEXT_MUTED)) for r in rows]
    total = centre_total if centre_total is not None else sum(vals)

    fig = plt.figure(figsize=(w, h))
    # A hand-placed axes, inset from the figure, leaves a margin for the
    # callouts and stops the ring — and the percentage sitting on it — running
    # into the edge of the image.
    ax = fig.add_axes([0.13, 0.05, 0.74, 0.90])
    wedges, _ = ax.pie(vals, colors=cols, startangle=90, counterclock=False, radius=1.0,
                       wedgeprops={"width": 0.36, "edgecolor": "white", "linewidth": 2})

    callouts = []
    for wg, r in zip(wedges, rows):
        ang = math.radians((wg.theta1 + wg.theta2) / 2)
        colour = T.CATEGORY_COLORS.get(r["category"], T.TEXT_MUTED)
        if r["pct"] >= 9:
            # Wide enough to carry the figure on the ring itself.
            ax.text(math.cos(ang) * 0.82, math.sin(ang) * 0.82, f"{r['pct']:.0f}%",
                    ha="center", va="center", fontsize=8.6, fontweight="bold",
                    color="white")
        else:
            # Too narrow for text on the ring, so it is led out rather than
            # dropped — a slice with no number is a slice nobody can read.
            callouts.append((ang, f"{r['pct']:.0f}%", colour))
    _lead_out(ax, callouts, 1.0, 8.2)

    ax.text(0, 0.09, f"{total}", ha="center", va="center",
            fontsize=20, fontweight="bold", color=T.hx(T.TEXT))
    ax.text(0, -0.17, "Total\nDefects", ha="center", va="center",
            fontsize=7.6, color=T.hx(T.TEXT_MUTED), linespacing=1.35)
    ax.set_xlim(-1.02, 1.02)
    ax.set_ylim(-1.02, 1.02)
    ax.set(aspect="equal")
    ax.axis("off")
    return _out(fig, tight=False)


# ==========================================================================
# 3. Error trend per month (defects by category over time)
# ==========================================================================
def error_trend(rows, w=6.6, h=3.3):
    """Stacked internal/external defect columns with a task-volume line."""
    if not rows:
        return _empty(w, h)

    multi_year = len({r.get("year") for r in rows if r.get("year")}) > 1
    labels = [(r["label"].replace(" ", "\n") if multi_year else r["label"].split(" ")[0])
              for r in rows]
    errs = [r["error"] for r in rows]
    obs = [r.get("observation", 0) for r in rows]
    idx = range(len(rows))

    fig, ax = plt.subplots(figsize=(w, h))
    bw = 0.5 if len(rows) > 2 else (0.3 if len(rows) == 2 else 0.2)
    ax.bar(idx, errs, width=bw, color=T.hx(T.RED), label="Errors", zorder=3)
    ax.bar(idx, obs, width=bw, bottom=errs, color=T.hx(T.ORANGE),
           label="Observations", zorder=3)
    ax.set_xlim(-0.6, len(rows) - 0.4)

    for i, (e, o) in enumerate(zip(errs, obs)):
        if e:
            ax.text(i, e / 2, str(e), ha="center", va="center",
                    fontsize=8.2, fontweight="bold", color="white")
        if o:
            ax.text(i, e + o / 2, str(o), ha="center", va="center",
                    fontsize=8.2, fontweight="bold", color="white")

    ax2 = ax.twinx()
    ax2.plot(idx, [r["total"] for r in rows], color=T.hx(T.BLUE), lw=2,
             marker="o", ms=5, zorder=4, label="Tasks audited")
    ax2.set_ylabel("Tasks audited", fontsize=8.4, color=T.hx(T.BLUE))
    ax2.tick_params(axis="y", labelsize=8, colors=T.hx(T.BLUE))
    ax2.set_ylim(0, max(max(r["total"] for r in rows) * 1.3, 1))
    ax2.spines["top"].set_visible(False)

    ax.set_xticks(list(idx))
    ax.set_xticklabels(labels, fontsize=9, fontweight="bold")
    ax.set_ylabel("Defects", fontsize=8.4)
    ax.set_ylim(0, max(max(e + o for e, o in zip(errs, obs)) * 1.45, 1))
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(axis="y", color=T.hx(T.GRID), lw=0.8, zorder=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=7.8, frameon=False, ncol=3)
    return _out(fig)


# ==========================================================================
# 4. Internal vs external split
# ==========================================================================
def internal_external(internal, external, w=3.4, h=2.6):
    if internal + external == 0:
        return _empty(w, h, "No defects")
    fig, ax = plt.subplots(figsize=(w, h))
    vals = [internal, external]
    cols = [T.hx(T.BRAND), T.hx(T.BLUE)]
    names = ["Test\nlink", "Live\nlink"]
    bars = ax.barh(names, vals, height=0.38, color=cols, zorder=3)
    ax.set_ylim(-0.75, 1.75)
    tot = internal + external
    for b, v in zip(bars, vals):
        ax.text(b.get_width() + tot * 0.02, b.get_y() + b.get_height() / 2,
                f"{v}  ({v / tot * 100:.1f}%)", va="center", fontsize=8.6,
                fontweight="bold", color=T.hx(T.TEXT))
    ax.set_xlim(0, tot * 1.32)
    ax.set_xticks([])
    ax.tick_params(axis="y", labelsize=8.4)
    for s in ("top", "right", "bottom", "left"):
        ax.spines[s].set_visible(False)
    return _out(fig)


# ==========================================================================
# 5. Developer score chart
# ==========================================================================
def developer_scores(rows, w=6.6, h=None, limit=14, watch=90.0):
    rows = [r for r in rows if r.get("score") is not None][:limit]
    if not rows:
        return _empty(w, 3)
    rows = list(reversed(rows))               # worst at the bottom of the list -> top of chart
    h = h or max(2.2, 0.34 * len(rows) + 0.9)

    fig, ax = plt.subplots(figsize=(w, h))
    names = [r["name"] if len(r["name"]) <= 26 else r["name"][:24] + "\u2026" for r in rows]
    vals = [r["score"] for r in rows]
    cols = [T.hx(T.score_color(v)) for v in vals]
    bars = ax.barh(names, vals, height=0.62, color=cols, zorder=3)

    for b, r in zip(bars, rows):
        ax.text(b.get_width() + 1.5, b.get_y() + b.get_height() / 2,
                f"{r['score']:.2f}%  ({r['no_error']}/{r['total']})",
                va="center", fontsize=7.8, color=T.hx(T.TEXT), fontweight="bold")

    ax.axvline(watch, color=T.hx(T.TEXT_MUTED), lw=1, ls=(0, (4, 3)), zorder=2)
    # Headroom past 100% for the value label, so a 100.00% (94/96) never clips.
    ax.set_xlim(0, 158)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
    ax.tick_params(axis="both", labelsize=8.2)
    ax.grid(axis="x", color=T.hx(T.GRID), lw=0.8, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    return _out(fig)


# ==========================================================================
# 6. Severity split
# ==========================================================================
def severity_bar(rows, w=3.4, h=2.6):
    rows = [r for r in rows if r.get("count", 0) > 0]
    if not rows:
        return _empty(w, h, "No defects")
    fig, ax = plt.subplots(figsize=(w, h))
    names = [r["severity"] for r in rows]
    vals = [r["count"] for r in rows]
    cols = [T.hx(T.SEVERITY_COLORS.get(n, T.TEXT_MUTED)) for n in names]
    bars = ax.bar(names, vals, width=0.52, color=cols, zorder=3)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + max(vals) * 0.04, str(v),
                ha="center", fontsize=9, fontweight="bold", color=T.hx(T.TEXT))
    ax.set_ylim(0, max(vals) * 1.25)
    ax.set_yticks([])
    ax.tick_params(axis="x", labelsize=8.6)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    return _out(fig)


# ==========================================================================
# 7. Market comparison
# ==========================================================================
def market_compare(series_by_market, w=7.4, h=3.4):
    """One line per market across a shared month axis."""
    series_by_market = {k: v for k, v in series_by_market.items() if v}
    if not series_by_market:
        return _empty(w, h)

    labels = []
    for rows in series_by_market.values():
        for r in rows:
            key = (r["year"], r["month"])
            if key not in labels:
                labels.append(key)
    labels.sort()
    xs = {k: i for i, k in enumerate(labels)}

    palette = [T.BRAND, T.BLUE, T.GREEN, T.PURPLE, T.TEAL]
    fig, ax = plt.subplots(figsize=(w, h))
    for i, (market, rows) in enumerate(series_by_market.items()):
        pts = [(xs[(r["year"], r["month"])], r["score"]) for r in rows if r.get("score") is not None]
        if not pts:
            continue
        ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", ms=5, lw=2.2,
                color=T.hx(palette[i % len(palette)]), label=market, zorder=3)

    from .metrics import MONTH_ABBR
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([f"{MONTH_ABBR[m - 1]}\n{y}" for y, m in labels], fontsize=8.2)
    ax.set_ylabel("Quality Score (%)", fontsize=8.6)
    ax.yaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(axis="y", color=T.hx(T.GRID), lw=0.8, zorder=0)
    ax.legend(fontsize=8.4, frameon=False, ncol=len(series_by_market), loc="lower left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    return _out(fig)


# ==========================================================================
# 8. Flat icons — drawn, not fetched, so nothing depends on a font or the web
# ==========================================================================
_ICON_CACHE = {}


def _canvas(size):
    """
    A square figure whose axes fill it edge to edge, in a fixed 0-100 space.

    Icons must NOT go through `bbox_inches="tight"`: that crops each glyph to
    its own ink, so a wide glyph and a tall one come back at different scales
    and the row of KPI tiles ends up visually ragged.
    """
    fig = plt.figure(figsize=(size, size))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


def _fixed_out(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=220, transparent=True)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def icon(name, color, size=0.62, bg=True):
    """A flat glyph on a soft tinted disc, returned as PNG bytes. Cached."""
    key = (name, color, round(size, 3), bg)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    fig, ax = _canvas(size)
    c = T.hx(color)
    if bg:
        ax.add_patch(Circle((50, 50), 47, color=c, alpha=0.14, zorder=0))
    _draw_glyph(ax, name, c)
    png = _fixed_out(fig)
    _ICON_CACHE[key] = png
    return png


def _draw_glyph(ax, name, c):
    z = 3
    if name == "clipboard":
        ax.add_patch(FancyBboxPatch((32, 20), 36, 52, boxstyle="round,pad=0,rounding_size=5",
                                    facecolor=c, edgecolor="none", zorder=z))
        ax.add_patch(FancyBboxPatch((41, 66), 18, 11, boxstyle="round,pad=0,rounding_size=3",
                                    facecolor=c, edgecolor="none", zorder=z + 2))
        ax.add_patch(Rectangle((41, 64), 18, 6, facecolor="white", edgecolor="none", zorder=z + 1))
        for y in (55, 45, 35):
            ax.plot([40, 60], [y, y], color="white", lw=3.6,
                    solid_capstyle="round", zorder=z + 1)
    elif name == "check":
        ax.add_patch(Circle((50, 50), 31, facecolor=c, edgecolor="none", zorder=z))
        ax.plot([36, 46, 66], [51, 40, 63], color="white", lw=7,
                solid_capstyle="round", solid_joinstyle="round", zorder=z + 1)
    elif name == "bug":
        # Kept deliberately simple: at 26px on a KPI tile, thin radiating legs
        # blur into a starburst, so the shape carries the meaning instead.
        for sx in (-1, 1):
            for y0, y1 in ((58, 64), (46, 44)):
                ax.plot([50 + sx * 15, 50 + sx * 27], [y0, y1], color=c, lw=4.5,
                        solid_capstyle="round", zorder=z - 1)
        ax.add_patch(Ellipse((50, 42), 40, 50, facecolor=c, edgecolor="none", zorder=z))
        ax.add_patch(Circle((50, 72), 13, facecolor=c, edgecolor="none", zorder=z))
        ax.plot([50, 50], [24, 58], color="white", lw=3, zorder=z + 1)
        for sx in (-1, 1):
            ax.plot([50 + sx * 6, 50 + sx * 16], [80, 90], color=c, lw=3.4,
                    solid_capstyle="round", zorder=z)
    elif name == "building":
        ax.add_patch(Rectangle((30, 18), 40, 62, facecolor=c, edgecolor="none", zorder=z))
        for row in range(4):
            for col in range(3):
                ax.add_patch(Rectangle((36 + col * 11, 28 + row * 13), 7, 8,
                                       facecolor="white", edgecolor="none", zorder=z + 1))
    elif name == "globe":
        ax.add_patch(Circle((50, 50), 31, facecolor=c, edgecolor="none", zorder=z))
        ax.plot([19, 81], [50, 50], color="white", lw=3, zorder=z + 1)
        ax.plot([24, 76], [64, 64], color="white", lw=2.4, zorder=z + 1)
        ax.plot([24, 76], [36, 36], color="white", lw=2.4, zorder=z + 1)
        ts = _lin(-math.pi / 2, math.pi / 2, 60)
        for k in (0.42, 1.0):
            xs = [50 + 31 * k * math.cos(t) for t in ts]
            ys = [50 + 31 * math.sin(t) for t in ts]
            ax.plot(xs, ys, color="white", lw=2.4, zorder=z + 1)
            ax.plot([100 - x for x in xs], ys, color="white", lw=2.4, zorder=z + 1)
    elif name == "people":
        ax.add_patch(Circle((37, 62), 12, facecolor=c, edgecolor="none", zorder=z))
        ax.add_patch(Circle((66, 64), 9.5, facecolor=c, edgecolor="none", alpha=0.72, zorder=z))
        ax.add_patch(FancyBboxPatch((20, 24), 34, 26, boxstyle="round,pad=0,rounding_size=11",
                                    facecolor=c, edgecolor="none", zorder=z))
        ax.add_patch(FancyBboxPatch((54, 26), 28, 22, boxstyle="round,pad=0,rounding_size=10",
                                    facecolor=c, edgecolor="none", alpha=0.72, zorder=z))
    elif name == "medal":
        ax.add_patch(Polygon([[34, 88], [46, 88], [56, 56], [42, 56]],
                             facecolor=c, alpha=0.45, zorder=z - 1))
        ax.add_patch(Polygon([[66, 88], [54, 88], [44, 56], [58, 56]],
                             facecolor=c, alpha=0.45, zorder=z - 1))
        ax.add_patch(Circle((50, 38), 24, facecolor=c, edgecolor="none", zorder=z))
        ax.add_patch(Circle((50, 38), 14, facecolor="white", edgecolor="none",
                            alpha=0.42, zorder=z + 1))
    elif name == "target":
        ax.add_patch(Circle((50, 50), 32, facecolor=c, edgecolor="none", zorder=z))
        ax.add_patch(Circle((50, 50), 23, facecolor="white", edgecolor="none", zorder=z + 1))
        ax.add_patch(Circle((50, 50), 14, facecolor=c, edgecolor="none", zorder=z + 2))
        ax.add_patch(Circle((50, 50), 5.5, facecolor="white", edgecolor="none", zorder=z + 3))
    elif name == "shield":
        ax.add_patch(Polygon([[50, 84], [76, 71], [76, 40], [50, 18], [24, 40], [24, 71]],
                             facecolor=c, edgecolor="none", zorder=z))
        ax.plot([38, 47, 63], [52, 42, 62], color="white", lw=5.5,
                solid_capstyle="round", solid_joinstyle="round", zorder=z + 1)
    elif name == "chart":
        for i, hgt in enumerate((24, 40, 56)):
            ax.add_patch(FancyBboxPatch((28 + i * 16, 22), 11, hgt,
                                        boxstyle="round,pad=0,rounding_size=3",
                                        facecolor=c, edgecolor="none",
                                        alpha=0.55 + i * 0.22, zorder=z))
    elif name == "up":
        ax.add_patch(Polygon([[50, 82], [72, 54], [59, 54], [59, 22], [41, 22], [41, 54], [28, 54]],
                             facecolor=c, edgecolor="none", zorder=z))
    elif name == "down":
        ax.add_patch(Polygon([[50, 18], [28, 46], [41, 46], [41, 78], [59, 78], [59, 46], [72, 46]],
                             facecolor=c, edgecolor="none", zorder=z))
    elif name == "calendar":
        ax.add_patch(FancyBboxPatch((24, 22), 52, 50, boxstyle="round,pad=0,rounding_size=6",
                                    facecolor="none", edgecolor=c, lw=5, zorder=z))
        ax.plot([24, 76], [60, 60], color=c, lw=5, zorder=z)
        for x in (38, 62):
            ax.plot([x, x], [68, 80], color=c, lw=5, solid_capstyle="round", zorder=z)
        for col in range(3):
            ax.add_patch(Rectangle((34 + col * 13, 36), 8, 8, facecolor=c,
                                   edgecolor="none", alpha=0.65, zorder=z))
    elif name == "clock":
        ax.add_patch(Circle((50, 50), 30, facecolor="none", edgecolor=c, lw=5, zorder=z))
        ax.plot([50, 50], [50, 68], color=c, lw=5, solid_capstyle="round", zorder=z)
        ax.plot([50, 64], [50, 44], color=c, lw=5, solid_capstyle="round", zorder=z)
    else:                                                   # generic dot
        ax.add_patch(Circle((50, 50), 26, facecolor=c, edgecolor="none", zorder=z))


def _lin(a, b, n):
    step = (b - a) / (n - 1)
    return [a + step * i for i in range(n)]


def rank_badge(rank, size=0.62):
    """Numbered medal: disc on top, two ribbon tails hanging beneath it."""
    key = ("rank", rank, round(size, 3))
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    col = {1: T.GOLD, 2: T.SILVER, 3: T.BRONZE}.get(rank, T.BRAND)
    fig, ax = _canvas(size)
    c = T.hx(col)
    ax.add_patch(Polygon([[36, 40], [48, 40], [44, 8], [30, 16]],
                         facecolor=c, alpha=0.5, zorder=1))
    ax.add_patch(Polygon([[64, 40], [52, 40], [56, 8], [70, 16]],
                         facecolor=c, alpha=0.5, zorder=1))
    ax.add_patch(Circle((50, 58), 30, facecolor=c, edgecolor="white", lw=3, zorder=2))
    ax.text(50, 57, str(rank), ha="center", va="center", fontsize=size * 30,
            fontweight="bold", color="white", zorder=3)
    png = _fixed_out(fig)
    _ICON_CACHE[key] = png
    return png


# ==========================================================================
# 9. Defect aging
# ==========================================================================
def aging_bar(rows, w=6.0, h=2.6):
    """
    Defect counts by age bucket. Colour deepens with age so the eye lands on
    the oldest defects first.
    """
    rows = [r for r in rows if r.get("count", 0) > 0]
    if not rows:
        return _empty(w, h, "No dated defects in this selection")
    names = [r["bucket"] for r in rows]
    vals = [r["count"] for r in rows]
    ramp = [T.GREEN, T.TEAL, T.GOLD, T.ORANGE, T.RED]
    cols = [T.hx(ramp[min(i, len(ramp) - 1)]) for i in range(len(rows))]

    fig, ax = plt.subplots(figsize=(w, h))
    bars = ax.bar(names, vals, width=0.52, color=cols, zorder=3)
    for b, r in zip(bars, rows):
        ax.text(b.get_x() + b.get_width() / 2, r["count"] + max(vals) * 0.04,
                f"{r['count']}  ({r['pct']:.2f}%)", ha="center", fontsize=8,
                fontweight="bold", color=T.hx(T.TEXT))
    ax.set_ylim(0, max(vals) * 1.28)
    ax.set_yticks([])
    ax.tick_params(axis="x", labelsize=8.4)
    ax.set_xlabel("Days between the defect being logged and the latest audit date",
                  fontsize=7.4, color=T.hx(T.TEXT_MUTED))
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    return _out(fig)


# ==========================================================================
# 10. Error-free composition — shows observations as a subset, never an extra
# ==========================================================================
def composition_pie(total, error, no_error, observation, w=3.4, h=3.0):
    """
    How the audited tasks divide: clean, observed, defective.

    Drawn as a ring rather than a stacked bar because a bar sized by value gave
    a one-task segment a sliver too thin to write in, so its count silently
    disappeared. Here every slice carries its own number — on the ring when it
    fits, led out on a line when it does not — and the legend repeats the
    figures, so no count depends on a slice being wide enough to hold text.

    Observation is a *kind* of error-free task, not a fourth bucket: the two
    error-free slices sit next to each other and their counts add up to the
    error-free total, never on top of it.
    """
    if total <= 0:
        return _empty(w, h, "No tasks")

    segs = [("No Error", no_error, T.GREEN),
            ("Observation", observation, T.TEAL),
            ("Error", error, T.RED)]
    live = [(lbl, val, col) for lbl, val, col in segs if val > 0]
    if not live:
        return _empty(w, h, "No tasks")

    # The ring keeps its own axes and the legend gets its own strip of the
    # figure, so adding a third slice never shrinks the chart to make room.
    fig = plt.figure(figsize=(w, h))
    legend_h = 0.055 * len(live) + 0.045
    ax = fig.add_axes([0.13, legend_h + 0.03, 0.74, 0.94 - legend_h])
    wedges, _ = ax.pie([v for _, v, _ in live], colors=[T.hx(c) for _, _, c in live],
                       startangle=90, counterclock=False, radius=1.0,
                       wedgeprops={"width": 0.36, "edgecolor": "white", "linewidth": 2})

    callouts = []
    for wg, (lbl, val, col) in zip(wedges, live):
        ang = math.radians((wg.theta1 + wg.theta2) / 2)
        if val / total >= 0.09:
            ax.text(math.cos(ang) * 0.82, math.sin(ang) * 0.82, f"{val:,}",
                    ha="center", va="center", fontsize=9.6, fontweight="bold",
                    color="white")
        else:
            callouts.append((ang, f"{val:,}", col))
    _lead_out(ax, callouts, 1.0, 9.0)

    ax.text(0, 0.09, f"{total:,}", ha="center", va="center",
            fontsize=19, fontweight="bold", color=T.hx(T.TEXT))
    ax.text(0, -0.17, "Total\nTasks", ha="center", va="center",
            fontsize=7.6, color=T.hx(T.TEXT_MUTED), linespacing=1.35)
    ax.set_xlim(-1.02, 1.02)
    ax.set_ylim(-1.02, 1.02)
    ax.set(aspect="equal")
    ax.axis("off")

    handles = [Rectangle((0, 0), 1, 1, color=T.hx(col)) for _, _, col in live]
    labels = [f"{lbl}   {val:,}  ({val / total * 100:.1f}%)" for lbl, val, _ in live]
    fig.legend(handles, labels, fontsize=8.0, frameon=False, ncol=1,
               loc="lower center", bbox_to_anchor=(0.5, 0.0),
               handlelength=1.0, handleheight=0.9, borderpad=0, labelspacing=0.42)
    return _out(fig, tight=False)
