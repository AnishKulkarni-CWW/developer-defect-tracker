"""
PPTX generation.

Layout language, taken from the reference dashboard so every slide reads as one
document: light canvas, white cards with a hairline border, a navy section bar
as each panel's heading, KPI tiles with a drawn icon and a big coloured number,
and charts embedded as PNGs from charts.py.

Everything is drawn with python-pptx shapes, so the client can open the deck and
edit any number, title or colour by hand.

Slide structure (each section can be switched off):
    Title -> Executive Summary
    -> per month: Quality Score | Developer Report | Error Trend | Internal vs External
    -> Quality Score Dashboard -> QA Summary -> Developer Summary
    -> Defect Category Breakdown -> Aging Analysis -> Critical Defects
    -> Key QA Recommendations -> Thank You
"""

from __future__ import annotations

import io
from datetime import datetime

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from . import charts, metrics, theme as T

SLIDE_W = 13.333
SLIDE_H = 7.5
MARGIN = 0.42
FS = metrics.fmt_score


def _rgb(h):
    h = h.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


class Kit:
    """Thin drawing helpers over python-pptx."""

    def __init__(self, prs):
        self.prs = prs
        self.blank = prs.slide_layouts[6]

    def slide(self, bg=T.PAGE_BG):
        s = self.prs.slides.add_slide(self.blank)
        f = s.background.fill
        f.solid()
        f.fore_color.rgb = _rgb(bg)
        return s

    def rect(self, s, x, y, w, h, fill=T.WHITE, line=T.BORDER, radius=0.035, line_w=0.75):
        shp = s.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
            Inches(x), Inches(y), Inches(w), Inches(h))
        if radius:
            try:
                shp.adjustments[0] = radius
            except (IndexError, ValueError):
                pass
        if fill is None:
            shp.fill.background()
        else:
            shp.fill.solid()
            shp.fill.fore_color.rgb = _rgb(fill)
        if line is None:
            shp.line.fill.background()
        else:
            shp.line.color.rgb = _rgb(line)
            shp.line.width = Pt(line_w)
        shp.shadow.inherit = False
        shp.text_frame.word_wrap = True
        return shp

    def text(self, s, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=None):
        box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = box.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = Emu(0)
        tf.margin_top = tf.margin_bottom = Emu(0)
        for i, para in enumerate(runs):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align
            if spacing:
                p.line_spacing = spacing
            for spec in para:
                r = p.add_run()
                r.text = spec.get("t", "")
                fnt = r.font
                fnt.size = Pt(spec.get("sz", 12))
                fnt.bold = spec.get("b", False)
                fnt.italic = spec.get("i", False)
                fnt.name = spec.get("f", T.FONT_BODY)
                fnt.color.rgb = _rgb(spec.get("c", T.TEXT))
        return box

    def bar(self, s, x, y, w, label, h=0.36, fill=T.NAVY, size=12.5):
        self.rect(s, x, y, w, h, fill=fill, line=None, radius=0.16)
        self.text(s, x + 0.16, y + 0.045, w - 0.32, h - 0.09,
                  [[{"t": label.upper(), "sz": size, "b": True, "c": T.WHITE, "f": T.FONT_HEAD}]],
                  align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    def image(self, s, png, x, y, w=None, h=None):
        return s.shapes.add_picture(io.BytesIO(png), Inches(x), Inches(y),
                                    Inches(w) if w else None, Inches(h) if h else None)

    def icon(self, s, name, color, x, y, size=0.44):
        self.image(s, charts.icon(name, color, size=max(size, 0.5)), x, y, size, size)

    def kpi_tile(self, s, x, y, w, h, value, label, color, icon_name=None, sub=None):
        self.rect(s, x, y, w, h)
        tx = x + 0.14
        if icon_name:
            self.icon(s, icon_name, color, x + 0.15, y + (h - 0.42) / 2, 0.42)
            tx = x + 0.68
        body = [[{"t": str(value), "sz": 19, "b": True, "c": color, "f": T.FONT_HEAD}],
                [{"t": label.upper(), "sz": 7.6, "b": True, "c": T.TEXT_MUTED}]]
        if sub:
            body.append([{"t": sub, "sz": 7.2, "c": T.TEXT_MUTED}])
        self.text(s, tx, y + 0.12, w - (tx - x) - 0.12, h - 0.24, body,
                  anchor=MSO_ANCHOR.MIDDLE, spacing=0.95)

    def table(self, s, x, y, w, headers, rows, col_w=None, row_h=0.27, header_h=0.32,
              font=9.0, head_font=9.0, cell_colors=None, max_h=None, fill_h=None,
              max_row_h=0.46):
        """
        Themed table. `cell_colors` maps (row, col) -> hex for the text colour.
        `max_h` shrinks rows to fit; `fill_h` also grows them so a short table
        does not leave a dead gap. Returns (shape, height_inches).
        """
        nrows, ncols = len(rows) + 1, len(headers)
        ndata = max(nrows - 1, 1)
        if fill_h:
            grown = (fill_h - header_h) / ndata
            if grown > row_h:
                row_h = min(grown, max_row_h)
                font = min(font * 1.18, max(font, row_h * 24))
            max_h = max_h or fill_h
        if max_h and (max_h - header_h) / ndata < row_h:
            row_h = max(0.155, (max_h - header_h) / ndata)
            font = max(6.4, min(font, row_h * 26))

        gt = s.shapes.add_table(nrows, ncols, Inches(x), Inches(y),
                                Inches(w), Inches(header_h + row_h * (nrows - 1)))
        tbl = gt.table
        tbl.first_row = True
        tbl.horz_banding = False
        if col_w:
            tot = sum(col_w)
            for j, cw in enumerate(col_w):
                tbl.columns[j].width = Emu(int(Inches(w) * cw / tot))
        tbl.rows[0].height = Inches(header_h)
        for i in range(1, nrows):
            tbl.rows[i].height = Inches(row_h)

        for j, htxt in enumerate(headers):
            self._cell(tbl.cell(0, j), str(htxt), head_font, True, T.WHITE, T.NAVY,
                       PP_ALIGN.CENTER if j else PP_ALIGN.LEFT)
        for i, row in enumerate(rows, start=1):
            bg = T.WHITE if i % 2 else T.ROW_ALT
            for j, val in enumerate(row):
                col = (cell_colors or {}).get((i - 1, j), T.TEXT)
                self._cell(tbl.cell(i, j), "" if val is None else str(val), font,
                           j == 0 or col != T.TEXT, col, bg,
                           PP_ALIGN.CENTER if j else PP_ALIGN.LEFT)
        return gt, header_h + row_h * (nrows - 1)

    @staticmethod
    def _cell(cell, text, size, bold, color, bg, align):
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(bg)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = cell.margin_right = Inches(0.07)
        cell.margin_top = cell.margin_bottom = Emu(0)
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = align
        r = p.add_run()
        r.text = text
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.name = T.FONT_BODY
        r.font.color.rgb = _rgb(color)

    def head(self, s, eyebrow, title):
        self.rect(s, 0, 0, SLIDE_W, 0.90, fill=T.NAVY, line=None, radius=0)
        self.text(s, MARGIN, 0.12, SLIDE_W - MARGIN * 2, 0.24,
                  [[{"t": eyebrow.upper(), "sz": 8.4, "b": True, "c": "8FB3E8"}]])
        self.text(s, MARGIN, 0.36, SLIDE_W - MARGIN * 2, 0.42,
                  [[{"t": title, "sz": 17.5, "b": True, "c": T.WHITE, "f": T.FONT_HEAD}]])

    def footer(self, s, left, right=""):
        self.text(s, MARGIN, SLIDE_H - 0.34, SLIDE_W - MARGIN * 2, 0.24,
                  [[{"t": left, "sz": 7.6, "c": T.TEXT_MUTED}]])
        if right:
            self.text(s, SLIDE_W - MARGIN - 3.2, SLIDE_H - 0.34, 3.2, 0.24,
                      [[{"t": right, "sz": 7.6, "c": T.TEXT_MUTED}]], align=PP_ALIGN.RIGHT)


# ==========================================================================
# Slide plan
#
#   Title
#   [per month]  Month divider -> Quality Score -> Developer Report -> Defects
#   Period divider
#   QA Summary -> Developer Summary -> Defect Categories
#   [optional]   Aging -> Critical defects
#   Recommendations
#   Quality Score Dashboard      <- the combined view, last before Thank You
#   Thank You
#
# One idea per slide, at most two visual elements on it. The earlier version
# packed four panels onto a slide and the numbers fought each other; the
# client's own decks are readable precisely because each slide answers a
# single question.
# ==========================================================================
NOTE_RULE = ("Error Free = No Error + Observation   \u2022   "
             "Total Tasks = Error + Error Free   \u2022   "
             "Quality Score = Error Free \u00f7 Total Tasks")


def _brand(org, market):
    """
    "Acme India", or just "India" when no brand is set.

    The report is brand-neutral: whoever runs it types their own organisation
    on the Settings page, and an empty one must not leave a stray space or a
    placeholder name on the cover.
    """
    org = (org or "").strip()
    return f"{org} {market}".strip() if org else market


def _dev_totals(devs):
    """The column sums that belong under any per-developer table."""
    agg = {k: sum(d[k] for d in devs)
           for k in ("error", "no_error", "observation", "error_free", "total")}
    score = metrics.compute(agg["error"], agg["no_error"], agg["observation"])["score"]
    return ("Total", agg["error"], agg["no_error"], agg["observation"],
            agg["error_free"], agg["total"], FS(score)), score


def build_deck(sel, options):
    """Render a Selection to .pptx bytes."""
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    k = Kit(prs)

    o = options or {}
    market = o.get("market_label") or sel.market
    org = (o.get("org") or "").strip()
    rows = metrics.monthly_series(sel)
    tot = metrics.totals(sel)
    period = tot["period_label"]
    foot = f"{_brand(org, market)} \u2013 QA Quality Report \u2022 {period}"

    _title_slide(k, org, market, period, tot, o)

    monthly = o.get("include_monthly", True) and bool(rows)
    if monthly:
        for i, r in enumerate(rows, 1):
            _month_divider(k, r, market, org, i, len(rows))
            _month_score(k, sel, r, market, foot)
            _month_developers(k, sel, r, market, foot)
            _month_defects(k, sel, r, market, foot)

    # One month selected: the consolidated section would restate the monthly
    # pages line for line, because consolidating a single month is that month.
    # The monthly pages and the closing dashboard carry everything, so the
    # repetition is dropped rather than printed twice.
    # It is only dropped when the monthly pages are actually there — with the
    # monthly section switched off, the consolidated view is the whole report.
    consolidated = not (monthly and len(rows) == 1)

    if consolidated:
        _period_divider(k, tot, market, org, period, len(rows))
        if o.get("include_summary", True):
            _qa_summary(k, sel, tot, rows, market, org, period, foot)
        if o.get("include_developer", True):
            _developer_summary(k, sel, market, org, period, foot)
        if o.get("include_category", True):
            _category_breakdown(k, sel, tot, market, org, period, foot)
        if o.get("include_aging", False):
            _aging(k, sel, market, org, period, foot)
        if o.get("include_critical", False):
            _critical(k, sel, market, org, period, foot)
        if o.get("include_recommendations", True):
            _recommendations(k, sel, market, org, period, foot, o.get("notes"))
    if o.get("include_dashboard", True):
        _dashboard(k, sel, tot, rows, market, period, foot)

    _closing(k, org, market, period, tot)

    out = io.BytesIO()
    prs.save(out)
    out.seek(0)
    return out.getvalue()


# --------------------------------------------------------------------------
# dividers
# --------------------------------------------------------------------------
def _title_slide(k, org, market, period, tot, o):
    s = k.slide(bg=T.NAVY)
    k.rect(s, 0, 4.15, SLIDE_W, SLIDE_H - 4.15, fill=T.NAVY_DK, line=None, radius=0)
    k.text(s, 1.0, 1.65, 11.3, 0.5,
           [[{"t": _brand(org, market).upper(), "sz": 15, "b": True, "c": "8FB3E8",
              "f": T.FONT_HEAD}]])
    k.text(s, 1.0, 2.15, 11.3, 1.2,
           [[{"t": "Quality Assurance Report", "sz": 42, "b": True, "c": T.WHITE,
              "f": T.FONT_HEAD}]])
    k.rect(s, 1.0, 3.55, 1.7, 0.055, fill=T.BLUE, line=None, radius=0)
    k.text(s, 1.0, 3.80, 11.3, 0.4, [[{"t": period, "sz": 18, "c": "C6D4EC"}]])

    tiles = [(f"{tot['total_tasks']:,}", "Tasks Audited"),
             (FS(tot["score"]), "Quality Score"),
             (f"{tot['error_tasks']:,}", "Total Defects"),
             (f"{tot['developers']}", "Developers")]
    tw, gap = 2.42, 0.28
    for i, (v, lbl) in enumerate(tiles):
        x = 1.0 + i * (tw + gap)
        k.rect(s, x, 4.62, tw, 1.02, fill="0B265E", line="1E4488", radius=0.1)
        k.text(s, x + 0.18, 4.74, tw - 0.36, 0.78,
               [[{"t": v, "sz": 20, "b": True, "c": T.WHITE, "f": T.FONT_HEAD}],
                [{"t": lbl.upper(), "sz": 7.8, "b": True, "c": "9FBAE4"}]],
               anchor=MSO_ANCHOR.MIDDLE, spacing=1.0)
    by = o.get("prepared_by") or ""
    stamp = datetime.now().strftime("%d %b %Y")
    k.text(s, 1.0, 6.12, 11.3, 0.3,
           [[{"t": f"Prepared by {by}  \u2022  {stamp}" if by else f"Generated {stamp}",
              "sz": 10, "c": "7E9AC8"}]])


def _month_divider(k, r, market, org, idx, total):
    """A full-bleed marker so you always know which month you are looking at."""
    s = k.slide(bg=T.NAVY)
    k.rect(s, 0, 0, 0.22, SLIDE_H, fill=T.BLUE, line=None, radius=0)
    k.text(s, 1.2, 2.35, 11.0, 0.4,
           [[{"t": f"{org.upper()} {market.upper()}  \u2022  MONTH {idx} OF {total}",
              "sz": 13, "b": True, "c": "8FB3E8", "f": T.FONT_HEAD}]])
    k.text(s, 1.2, 2.85, 11.0, 1.1,
           [[{"t": r["month_name"].upper(), "sz": 58, "b": True, "c": T.WHITE,
              "f": T.FONT_HEAD}]])
    k.text(s, 1.2, 4.00, 11.0, 0.7,
           [[{"t": str(r["year"]), "sz": 34, "b": True, "c": T.BLUE, "f": T.FONT_HEAD}]])
    k.rect(s, 1.2, 4.85, 1.7, 0.05, fill=T.BLUE, line=None, radius=0)
    k.text(s, 1.2, 5.10, 11.0, 0.4,
           [[{"t": f"{r['total']:,} tasks audited   \u2022   {r['error']} defect(s)   "
                  f"\u2022   {FS(r['score'])} quality score", "sz": 14, "c": "C6D4EC"}]])


def _period_divider(k, tot, market, org, period, n_months):
    s = k.slide(bg=T.NAVY)
    k.rect(s, 0, 0, 0.22, SLIDE_H, fill=T.GREEN, line=None, radius=0)
    k.text(s, 1.2, 2.45, 11.0, 0.4,
           [[{"t": f"{org.upper()} {market.upper()}", "sz": 13, "b": True, "c": "8FB3E8",
              "f": T.FONT_HEAD}]])
    k.text(s, 1.2, 2.95, 11.0, 1.0,
           [[{"t": "CONSOLIDATED SUMMARY", "sz": 44, "b": True, "c": T.WHITE,
              "f": T.FONT_HEAD}]])
    k.text(s, 1.2, 4.05, 11.0, 0.6,
           [[{"t": period, "sz": 26, "b": True, "c": T.BLUE, "f": T.FONT_HEAD}]])
    k.rect(s, 1.2, 4.85, 1.7, 0.05, fill=T.GREEN, line=None, radius=0)
    k.text(s, 1.2, 5.10, 11.0, 0.4,
           [[{"t": f"All {n_months} month(s) combined   \u2022   {tot['total_tasks']:,} tasks   "
                  f"\u2022   {FS(tot['score'])} overall quality score",
              "sz": 14, "c": "C6D4EC"}]])


# --------------------------------------------------------------------------
# monthly slides — one question each
# --------------------------------------------------------------------------
def _kpi_strip(k, s, tiles, y=1.10, h=1.05):
    gap = 0.16
    tw = (SLIDE_W - MARGIN * 2 - gap * (len(tiles) - 1)) / len(tiles)
    for i, (v, lbl, col, ic) in enumerate(tiles):
        x = MARGIN + i * (tw + gap)
        k.rect(s, x, y, tw, h)
        k.icon(s, ic, col, x + (tw - 0.44) / 2, y + 0.12, 0.44)
        k.text(s, x + 0.06, y + 0.60, tw - 0.12, 0.28,
               [[{"t": v, "sz": 17, "b": True, "c": col, "f": T.FONT_HEAD}]],
               align=PP_ALIGN.CENTER)
        k.text(s, x + 0.06, y + 0.87, tw - 0.12, 0.16,
               [[{"t": lbl.upper(), "sz": 6.6, "b": True, "c": T.TEXT_MUTED}]],
               align=PP_ALIGN.CENTER)
    return y + h


def _month_score(k, sel, r, market, foot):
    label = f"{r['month_name']} {r['year']}"
    s = k.slide()
    k.head(s, f"{market} \u2013 {label}", "Quality Score")
    _kpi_strip(k, s, [
        (f"{r['total']:,}", "Total Tasks", T.BLUE, "clipboard"),
        (f"{r['error_free']:,}", "Error Free Tasks", T.GREEN, "check"),
        (f"{r['error']:,}", "Errors", T.RED, "bug"),
        (f"{r['observation']:,}", "Observations", T.ORANGE, "clipboard"),
        (FS(r["score"]), "Quality Score", T.score_color(r["score"]), "target"),
    ])

    py, ph = 2.42, 4.40
    lw = 6.4
    k.rect(s, MARGIN, py, lw, ph)
    k.bar(s, MARGIN + 0.14, py + 0.14, lw - 0.28, f"Quality Score \u2013 {label}",
          h=0.32, size=10.5)
    body = [("Error", f"{r['error']:,}"),
            ("No Error", f"{r['no_error']:,}"),
            ("Observation", f"{r['observation']:,}"),
            ("Error-Free Tasks", f"{r['error_free']:,}"),
            ("Total Tasks", f"{r['total']:,}"),
            ("Quality Score", FS(r["score"]))]
    k.table(s, MARGIN + 0.20, py + 0.62, lw - 0.40, ["Measure", "Value"], body,
            col_w=[3.0, 1.4], row_h=0.46, font=13, head_font=11,
            cell_colors={(3, 0): T.GREEN, (3, 1): T.GREEN,
                         (5, 0): T.NAVY, (5, 1): T.score_color(r["score"])},
            fill_h=ph - 1.02, max_row_h=0.58)
    k.text(s, MARGIN + 0.20, py + ph - 0.34, lw - 0.40, 0.26,
           [[{"t": "Error-Free = No Error + Observation   \u2022   "
                  "Score = Error-Free \u00f7 Total Tasks", "sz": 8.4, "i": True,
              "c": T.TEXT_MUTED}]])

    rx = MARGIN + lw + 0.18
    rw = SLIDE_W - MARGIN - rx
    k.rect(s, rx, py, rw, ph)
    k.bar(s, rx + 0.14, py + 0.14, rw - 0.28, "Task Composition", h=0.32, size=10.5)
    # Sized against the panel, not a guessed constant: a chart that overruns
    # its card is worse than a slightly smaller one.
    cw = min(rw - 0.6, 3.5)
    iy, ch = py + 0.58, cw * 0.92
    ty = iy + ch + 0.12
    k.image(s, charts.composition_pie(r["total"], r["error"], r["no_error"],
                                      r["observation"], w=cw, h=ch),
            rx + (rw - cw) / 2, iy, cw)
    k.text(s, rx + 0.30, ty, rw - 0.60, max(0.6, ph - (ty - py) - 0.12),
           [[{"t": "Reading this chart", "sz": 12, "b": True, "c": T.NAVY}],
            [{"t": f"{r['error_free']:,} of {r['total']:,} tasks were error free. "
                   f"{r['observation']:,} of those carried an observation \u2014 they are "
                   "counted inside the error-free slices, never added on top.",
              "sz": 10.5, "c": T.TEXT}],
            [{"t": " ", "sz": 6}],
            [{"t": f"{r['error']:,} task(s) contained a defect.", "sz": 10.5, "c": T.TEXT}]],
           spacing=1.25)
    if r["source"] == "summary":
        k.text(s, rx + 0.30, py + ph - 0.34, rw - 0.60, 0.26,
               [[{"t": "Figures imported from a previously issued deck.", "sz": 8,
                  "i": True, "c": T.TEXT_MUTED}]])
    k.footer(s, foot, label)


def _month_developers(k, sel, r, market, foot):
    """One full-width table. Nothing else competing for attention."""
    label = f"{r['month_name']} {r['year']}"
    devs = metrics.developer_table(sel, month=(r["year"], r["month"]))
    s = k.slide()
    k.head(s, f"{market} \u2013 {label}", "Developer Report")
    py, ph = 1.10, 5.72
    w = SLIDE_W - MARGIN * 2
    k.rect(s, MARGIN, py, w, ph)
    k.bar(s, MARGIN + 0.14, py + 0.14, w - 0.28, f"Developer Report \u2013 {label}",
          h=0.32, size=10.5)
    if devs:
        body = [(d["name"], d["error"], d["no_error"], d["observation"], d["error_free"],
                 d["total"], FS(d["score"])) for d in devs]
        colors = {(i, 6): T.score_color(d["score"]) for i, d in enumerate(devs)}
        # The column sums, so the table adds up on the page instead of asking
        # the reader to do it.
        total_row, total_score = _dev_totals(devs)
        body.append(total_row)
        colors[(len(devs), 0)] = T.NAVY
        colors[(len(devs), 6)] = T.score_color(total_score)
        k.table(s, MARGIN + 0.20, py + 0.64, w - 0.40,
                ["Developer Name", "Error", "No Error", "Observation", "Error Free",
                 "Total Tasks", "Quality Score"], body,
                col_w=[3.2, 1.0, 1.1, 1.3, 1.2, 1.1, 1.5],
                row_h=0.30, font=11, head_font=10.5, cell_colors=colors,
                fill_h=ph - 1.24, max_row_h=0.44)
        k.text(s, MARGIN + 0.20, py + ph - 0.38, w - 0.40, 0.30,
               [[{"t": NOTE_RULE, "sz": 9, "i": True, "c": T.TEXT_MUTED}]])
    else:
        k.text(s, MARGIN + 0.4, py + 1.4, w - 0.8, 0.4,
               [[{"t": "No developer detail stored for this month.", "sz": 12,
                  "c": T.TEXT_MUTED}]])
    k.footer(s, foot, label)


def _month_defects(k, sel, r, market, foot):
    label = f"{r['month_name']} {r['year']}"
    cats = metrics.category_table(sel, month=(r["year"], r["month"]))
    ti = sum(c["internal"] for c in cats)
    te = sum(c["external"] for c in cats)
    s = k.slide()
    k.head(s, f"{market} \u2013 {label}", "Defect Analysis")

    py, ph = 1.10, 5.72
    lw = 8.1
    k.rect(s, MARGIN, py, lw, ph)
    k.bar(s, MARGIN + 0.14, py + 0.14, lw - 0.28,
          f"Defects by Link Type \u2013 {label}", h=0.32, size=10.5)
    if cats:
        body = [(c["category"], c["internal"], c["external"], c["total"], f"{c['pct']:.2f}%")
                for c in cats] + [("Total", ti, te, ti + te, "100.00%")]
        colors = {(i, 0): T.CATEGORY_COLORS.get(c["category"], T.TEXT)
                  for i, c in enumerate(cats)}
        colors[(len(cats), 0)] = T.NAVY
        k.table(s, MARGIN + 0.20, py + 0.64, lw - 0.40,
                ["Error Type", "Test Link", "Live Link", "Total", "% of Total"], body,
                col_w=[2.6, 1.5, 1.5, 0.9, 1.1], row_h=0.34, font=11.5, head_font=10,
                cell_colors=colors, fill_h=ph - 0.86, max_row_h=0.46)
    else:
        k.icon(s, "check", T.GREEN, MARGIN + (lw - 0.8) / 2, py + 1.7, 0.8)
        k.text(s, MARGIN, py + 2.7, lw, 0.6,
               [[{"t": "Zero defects this month.", "sz": 20, "b": True, "c": T.GREEN,
                  "f": T.FONT_HEAD}]], align=PP_ALIGN.CENTER)

    rx = MARGIN + lw + 0.18
    rw = SLIDE_W - MARGIN - rx
    k.rect(s, rx, py, rw, ph)
    k.bar(s, rx + 0.14, py + 0.14, rw - 0.28, "Category Share", h=0.32, size=10.5)
    if cats:
        dh = min(3.4, rw - 0.34)
        iy = py + 0.58
        ty = iy + dh + 0.12
        k.image(s, charts.category_donut(cats[:6], w=dh, h=dh, centre_total=r["error"]),
                rx + (rw - dh) / 2, iy, dh)
        k.text(s, rx + 0.24, ty, rw - 0.48, max(0.7, ph - (ty - py) - 0.12),
               [[{"t": f"{ti} on test links", "sz": 12.5, "b": True, "c": T.BRAND}],
                [{"t": "Caught internally, before the page went live.",
                  "sz": 10, "c": T.TEXT}],
                [{"t": " ", "sz": 7}],
                [{"t": f"{te} on live links", "sz": 12.5, "b": True, "c": T.BLUE}],
                [{"t": "Also caught internally by QA \u2014 found after the page "
                       "went live, not reported by the client.",
                  "sz": 10, "c": T.TEXT}]], spacing=1.2)
    k.footer(s, foot, label)


# --------------------------------------------------------------------------
# consolidated slides
# --------------------------------------------------------------------------
def _qa_summary(k, sel, tot, rows, market, org, period, foot):
    s = k.slide()
    k.head(s, _brand(org, market), f"QA Summary \u2013 {period}")
    kpi_rows = [("Total Tasks Audited", f"{tot['total_tasks']:,}"),
                ("Error Tasks (defects)", f"{tot['error_tasks']:,}"),
                ("No Error Tasks", f"{tot['no_error']:,}"),
                ("Observations", f"{tot['observations']:,}"),
                ("Error-Free Tasks", f"{tot['error_free']:,}"),
                ("Defects on Test Links", f"{tot['internal']} ({tot['internal_pct']:.2f}%)"),
                ("Defects on Live Links", f"{tot['external']} ({tot['external_pct']:.2f}%)"),
                ("Developers Audited", f"{tot['developers']}"),
                (f"Developers Below {metrics.BAND_WATCH:.0f}%", f"{tot['below_target']}"),
                ("Months Covered", f"{tot['months']}"),
                ("Overall Quality Score", FS(tot["score"])),
                ("Average Monthly Score", FS(tot["avg_monthly_score"]))]
    lw, py, ph = 6.4, 1.10, 5.72
    k.rect(s, MARGIN, py, lw, ph)
    k.bar(s, MARGIN + 0.14, py + 0.14, lw - 0.28, "Key Performance Indicators",
          h=0.32, size=10.5)
    k.table(s, MARGIN + 0.20, py + 0.64, lw - 0.40, ["KPI", "Value"], kpi_rows,
            col_w=[3.2, 1.5], row_h=0.36, font=11.5, head_font=10.5,
            cell_colors={(4, 0): T.GREEN, (4, 1): T.GREEN,
                         (10, 0): T.NAVY, (10, 1): T.score_color(tot["score"]),
                         (11, 1): T.BLUE},
            fill_h=ph - 0.86, max_row_h=0.44)

    rx = MARGIN + lw + 0.18
    rw = SLIDE_W - MARGIN - rx
    k.rect(s, rx, py, rw, ph)
    k.bar(s, rx + 0.14, py + 0.14, rw - 0.28, "Quality Score by Month", h=0.32, size=10.5)
    k.image(s, charts.quality_trend(rows, w=rw - 0.4, h=2.6),
            rx + 0.20, py + 0.66, rw - 0.4)
    mb = [(r["label"], r["total"], r["error"], r["error_free"], FS(r["score"]))
          for r in rows]
    colors = {(i, 4): T.score_color(r["score"]) for i, r in enumerate(rows)}
    k.table(s, rx + 0.20, py + 3.42, rw - 0.4,
            ["Month", "Tasks", "Defects", "Error Free", "Score"], mb,
            col_w=[1.5, 0.9, 0.9, 1.1, 1.2], row_h=0.32, font=10.5, head_font=10,
            cell_colors=colors, max_h=ph - 3.60)
    k.footer(s, foot, "QA summary")


def _developer_summary(k, sel, market, org, period, foot):
    devs = metrics.developer_table(sel)
    pages = [devs[i:i + 14] for i in range(0, len(devs), 14)] or [[]]
    for page, chunk in enumerate(pages, start=1):
        if not chunk:
            continue
        s = k.slide()
        suffix = f" ({page} of {len(pages)})" if len(pages) > 1 else ""
        k.head(s, _brand(org, market), f"Developer Summary \u2013 {period}{suffix}")
        py, ph = 1.10, 5.72
        w = SLIDE_W - MARGIN * 2
        k.rect(s, MARGIN, py, w, ph)
        k.bar(s, MARGIN + 0.14, py + 0.14, w - 0.28, "Per-Developer Performance",
              h=0.32, size=10.5)
        body = [(d["name"], d["error"], d["no_error"], d["observation"], d["error_free"],
                 d["total"], FS(d["score"])) for d in chunk]
        colors = {(i, 6): T.score_color(d["score"]) for i, d in enumerate(chunk)}
        # Only the final page carries the sums: a running subtotal halfway
        # through an alphabetical list is a number nobody asked for.
        if page == len(pages):
            total_row, total_score = _dev_totals(devs)
            body.append(total_row)
            colors[(len(chunk), 0)] = T.NAVY
            colors[(len(chunk), 6)] = T.score_color(total_score)
        k.table(s, MARGIN + 0.20, py + 0.64, w - 0.40,
                ["Developer Name", "Error", "No Error", "Observation", "Error Free",
                 "Total Tasks", "Quality Score"], body,
                col_w=[3.2, 1.0, 1.1, 1.3, 1.2, 1.1, 1.5],
                row_h=0.32, font=11, head_font=10.5, cell_colors=colors,
                fill_h=ph - 1.24, max_row_h=0.44)
        k.text(s, MARGIN + 0.20, py + ph - 0.38, w - 0.40, 0.30,
               [[{"t": NOTE_RULE, "sz": 9, "i": True, "c": T.TEXT_MUTED}]])
        k.footer(s, foot, "Developer summary")


def _category_breakdown(k, sel, tot, market, org, period, foot):
    cats = metrics.category_table(sel)
    s = k.slide()
    k.head(s, _brand(org, market), f"Defect Category Breakdown \u2013 {period}")
    py, ph = 1.10, 5.72
    lw = 8.1
    ti = sum(c["internal"] for c in cats)
    te = sum(c["external"] for c in cats)
    k.rect(s, MARGIN, py, lw, ph)
    k.bar(s, MARGIN + 0.14, py + 0.14, lw - 0.28, "Defects by Category and Link Type",
          h=0.32, size=10.5)
    if cats:
        body = [(c["category"], c["internal"], c["external"], c["total"], f"{c['pct']:.2f}%")
                for c in cats] + [("Grand Total", ti, te, ti + te, "100.00%")]
        colors = {(i, 0): T.CATEGORY_COLORS.get(c["category"], T.TEXT)
                  for i, c in enumerate(cats)}
        colors[(len(cats), 0)] = T.NAVY
        k.table(s, MARGIN + 0.20, py + 0.64, lw - 0.40,
                ["Defect Category", "Test Link", "Live Link", "Total Defects",
                 "% of Total"], body,
                col_w=[2.6, 1.5, 1.5, 1.1, 1.1], row_h=0.34, font=11.5, head_font=10,
                cell_colors=colors, fill_h=ph - 0.86, max_row_h=0.46)
    else:
        k.text(s, MARGIN + 0.4, py + 1.5, lw - 0.8, 0.5,
               [[{"t": "Zero defects across this period.", "sz": 16, "b": True,
                  "c": T.GREEN}]])

    rx = MARGIN + lw + 0.18
    rw = SLIDE_W - MARGIN - rx
    k.rect(s, rx, py, rw, ph)
    k.bar(s, rx + 0.14, py + 0.14, rw - 0.28, "Category Share", h=0.32, size=10.5)
    if cats:
        bar_h, chart_h = 0.30, 1.20
        dh = min(3.3, rw - 0.34, ph - 0.58 - 0.12 - bar_h - 0.10 - chart_h - 0.10)
        iy = py + 0.58
        by = iy + dh + 0.12
        k.image(s, charts.category_donut(cats[:7], w=dh, h=dh,
                                         centre_total=tot["error_tasks"]),
                rx + (rw - dh) / 2, iy, dh)
        k.bar(s, rx + 0.14, by, rw - 0.28, "Test vs Live Links", h=bar_h, size=9.5)
        k.image(s, charts.internal_external(ti, te, w=rw - 0.5, h=chart_h),
                rx + 0.25, by + bar_h + 0.10, rw - 0.5)
    k.footer(s, foot, "Defect categories")


def _aging(k, sel, market, org, period, foot):
    rows, ref = metrics.aging_table(sel)
    s = k.slide()
    k.head(s, _brand(org, market), f"Aging Analysis \u2013 {period}")
    py, ph = 1.10, 5.72
    lw = 8.1
    k.rect(s, MARGIN, py, lw, ph)
    k.bar(s, MARGIN + 0.14, py + 0.14, lw - 0.28, "Defect age distribution", h=0.32, size=10.5)
    if rows and any(r["count"] for r in rows):
        k.image(s, charts.aging_bar(rows, w=lw - 0.6, h=2.7), MARGIN + 0.30, py + 0.66, lw - 0.6)
        body = [(r["bucket"], r["count"], f"{r['pct']:.2f}%") for r in rows]
        k.table(s, MARGIN + 0.20, py + 3.60, lw - 0.40,
                ["Age Bucket", "Defects", "% of Defects"], body,
                col_w=[2.2, 1.0, 1.2], row_h=0.36, font=11, max_h=ph - 3.80)
    else:
        k.text(s, MARGIN + 0.4, py + 1.4, lw - 0.8, 0.5,
               [[{"t": "No dated defects in this selection.", "sz": 13, "c": T.TEXT_MUTED}]])
    rx = MARGIN + lw + 0.18
    rw = SLIDE_W - MARGIN - rx
    k.rect(s, rx, py, rw, ph)
    k.bar(s, rx + 0.14, py + 0.14, rw - 0.28, "How to read this", h=0.32, size=10.5)
    k.text(s, rx + 0.24, py + 0.72, rw - 0.48, 4.6,
           [[{"t": "What is measured", "sz": 12, "b": True, "c": T.NAVY}],
            [{"t": "Days between the date a defect was logged and "
                   + (f"the latest audit date in this period ({ref})." if ref
                      else "the latest audit date in this period."),
              "sz": 10, "c": T.TEXT}],
            [{"t": " ", "sz": 7}],
            [{"t": "What is NOT measured", "sz": 12, "b": True, "c": T.RED}],
            [{"t": "The audit sheets carry no closure date, so this is not time-to-fix. "
                   "Adding a 'Date Closed' column would let a true time-to-resolution "
                   "be reported here instead.", "sz": 10, "c": T.TEXT}]], spacing=1.2)
    k.footer(s, foot, "Aging analysis")


def _critical(k, sel, market, org, period, foot):
    rows, total = metrics.critical_defects(sel, limit=13)
    s = k.slide()
    k.head(s, _brand(org, market), f"Critical Defects \u2013 {period}")
    py, ph = 1.10, 5.72
    w = SLIDE_W - MARGIN * 2
    k.rect(s, MARGIN, py, w, ph)
    if rows:
        k.bar(s, MARGIN + 0.14, py + 0.14, w - 0.28,
              f"{total} defect(s) logged at Critical severity", h=0.32, size=10.5)
        body = [(r.get("date") or "\u2013", r.get("dev") or "\u2013",
                 r.get("category") or "Other", r.get("env") or "Internal",
                 (r.get("title") or "")[:66]) for r in rows]
        colors = {(i, 2): T.CATEGORY_COLORS.get(r.get("category"), T.TEXT)
                  for i, r in enumerate(rows)}
        k.table(s, MARGIN + 0.20, py + 0.64, w - 0.40,
                ["Date", "Developer", "Category", "Environment", "Task"], body,
                col_w=[1.0, 2.0, 1.6, 1.2, 5.2], row_h=0.34, font=10.5,
                cell_colors=colors, fill_h=ph - 1.00, max_row_h=0.44)
        if total > len(rows):
            k.text(s, MARGIN + 0.20, py + ph - 0.32, w - 0.40, 0.26,
                   [[{"t": f"Showing the first {len(rows)} of {total}. The full list is "
                          "in the CSV export.", "sz": 8.4, "i": True, "c": T.TEXT_MUTED}]])
    else:
        k.bar(s, MARGIN + 0.14, py + 0.14, w - 0.28, "Critical defects", h=0.32, size=10.5)
        k.icon(s, "check", T.GREEN, (SLIDE_W - 1.0) / 2, py + 1.7, 1.0)
        k.text(s, MARGIN, py + 2.9, w, 0.9,
               [[{"t": "No critical defects in this period.", "sz": 22, "b": True,
                  "c": T.GREEN, "f": T.FONT_HEAD}]], align=PP_ALIGN.CENTER)
    k.footer(s, foot, "Critical defects")


def _recommendations(k, sel, market, org, period, foot, note):
    recs = metrics.recommendations(sel)
    s = k.slide()
    k.head(s, _brand(org, market), f"Key QA Recommendations \u2013 {period}")
    py, ph = 1.10, 5.72
    w = SLIDE_W - MARGIN * 2
    k.rect(s, MARGIN, py, w, ph)
    k.bar(s, MARGIN + 0.14, py + 0.14, w - 0.28,
          "Actions suggested by the numbers in this report", h=0.32, size=10.5)
    per_col = (len(recs) + 1) // 2 or 1
    cw = (w - 0.40 - 0.24) / 2
    rh = min(1.45, (ph - 0.80) / max(per_col, 1))
    for i, rec in enumerate(recs):
        cx = MARGIN + 0.20 + (i // per_col) * (cw + 0.24)
        cy = py + 0.66 + (i % per_col) * (rh + 0.08)
        k.rect(s, cx, cy, cw, rh, fill=T.PAGE_BG, line=T.BORDER, radius=0.09)
        col = [T.BLUE, T.ORANGE, T.RED, T.PURPLE, T.TEAL, T.GREEN][i % 6]
        k.icon(s, rec["icon"], col, cx + 0.16, cy + 0.18, 0.40)
        k.text(s, cx + 0.70, cy + 0.16, cw - 0.86, 0.30,
               [[{"t": rec["title"], "sz": 12, "b": True, "c": T.NAVY, "f": T.FONT_HEAD}]])
        k.text(s, cx + 0.70, cy + 0.50, cw - 0.86, rh - 0.60,
               [[{"t": rec["text"], "sz": 9.6, "c": T.TEXT}]], spacing=1.14)
    if note:
        k.text(s, MARGIN + 0.20, py + ph - 0.44, w - 0.40, 0.4,
               [[{"t": "Note: ", "sz": 10, "b": True, "c": T.NAVY},
                 {"t": note, "sz": 10, "c": T.TEXT}]])
    k.footer(s, foot, "Recommendations")


def _dashboard(k, sel, tot, rows, market, period, foot):
    """The combined view. Placed last, immediately before Thank You."""
    s = k.slide()
    k.rect(s, 0, 0, SLIDE_W, 0.82, fill=T.NAVY, line=None, radius=0)
    k.text(s, MARGIN, 0.16, SLIDE_W - MARGIN * 2, 0.5,
           [[{"t": f"{market.upper()} QA SUMMARY REPORT  \u2022  {period.upper()}",
              "sz": 21, "b": True, "c": T.WHITE, "f": T.FONT_HEAD}]],
           align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    kpis = [(f"{tot['total_tasks']:,}", "Total Tasks Audited", T.BLUE, "clipboard", None),
            (f"{tot['error_free']:,}", "Error Free Tasks", T.GREEN, "check", None),
            (f"{tot['observations']:,}", "Observations", T.TEAL, "clipboard", "in error free"),
            (f"{tot['error_tasks']:,}", "Total Defects", T.RED, "bug", None),
            (f"{tot['internal']:,}", "Test Link Defects", T.ORANGE, "building",
             f"{tot['internal_pct']:.2f}%"),
            (f"{tot['external']:,}", "Live Link Defects", T.NAVY, "globe",
             f"{tot['external_pct']:.2f}%"),
            (f"{tot['developers']}", "Developers Audited", T.PURPLE, "people", None),
            (FS(tot["score"]), "Overall Quality Score", T.TEAL, "target", None)]
    n, gap = len(kpis), 0.11
    tw = (SLIDE_W - MARGIN * 2 - gap * (n - 1)) / n
    for i, (v, lbl, col, ic, sub) in enumerate(kpis):
        x = MARGIN + i * (tw + gap)
        k.rect(s, x, 0.98, tw, 0.92)
        k.icon(s, ic, col, x + (tw - 0.38) / 2, 1.08, 0.38)
        k.text(s, x + 0.04, 1.48, tw - 0.08, 0.34,
               [[{"t": v, "sz": 13.5, "b": True, "c": col, "f": T.FONT_HEAD}]],
               align=PP_ALIGN.CENTER)
        k.text(s, x + 0.04, 1.75, tw - 0.08, 0.14,
               [[{"t": lbl.upper() + (f" ({sub})" if sub else ""), "sz": 5.3, "b": True,
                  "c": T.TEXT_MUTED}]], align=PP_ALIGN.CENTER)

    py, ph = 2.06, 3.30
    p1w, p2w, p3w = 4.62, 3.72, 3.71
    p1x = MARGIN
    p2x = p1x + p1w + 0.14
    p3x = p2x + p2w + 0.14

    k.rect(s, p1x, py, p1w, ph)
    k.bar(s, p1x + 0.10, py + 0.10, p1w - 0.20, "Quality Score Trend (Monthly)",
          h=0.30, size=10)
    k.image(s, charts.quality_trend(rows, w=p1w - 0.32, h=2.08),
            p1x + 0.16, py + 0.50, p1w - 0.32)
    scored = [r for r in rows if r["score"] is not None]
    if scored:
        best = max(scored, key=lambda r: r["score"])
        worst = min(scored, key=lambda r: r["score"])
        band = [("up", T.GREEN, "Highest", f"{best['label']} {FS(best['score'])}"),
                ("down", T.RED, "Lowest", f"{worst['label']} {FS(worst['score'])}"),
                ("chart", T.BLUE, "Overall", FS(tot["score"])),
                ("calendar", T.PURPLE, "Avg monthly", FS(tot["avg_monthly_score"]))]
        bw = (p1w - 0.32 - 0.18) / 4
        for i, (ic, col, lbl, val) in enumerate(band):
            bx = p1x + 0.16 + i * (bw + 0.06)
            k.rect(s, bx, py + ph - 0.62, bw, 0.50, fill=T.PAGE_BG, line=T.BORDER,
                   radius=0.14)
            k.text(s, bx + 0.08, py + ph - 0.585, bw - 0.16, 0.44,
                   [[{"t": lbl, "sz": 5.8, "b": True, "c": col}],
                    [{"t": val, "sz": 7.2, "b": True, "c": T.TEXT}]],
                   anchor=MSO_ANCHOR.MIDDLE, spacing=0.95)

    k.rect(s, p2x, py, p2w, ph)
    k.bar(s, p2x + 0.10, py + 0.10, p2w - 0.20, "Defect Category Breakdown", h=0.30, size=10)
    cats = metrics.category_table(sel)
    if cats:
        k.image(s, charts.category_donut(cats[:6], w=2.10, h=2.10,
                                         centre_total=tot["error_tasks"]),
                p2x + 0.14, py + 0.46, 2.10)
        rowsc = [(c["category"], c["total"], f"{c['pct']:.2f}%") for c in cats[:7]]
        colors = {(i, 0): T.CATEGORY_COLORS.get(c["category"], T.TEXT)
                  for i, c in enumerate(cats[:7])}
        k.table(s, p2x + 2.30, py + 0.52, p2w - 2.42, ["Category", "No.", "%"], rowsc,
                col_w=[2.5, 0.8, 1.2], row_h=0.24, header_h=0.26, font=6.4,
                head_font=6.4, cell_colors=colors, max_h=ph - 0.80)
    else:
        k.text(s, p2x + 0.20, py + 1.50, p2w - 0.40, 0.4,
               [[{"t": "No defects in this selection", "sz": 10, "b": True, "c": T.GREEN}]],
               align=PP_ALIGN.CENTER)

    k.rect(s, p3x, py, p3w, ph)
    k.bar(s, p3x + 0.10, py + 0.10, p3w - 0.20, "Top Performers", h=0.30, size=10)
    top, bar_n = metrics.top_developers(sel, n=3)
    if top:
        rh = (ph - 0.76) / 3
        for i, d in enumerate(top):
            yy = py + 0.52 + i * rh
            k.image(s, charts.rank_badge(i + 1), p3x + 0.18, yy + (rh - 0.58) / 2, 0.50, 0.50)
            k.text(s, p3x + 0.78, yy + 0.04, p3w - 0.98, 0.28,
                   [[{"t": d["name"], "sz": 10.5, "b": True, "c": T.BLUE, "f": T.FONT_HEAD}]])
            k.text(s, p3x + 0.78, yy + 0.32, p3w - 0.98, 0.5,
                   [[{"t": f"{d['total']} tasks   \u2022   {d['error_free']} error free",
                      "sz": 8.2, "c": T.TEXT_MUTED}],
                    [{"t": f"{FS(d['score'])} quality score", "sz": 10, "b": True,
                      "c": T.score_color(d["score"]), "f": T.FONT_HEAD}]], spacing=1.05)
        k.text(s, p3x + 0.14, py + ph - 0.26, p3w - 0.28, 0.20,
               [[{"t": f"Ranked on score, minimum {bar_n} audited tasks to qualify.",
                  "sz": 6.4, "i": True, "c": T.TEXT_MUTED}]], align=PP_ALIGN.CENTER)

    iy = py + ph + 0.14
    k.bar(s, MARGIN, iy, SLIDE_W - MARGIN * 2, "Key Insights", h=0.30, size=10)
    ins = metrics.insights(sel)
    if ins:
        n = len(ins)
        iw = (SLIDE_W - MARGIN * 2 - 0.10 * (n - 1)) / n
        cols = [T.BLUE, T.GREEN, T.ORANGE, T.PURPLE, T.TEAL, T.RED]
        for i, item in enumerate(ins):
            x = MARGIN + i * (iw + 0.10)
            k.rect(s, x, iy + 0.36, iw, 1.06)
            col = cols[i % len(cols)]
            k.icon(s, item["icon"], col, x + (iw - 0.34) / 2, iy + 0.44, 0.34)
            k.text(s, x + 0.07, iy + 0.82, iw - 0.14, 0.56,
                   [[{"t": item["value"] + " ", "sz": 8.6, "b": True, "c": col,
                      "f": T.FONT_HEAD},
                     {"t": item["text"], "sz": 7.0, "c": T.TEXT_MUTED}]],
                   align=PP_ALIGN.CENTER, spacing=1.0)
    k.footer(s, foot, "Quality score dashboard")


def _closing(k, org, market, period, tot):
    s = k.slide(bg=T.NAVY)
    k.text(s, 1.0, 2.75, 11.3, 0.9,
           [[{"t": "Thank You", "sz": 44, "b": True, "c": T.WHITE, "f": T.FONT_HEAD}]],
           align=PP_ALIGN.CENTER)
    k.rect(s, (SLIDE_W - 1.7) / 2, 3.78, 1.7, 0.055, fill=T.BLUE, line=None, radius=0)
    k.text(s, 1.0, 4.08, 11.3, 0.4,
           [[{"t": f"{org} {market} Quality Assurance  \u2022  {period}", "sz": 14,
              "c": "C6D4EC"}]], align=PP_ALIGN.CENTER)
    if tot["score"] is not None:
        k.text(s, 1.0, 4.62, 11.3, 0.4,
               [[{"t": f"{tot['total_tasks']:,} tasks audited  \u2022  {FS(tot['score'])} "
                      "overall quality score", "sz": 11, "c": "7E9AC8"}]],
               align=PP_ALIGN.CENTER)
