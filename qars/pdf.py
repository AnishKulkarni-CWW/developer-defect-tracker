"""
PDF generation.

Deliberately NOT a LibreOffice conversion of the .pptx: that would add a heavy
external dependency, break the offline promise, and not survive being frozen
into an .exe. The PDF is drawn natively with ReportLab at the same
13.333 x 7.5in page as the slides, reusing the same palette, the same chart
PNGs and — critically — the same metrics functions, so both outputs carry
identical numbers.

Only the built-in Helvetica family is used, so no font files ship with the app.
"""

from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from . import charts, metrics, theme as T

PAGE_W = 13.333 * 72
PAGE_H = 7.5 * 72
MARGIN = 0.42 * 72
HEAD = "Helvetica-Bold"
BODY = "Helvetica"
FS = metrics.fmt_score


def _c(h):
    return HexColor("#" + h.lstrip("#"))


class Page:
    """Top-left coordinate wrapper over a ReportLab canvas."""

    def __init__(self, cv):
        self.cv = cv

    def _y(self, top, h=0.0):
        return PAGE_H - top - h

    def rect(self, x, top, w, h, fill=T.WHITE, line=T.BORDER, radius=5, line_w=0.7):
        cv = self.cv
        if fill:
            cv.setFillColor(_c(fill))
        if line:
            cv.setStrokeColor(_c(line))
            cv.setLineWidth(line_w)
        if radius:
            cv.roundRect(x, self._y(top, h), w, h, radius,
                         stroke=1 if line else 0, fill=1 if fill else 0)
        else:
            cv.rect(x, self._y(top, h), w, h, stroke=1 if line else 0, fill=1 if fill else 0)

    def text(self, x, top, txt, size=10, bold=False, color=T.TEXT, align="l", w=None):
        cv = self.cv
        cv.setFont(HEAD if bold else BODY, size)
        cv.setFillColor(_c(color))
        y = self._y(top + size * 0.86)
        if align == "c" and w:
            cv.drawCentredString(x + w / 2, y, txt)
        elif align == "r" and w:
            cv.drawRightString(x + w, y, txt)
        else:
            cv.drawString(x, y, txt)

    def para(self, x, top, w, txt, size=8, color=T.TEXT_MUTED, bold=False,
             align="l", leading=None, max_lines=6):
        font = HEAD if bold else BODY
        leading = leading or size * 1.30
        lines, cur = [], ""
        for word in str(txt).split():
            trial = (cur + " " + word).strip()
            if stringWidth(trial, font, size) <= w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
                if len(lines) >= max_lines:
                    break
        if cur and len(lines) < max_lines:
            lines.append(cur)
        for i, ln in enumerate(lines):
            self.text(x, top + i * leading, ln, size, bold, color, align, w)
        return len(lines) * leading

    def bar(self, x, top, w, label, h=26, fill=T.NAVY, size=9.5):
        self.rect(x, top, w, h, fill=fill, line=None, radius=6)
        self.text(x, top + (h - size) / 2 - 0.5, label.upper(), size, True, T.WHITE, "c", w)

    def image(self, png, x, top, w, h=None):
        img = ImageReader(io.BytesIO(png))
        iw, ih = img.getSize()
        h = h or w * ih / iw
        self.cv.drawImage(img, x, self._y(top, h), w, h, mask="auto")
        return h

    def icon(self, name, color, x, top, size=26):
        self.image(charts.icon(name, color, size=max(size / 72.0, 0.5)), x, top, size, size)

    def kpi_tile(self, x, top, w, h, value, label, color, icon_name=None, sub=None):
        self.rect(x, top, w, h)
        if icon_name:
            self.icon(icon_name, color, x + (w - 26) / 2, top + 7, 26)
            self.text(x, top + 38, str(value), 12.5, True, color, "c", w)
            lbl = label.upper() + (f" ({sub})" if sub else "")
            self.text(x, top + 54, _fit(lbl, BODY, 5.3, w - 5), 5.3, True, T.TEXT_MUTED, "c", w)
        else:
            self.text(x, top + 10, str(value), 15, True, color, "c", w)
            self.text(x, top + 32, label.upper(), 6.2, True, T.TEXT_MUTED, "c", w)

    def table(self, x, top, w, headers, rows, col_w=None, row_h=19, header_h=22,
              font=8, head_font=8, cell_colors=None, fill_h=None, max_h=None,
              max_row_h=32, pad=5):
        n = max(len(rows), 1)
        if fill_h:
            grown = (fill_h - header_h) / n
            if grown > row_h:
                row_h = min(grown, max_row_h)
                font = min(font * 1.18, max(font, row_h * 0.33))
            max_h = max_h or fill_h
        if max_h and (max_h - header_h) / n < row_h:
            row_h = max(11, (max_h - header_h) / n)
            font = max(5.5, min(font, row_h * 0.36))

        col_w = col_w or [1] * len(headers)
        tot = sum(col_w)
        widths = [w * cwi / tot for cwi in col_w]

        self.rect(x, top, w, header_h, fill=T.NAVY, line=None, radius=0)
        cx = x
        for j, htxt in enumerate(headers):
            self.text(cx + pad, top + (header_h - head_font) / 2 - 0.5,
                      _fit(str(htxt), HEAD, head_font, widths[j] - pad * 2),
                      head_font, True, T.WHITE, "c" if j else "l", widths[j] - pad * 2)
            cx += widths[j]

        for i, row in enumerate(rows):
            ry = top + header_h + i * row_h
            self.rect(x, ry, w, row_h, fill=T.WHITE if i % 2 == 0 else T.ROW_ALT,
                      line=None, radius=0)
            cx = x
            for j, val in enumerate(row):
                col = (cell_colors or {}).get((i, j), T.TEXT)
                bold = j == 0 or col != T.TEXT
                txt = _fit("" if val is None else str(val), HEAD if bold else BODY,
                           font, widths[j] - pad * 2)
                self.text(cx + pad, ry + (row_h - font) / 2 - 0.5, txt, font, bold, col,
                          "c" if j else "l", widths[j] - pad * 2)
                cx += widths[j]

        h = header_h + row_h * len(rows)
        self.cv.setStrokeColor(_c(T.BORDER))
        self.cv.setLineWidth(0.6)
        self.cv.rect(x, self._y(top, h), w, h, stroke=1, fill=0)
        return h

    def head(self, eyebrow, title):
        self.rect(0, 0, PAGE_W, 0.90 * 72, fill=T.NAVY, line=None, radius=0)
        self.text(MARGIN, 9, eyebrow.upper(), 8, True, "8FB3E8")
        self.text(MARGIN, 25, title, 17, True, T.WHITE)

    def footer(self, left, right=""):
        self.text(MARGIN, PAGE_H - 22, left, 7.2, False, T.TEXT_MUTED)
        if right:
            self.text(PAGE_W - MARGIN - 240, PAGE_H - 22, right, 7.2, False,
                      T.TEXT_MUTED, "r", 240)


def _fit(txt, font, size, maxw):
    """Truncate with an ellipsis rather than let text run past its cell."""
    if stringWidth(txt, font, size) <= maxw:
        return txt
    while txt and stringWidth(txt + "\u2026", font, size) > maxw:
        txt = txt[:-1]
    return txt + "\u2026"


# ==========================================================================
# Mirrors deck.py page for page. Both read the same metrics functions, so the
# two documents cannot drift apart numerically.
# ==========================================================================
NOTE_RULE = ("Error Free = No Error + Observation   \u2022   "
             "Total Tasks = Error + Error Free   \u2022   "
             "Quality Score = Error Free \u00f7 Total Tasks")


def _brand(org, market):
    """"Acme India", or just "India" when no brand is set — see deck._brand."""
    org = (org or "").strip()
    return f"{org} {market}".strip() if org else market


def _dev_totals(devs):
    """The column sums that belong under any per-developer table."""
    agg = {k: sum(d[k] for d in devs)
           for k in ("error", "no_error", "observation", "error_free", "total")}
    score = metrics.compute(agg["error"], agg["no_error"], agg["observation"])["score"]
    return ("Total", agg["error"], agg["no_error"], agg["observation"],
            agg["error_free"], agg["total"], FS(score)), score


def build_pdf(sel, options):
    o = options or {}
    market = o.get("market_label") or sel.market
    org = (o.get("org") or "").strip()
    rows = metrics.monthly_series(sel)
    tot = metrics.totals(sel)
    period = tot["period_label"]
    foot = f"{_brand(org, market)} \u2013 QA Quality Report \u2022 {period}"

    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    cv.setTitle(f"{_brand(org, market)} QA Report {period}")
    cv.setAuthor(o.get("prepared_by") or "QA Report Studio")
    p = Page(cv)

    def page(fn, *args, bg=T.PAGE_BG):
        _bg(p, bg)
        fn(*args)
        cv.showPage()

    page(_title_page, p, org, market, period, tot, o, bg=T.NAVY)
    monthly = o.get("include_monthly", True) and bool(rows)
    if monthly:
        for i, r in enumerate(rows, 1):
            page(_month_divider, p, r, market, org, i, len(rows), bg=T.NAVY)
            page(_month_score, p, sel, r, market, foot)
            page(_month_devs, p, sel, r, market, foot)
            page(_month_defects, p, sel, r, market, foot)

    # One month selected: consolidating a single month restates that month, so
    # the consolidated section is dropped rather than printed twice. Only when
    # the monthly pages are actually present — with them switched off, the
    # consolidated view is the entire report. Matches deck.build_deck.
    if not (monthly and len(rows) == 1):
        page(_period_divider, p, tot, market, org, period, len(rows), bg=T.NAVY)
        if o.get("include_summary", True):
            page(_qa_summary, p, sel, tot, rows, market, org, period, foot)
        if o.get("include_developer", True):
            devs = metrics.developer_table(sel)
            chunks = [devs[i:i + 14] for i in range(0, len(devs), 14)]
            for i, chunk in enumerate(chunks, 1):
                page(_developer_page, p, chunk, devs, market, org, period, foot,
                     i, len(chunks))
        if o.get("include_category", True):
            page(_category_page, p, sel, tot, market, org, period, foot)
        if o.get("include_aging", False):
            page(_aging_page, p, sel, market, org, period, foot)
        if o.get("include_critical", False):
            page(_critical_page, p, sel, market, org, period, foot)
        if o.get("include_recommendations", True):
            page(_recs_page, p, sel, market, org, period, foot, o.get("notes"))
    if o.get("include_dashboard", True):
        page(_dashboard_page, p, sel, tot, rows, market, period, foot)
    page(_closing_page, p, org, market, period, tot, bg=T.NAVY)

    cv.save()
    buf.seek(0)
    return buf.getvalue()


def _bg(p, color=T.PAGE_BG):
    p.cv.setFillColor(_c(color))
    p.cv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)


IN = 72.0


# --------------------------------------------------------------------------
def _title_page(p, org, market, period, tot, o):
    p.rect(0, 4.15 * IN, PAGE_W, PAGE_H - 4.15 * IN, fill=T.NAVY_DK, line=None, radius=0)
    x = 1.0 * IN
    p.text(x, 1.70 * IN, _brand(org, market).upper(), 14, True, "8FB3E8")
    p.text(x, 2.20 * IN, "Quality Assurance Report", 40, True, T.WHITE)
    p.rect(x, 3.55 * IN, 1.7 * IN, 4, fill=T.BLUE, line=None, radius=0)
    p.text(x, 3.80 * IN, period, 18, False, "C6D4EC")
    tiles = [(f"{tot['total_tasks']:,}", "Tasks Audited"), (FS(tot["score"]), "Quality Score"),
             (f"{tot['error_tasks']:,}", "Total Defects"), (f"{tot['developers']}", "Developers")]
    tw, gap = 2.42 * IN, 0.28 * IN
    for i, (v, lbl) in enumerate(tiles):
        tx = x + i * (tw + gap)
        p.rect(tx, 4.62 * IN, tw, 1.02 * IN, fill="0B265E", line="1E4488", radius=7)
        p.text(tx, 4.75 * IN, v, 19, True, T.WHITE, "c", tw)
        p.text(tx, 5.17 * IN, lbl.upper(), 7.4, True, "9FBAE4", "c", tw)
    by = o.get("prepared_by") or ""
    stamp = datetime.now().strftime("%d %b %Y")
    p.text(x, 6.12 * IN, f"Prepared by {by}  \u2022  {stamp}" if by else f"Generated {stamp}",
           9.5, False, "7E9AC8")


def _month_divider(p, r, market, org, idx, total):
    p.rect(0, 0, 0.22 * IN, PAGE_H, fill=T.BLUE, line=None, radius=0)
    x = 1.2 * IN
    p.text(x, 2.35 * IN, f"{_brand(org, market).upper()}  \u2022  MONTH {idx} OF {total}",
           13, True, "8FB3E8")
    p.text(x, 2.85 * IN, r["month_name"].upper(), 56, True, T.WHITE)
    p.text(x, 4.00 * IN, str(r["year"]), 34, True, T.BLUE)
    p.rect(x, 4.85 * IN, 1.7 * IN, 4, fill=T.BLUE, line=None, radius=0)
    p.text(x, 5.10 * IN, f"{r['total']:,} tasks audited   \u2022   {r['error']} defect(s)   "
                         f"\u2022   {FS(r['score'])} quality score", 14, False, "C6D4EC")


def _period_divider(p, tot, market, org, period, n_months):
    p.rect(0, 0, 0.22 * IN, PAGE_H, fill=T.GREEN, line=None, radius=0)
    x = 1.2 * IN
    p.text(x, 2.45 * IN, _brand(org, market).upper(), 13, True, "8FB3E8")
    p.text(x, 2.95 * IN, "CONSOLIDATED SUMMARY", 42, True, T.WHITE)
    p.text(x, 4.05 * IN, period, 26, True, T.BLUE)
    p.rect(x, 4.85 * IN, 1.7 * IN, 4, fill=T.GREEN, line=None, radius=0)
    p.text(x, 5.10 * IN, f"All {n_months} month(s) combined   \u2022   {tot['total_tasks']:,} "
                         f"tasks   \u2022   {FS(tot['score'])} overall quality score",
           14, False, "C6D4EC")


def _kpi_strip(p, tiles, top=1.10 * IN, h=1.05 * IN):
    gap = 0.16 * IN
    tw = (PAGE_W - MARGIN * 2 - gap * (len(tiles) - 1)) / len(tiles)
    for i, (v, lbl, col, ic) in enumerate(tiles):
        x = MARGIN + i * (tw + gap)
        p.rect(x, top, tw, h)
        p.icon(ic, col, x + (tw - 30) / 2, top + 9, 30)
        p.text(x, top + 44, v, 16, True, col, "c", tw)
        p.text(x, top + 64, lbl.upper(), 6.4, True, T.TEXT_MUTED, "c", tw)


def _month_score(p, sel, r, market, foot):
    label = f"{r['month_name']} {r['year']}"
    p.head(f"{market} \u2013 {label}", "Quality Score")
    _kpi_strip(p, [(f"{r['total']:,}", "Total Tasks", T.BLUE, "clipboard"),
                   (f"{r['error_free']:,}", "Error Free Tasks", T.GREEN, "check"),
                   (f"{r['error']:,}", "Errors", T.RED, "bug"),
                   (f"{r['observation']:,}", "Observations", T.ORANGE, "clipboard"),
                   (FS(r["score"]), "Quality Score", T.score_color(r["score"]), "target")])
    py, ph = 2.42 * IN, 4.30 * IN
    lw = 6.4 * IN
    p.rect(MARGIN, py, lw, ph)
    p.bar(MARGIN + 10, py + 10, lw - 20, f"Quality Score \u2013 {label}", 24, size=10)
    body = [("Error", f"{r['error']:,}"), ("No Error", f"{r['no_error']:,}"),
            ("Observation", f"{r['observation']:,}"),
            ("Error-Free Tasks", f"{r['error_free']:,}"),
            ("Total Tasks", f"{r['total']:,}"), ("Quality Score", FS(r["score"]))]
    p.table(MARGIN + 14, py + 46, lw - 28, ["Measure", "Value"], body,
            col_w=[3.0, 1.4], row_h=32, font=12.5, head_font=10.5,
            cell_colors={(3, 0): T.GREEN, (3, 1): T.GREEN,
                         (5, 0): T.NAVY, (5, 1): T.score_color(r["score"])},
            fill_h=ph - 74, max_row_h=42)
    p.text(MARGIN + 14, py + ph - 22,
           "Error-Free = No Error + Observation   \u2022   Score = Error-Free \u00f7 Total Tasks",
           8.4, False, T.TEXT_MUTED)

    rx = MARGIN + lw + 0.18 * IN
    rw = PAGE_W - MARGIN - rx
    p.rect(rx, py, rw, ph)
    p.bar(rx + 10, py + 10, rw - 20, "Task Composition", 24, size=10)
    # The page is shorter than the slide, so the chart is sized from what is
    # left after the note rather than from a constant that happened to fit
    # once. The legend already carries every count, so the note can be brief.
    note_h = 74
    ch = max(120.0, min(3.2 * IN, rw - 40, ph - 42 - note_h - 22))
    cw = min(rw - 40, ch / 0.92)
    p.image(charts.composition_pie(r["total"], r["error"], r["no_error"], r["observation"],
                                   w=cw / IN, h=ch / IN), rx + (rw - cw) / 2, py + 42, cw)
    ty = py + 42 + ch + 8
    p.text(rx + 22, ty, "Reading this chart", 11.5, True, T.NAVY)
    p.para(rx + 22, ty + 19, rw - 44,
           f"{r['error_free']:,} of {r['total']:,} tasks were error free; "
           f"{r['observation']:,} of those carried an observation, counted inside the "
           "error-free slices and never added on top.", 9.6, T.TEXT)
    if r["source"] == "summary":
        p.text(rx + 22, py + ph - 14, "Figures imported from a previously issued deck.",
               8, False, T.TEXT_MUTED)
    p.footer(foot, label)


def _month_devs(p, sel, r, market, foot):
    label = f"{r['month_name']} {r['year']}"
    devs = metrics.developer_table(sel, month=(r["year"], r["month"]))
    p.head(f"{market} \u2013 {label}", "Developer Report")
    py, ph = 1.10 * IN, 5.62 * IN
    w = PAGE_W - MARGIN * 2
    p.rect(MARGIN, py, w, ph)
    p.bar(MARGIN + 10, py + 10, w - 20, f"Developer Report \u2013 {label}", 24, size=10)
    if devs:
        body = [(_fit(d["name"], HEAD, 11, 3.0 * IN), d["error"], d["no_error"],
                 d["observation"], d["error_free"], d["total"], FS(d["score"])) for d in devs]
        colors = {(i, 6): T.score_color(d["score"]) for i, d in enumerate(devs)}
        total_row, total_score = _dev_totals(devs)
        body.append(total_row)
        colors[(len(devs), 0)] = T.NAVY
        colors[(len(devs), 6)] = T.score_color(total_score)
        p.table(MARGIN + 14, py + 46, w - 28,
                ["Developer Name", "Error", "No Error", "Observation", "Error Free",
                 "Total Tasks", "Quality Score"], body,
                col_w=[3.2, 1.0, 1.1, 1.3, 1.2, 1.1, 1.5], row_h=22, font=10.5,
                head_font=10, cell_colors=colors, fill_h=ph - 90, max_row_h=32)
        p.text(MARGIN + 14, py + ph - 24, NOTE_RULE, 9, False, T.TEXT_MUTED)
    else:
        p.text(MARGIN + 28, py + 70, "No developer detail stored for this month.",
               12, False, T.TEXT_MUTED)
    p.footer(foot, label)


def _month_defects(p, sel, r, market, foot):
    label = f"{r['month_name']} {r['year']}"
    cats = metrics.category_table(sel, month=(r["year"], r["month"]))
    ti = sum(c["internal"] for c in cats)
    te = sum(c["external"] for c in cats)
    p.head(f"{market} \u2013 {label}", "Defect Analysis")
    py, ph = 1.10 * IN, 5.62 * IN
    lw = 8.1 * IN
    p.rect(MARGIN, py, lw, ph)
    p.bar(MARGIN + 10, py + 10, lw - 20, f"Defects by Link Type \u2013 {label}", 24, size=10)
    if cats:
        body = [(c["category"], c["internal"], c["external"], c["total"], f"{c['pct']:.2f}%")
                for c in cats] + [("Total", ti, te, ti + te, "100.00%")]
        colors = {(i, 0): T.CATEGORY_COLORS.get(c["category"], T.TEXT)
                  for i, c in enumerate(cats)}
        colors[(len(cats), 0)] = T.NAVY
        p.table(MARGIN + 14, py + 46, lw - 28,
                ["Error Type", "Test Link", "Live Link", "Total", "% of Total"], body,
                col_w=[2.6, 1.5, 1.5, 0.9, 1.1], row_h=24, font=11, head_font=10,
                cell_colors=colors, fill_h=ph - 62, max_row_h=34)
    else:
        p.icon("check", T.GREEN, MARGIN + (lw - 58) / 2, py + 120, 58)
        p.text(MARGIN, py + 200, "Zero defects this month.", 20, True, T.GREEN, "c", lw)

    rx = MARGIN + lw + 0.18 * IN
    rw = PAGE_W - MARGIN - rx
    p.rect(rx, py, rw, ph)
    p.bar(rx + 10, py + 10, rw - 20, "Category Share", 24, size=10)
    if cats:
        text_h = 140
        dh = max(140.0, min(3.4 * IN, rw - 22, ph - 44 - text_h))
        p.image(charts.category_donut(cats[:6], w=dh / IN, h=dh / IN,
                                      centre_total=r["error"]),
                rx + (rw - dh) / 2, py + 44, dh)
        ty = py + 44 + dh + 10
        p.text(rx + 18, ty, f"{ti} on test links", 12, True, T.BRAND)
        p.para(rx + 18, ty + 18, rw - 36,
               "Caught internally, before the page went live.", 9.6, T.TEXT)
        p.text(rx + 18, ty + 58, f"{te} on live links", 12, True, T.BLUE)
        p.para(rx + 18, ty + 76, rw - 36,
               "Also caught internally by QA \u2014 found after the page went live, "
               "not reported by the client.", 9.6, T.TEXT)
    p.footer(foot, label)


def _qa_summary(p, sel, tot, rows, market, org, period, foot):
    p.head(_brand(org, market), f"QA Summary \u2013 {period}")
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
    lw, py, ph = 6.4 * IN, 1.10 * IN, 5.62 * IN
    p.rect(MARGIN, py, lw, ph)
    p.bar(MARGIN + 10, py + 10, lw - 20, "Key Performance Indicators", 24, size=10)
    p.table(MARGIN + 14, py + 46, lw - 28, ["KPI", "Value"], kpi_rows, col_w=[3.2, 1.5],
            row_h=26, font=11, head_font=10.5,
            cell_colors={(4, 0): T.GREEN, (4, 1): T.GREEN,
                         (10, 0): T.NAVY, (10, 1): T.score_color(tot["score"]),
                         (11, 1): T.BLUE},
            fill_h=ph - 62, max_row_h=32)
    rx = MARGIN + lw + 0.18 * IN
    rw = PAGE_W - MARGIN - rx
    p.rect(rx, py, rw, ph)
    p.bar(rx + 10, py + 10, rw - 20, "Quality Score by Month", 24, size=10)
    p.image(charts.quality_trend(rows, w=(rw - 28) / IN, h=2.6),
            rx + 14, py + 48, rw - 28)
    mb = [(r["label"], r["total"], r["error"], r["error_free"], FS(r["score"])) for r in rows]
    colors = {(i, 4): T.score_color(r["score"]) for i, r in enumerate(rows)}
    p.table(rx + 14, py + 246, rw - 28, ["Month", "Tasks", "Defects", "Error Free", "Score"],
            mb, col_w=[1.5, 0.9, 0.9, 1.1, 1.2], row_h=22, font=10, head_font=9.5,
            cell_colors=colors, max_h=ph - 262)
    p.footer(foot, "QA summary")


def _developer_page(p, chunk, all_devs, market, org, period, foot, idx, total):
    suffix = f" ({idx} of {total})" if total > 1 else ""
    p.head(_brand(org, market), f"Developer Summary \u2013 {period}{suffix}")
    py, ph = 1.10 * IN, 5.62 * IN
    w = PAGE_W - MARGIN * 2
    p.rect(MARGIN, py, w, ph)
    p.bar(MARGIN + 10, py + 10, w - 20, "Per-Developer Performance", 24, size=10)
    body = [(_fit(d["name"], HEAD, 11, 3.0 * IN), d["error"], d["no_error"], d["observation"],
             d["error_free"], d["total"], FS(d["score"])) for d in chunk]
    colors = {(i, 6): T.score_color(d["score"]) for i, d in enumerate(chunk)}
    # Sums on the final page only — a running subtotal partway through an
    # alphabetical list is a number nobody asked for.
    if idx == total:
        total_row, total_score = _dev_totals(all_devs)
        body.append(total_row)
        colors[(len(chunk), 0)] = T.NAVY
        colors[(len(chunk), 6)] = T.score_color(total_score)
    p.table(MARGIN + 14, py + 46, w - 28,
            ["Developer Name", "Error", "No Error", "Observation", "Error Free",
             "Total Tasks", "Quality Score"], body,
            col_w=[3.2, 1.0, 1.1, 1.3, 1.2, 1.1, 1.5], row_h=23, font=10.5,
            head_font=10, cell_colors=colors, fill_h=ph - 90, max_row_h=32)
    p.text(MARGIN + 14, py + ph - 24, NOTE_RULE, 9, False, T.TEXT_MUTED)
    p.footer(foot, "Developer summary")


def _category_page(p, sel, tot, market, org, period, foot):
    p.head(_brand(org, market), f"Defect Category Breakdown \u2013 {period}")
    cats = metrics.category_table(sel)
    lw, py, ph = 8.1 * IN, 1.10 * IN, 5.62 * IN
    ti = sum(c["internal"] for c in cats)
    te = sum(c["external"] for c in cats)
    p.rect(MARGIN, py, lw, ph)
    p.bar(MARGIN + 10, py + 10, lw - 20, "Defects by Category and Link Type", 24, size=10)
    if cats:
        body = [(c["category"], c["internal"], c["external"], c["total"], f"{c['pct']:.2f}%")
                for c in cats] + [("Grand Total", ti, te, ti + te, "100.00%")]
        colors = {(i, 0): T.CATEGORY_COLORS.get(c["category"], T.TEXT)
                  for i, c in enumerate(cats)}
        colors[(len(cats), 0)] = T.NAVY
        p.table(MARGIN + 14, py + 46, lw - 28,
                ["Defect Category", "Test Link", "Live Link", "Total Defects",
                 "% of Total"], body,
                col_w=[2.6, 1.5, 1.5, 1.1, 1.1], row_h=24, font=11, head_font=10,
                cell_colors=colors, fill_h=ph - 62, max_row_h=34)
    else:
        p.text(MARGIN + 28, py + 80, "Zero defects across this period.", 16, True, T.GREEN)
    rx = MARGIN + lw + 0.18 * IN
    rw = PAGE_W - MARGIN - rx
    p.rect(rx, py, rw, ph)
    p.bar(rx + 10, py + 10, rw - 20, "Category Share", 24, size=10)
    if cats:
        bar_h, chart_h = 22, 1.20 * IN
        dh = max(140.0, min(3.3 * IN, rw - 22,
                            ph - 44 - 8 - bar_h - 8 - chart_h - 10))
        p.image(charts.category_donut(cats[:7], w=dh / IN, h=dh / IN,
                                      centre_total=tot["error_tasks"]),
                rx + (rw - dh) / 2, py + 44, dh)
        by = py + 44 + dh + 8
        p.bar(rx + 10, by, rw - 20, "Test vs Live Links", bar_h, size=9)
        p.image(charts.internal_external(ti, te, w=(rw - 36) / IN, h=chart_h / IN),
                rx + 18, by + bar_h + 8, rw - 36)
    p.footer(foot, "Defect categories")


def _aging_page(p, sel, market, org, period, foot):
    rows, ref = metrics.aging_table(sel)
    p.head(_brand(org, market), f"Aging Analysis \u2013 {period}")
    py, ph = 1.10 * IN, 5.62 * IN
    lw = 8.1 * IN
    p.rect(MARGIN, py, lw, ph)
    p.bar(MARGIN + 10, py + 10, lw - 20, "Defect age distribution", 24, size=10)
    if rows and any(r["count"] for r in rows):
        p.image(charts.aging_bar(rows, w=(lw - 44) / IN, h=2.7), MARGIN + 22, py + 48, lw - 44)
        body = [(r["bucket"], r["count"], f"{r['pct']:.2f}%") for r in rows]
        p.table(MARGIN + 14, py + 258, lw - 28, ["Age Bucket", "Defects", "% of Defects"],
                body, col_w=[2.2, 1.0, 1.2], row_h=26, font=11, max_h=ph - 274)
    else:
        p.text(MARGIN + 28, py + 70, "No dated defects in this selection.", 13,
               False, T.TEXT_MUTED)
    rx = MARGIN + lw + 0.18 * IN
    rw = PAGE_W - MARGIN - rx
    p.rect(rx, py, rw, ph)
    p.bar(rx + 10, py + 10, rw - 20, "How to read this", 24, size=10)
    y = py + 52
    p.text(rx + 18, y, "What is measured", 12, True, T.NAVY)
    y += 20 + p.para(rx + 18, y + 20, rw - 36,
                     "Days between the date a defect was logged and "
                     + (f"the latest audit date in this period ({ref})." if ref
                        else "the latest audit date in this period."), 10, T.TEXT)
    y += 16
    p.text(rx + 18, y, "What is NOT measured", 12, True, T.RED)
    p.para(rx + 18, y + 20, rw - 36,
           "The audit sheets carry no closure date, so this is not time-to-fix. Adding a "
           "'Date Closed' column would let a true time-to-resolution be reported here.",
           10, T.TEXT)
    p.footer(foot, "Aging analysis")


def _critical_page(p, sel, market, org, period, foot):
    rows, total = metrics.critical_defects(sel, limit=13)
    p.head(_brand(org, market), f"Critical Defects \u2013 {period}")
    py, ph = 1.10 * IN, 5.62 * IN
    w = PAGE_W - MARGIN * 2
    p.rect(MARGIN, py, w, ph)
    if rows:
        p.bar(MARGIN + 10, py + 10, w - 20,
              f"{total} defect(s) logged at Critical severity", 24, size=10)
        body = [(r.get("date") or "\u2013", _fit(r.get("dev") or "\u2013", HEAD, 10.5, 1.8 * IN),
                 r.get("category") or "Other", r.get("env") or "Internal",
                 (r.get("title") or "")[:70]) for r in rows]
        colors = {(i, 2): T.CATEGORY_COLORS.get(r.get("category"), T.TEXT)
                  for i, r in enumerate(rows)}
        p.table(MARGIN + 14, py + 46, w - 28,
                ["Date", "Developer", "Category", "Environment", "Task"], body,
                col_w=[1.0, 2.0, 1.6, 1.2, 5.2], row_h=24, font=10.5,
                cell_colors=colors, fill_h=ph - 72, max_row_h=32)
        if total > len(rows):
            p.text(MARGIN + 14, py + ph - 20,
                   f"Showing the first {len(rows)} of {total}. The full list is in the "
                   "CSV export.", 8.4, False, T.TEXT_MUTED)
    else:
        p.bar(MARGIN + 10, py + 10, w - 20, "Critical defects", 24, size=10)
        p.icon("check", T.GREEN, (PAGE_W - 68) / 2, py + 120, 68)
        p.text(0, py + 210, "No critical defects in this period.", 22, True, T.GREEN,
               "c", PAGE_W)
    p.footer(foot, "Critical defects")


def _recs_page(p, sel, market, org, period, foot, note):
    recs = metrics.recommendations(sel)
    p.head(_brand(org, market), f"Key QA Recommendations \u2013 {period}")
    py, ph = 1.10 * IN, 5.62 * IN
    w = PAGE_W - MARGIN * 2
    p.rect(MARGIN, py, w, ph)
    p.bar(MARGIN + 10, py + 10, w - 20,
          "Actions suggested by the numbers in this report", 24, size=10)
    per_col = (len(recs) + 1) // 2 or 1
    cw = (w - 28 - 18) / 2
    rh = min(104, (ph - 58) / max(per_col, 1))
    for i, rec in enumerate(recs):
        cx = MARGIN + 14 + (i // per_col) * (cw + 18)
        cy = py + 48 + (i % per_col) * (rh + 6)
        p.rect(cx, cy, cw, rh, fill=T.PAGE_BG, line=T.BORDER, radius=5)
        col = [T.BLUE, T.ORANGE, T.RED, T.PURPLE, T.TEAL, T.GREEN][i % 6]
        p.icon(rec["icon"], col, cx + 12, cy + 13, 26)
        p.text(cx + 48, cy + 13, _fit(rec["title"], HEAD, 12, cw - 62), 12, True, T.NAVY)
        p.para(cx + 48, cy + 33, cw - 62, rec["text"], 9.2, T.TEXT, max_lines=4)
    if note:
        p.text(MARGIN + 14, py + ph - 24, f"Note: {note}", 10, False, T.TEXT)
    p.footer(foot, "Recommendations")


def _dashboard_page(p, sel, tot, rows, market, period, foot):
    p.rect(0, 0, PAGE_W, 0.82 * IN, fill=T.NAVY, line=None, radius=0)
    p.text(0, 0.24 * IN, f"{market.upper()} QA SUMMARY REPORT  \u2022  {period.upper()}",
           20, True, T.WHITE, "c", PAGE_W)
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
    n, gap = len(kpis), 0.11 * IN
    tw = (PAGE_W - MARGIN * 2 - gap * (n - 1)) / n
    for i, (v, lbl, col, ic, sub) in enumerate(kpis):
        p.kpi_tile(MARGIN + i * (tw + gap), 0.98 * IN, tw, 0.92 * IN, v, lbl, col, ic, sub)

    py, ph = 2.06 * IN, 3.30 * IN
    p1w, p2w, p3w = 4.62 * IN, 3.72 * IN, 3.71 * IN
    p1x = MARGIN
    p2x = p1x + p1w + 0.14 * IN
    p3x = p2x + p2w + 0.14 * IN

    p.rect(p1x, py, p1w, ph)
    p.bar(p1x + 7, py + 7, p1w - 14, "Quality Score Trend (Monthly)", 22, size=9)
    _ch = (ph - 44) - 36 - 8
    p.image(charts.quality_trend(rows, w=(p1w - 22) / IN, h=_ch / IN),
            p1x + 11, py + 36, p1w - 22, _ch)
    scored = [r for r in rows if r["score"] is not None]
    if scored:
        best = max(scored, key=lambda r: r["score"])
        worst = min(scored, key=lambda r: r["score"])
        band = [(T.GREEN, "Highest", f"{best['label']} {FS(best['score'])}"),
                (T.RED, "Lowest", f"{worst['label']} {FS(worst['score'])}"),
                (T.BLUE, "Overall", FS(tot["score"])),
                (T.PURPLE, "Avg monthly", FS(tot["avg_monthly_score"]))]
        bw = (p1w - 22 - 18) / 4
        for i, (col, lbl, val) in enumerate(band):
            bx = p1x + 11 + i * (bw + 6)
            byy = py + ph - 44
            p.rect(bx, byy, bw, 36, fill=T.PAGE_BG, line=T.BORDER, radius=5)
            p.text(bx + 6, byy + 7, lbl, 5.8, True, col)
            p.text(bx + 6, byy + 19, _fit(val, HEAD, 7.2, bw - 12), 7.2, True, T.TEXT)

    p.rect(p2x, py, p2w, ph)
    p.bar(p2x + 7, py + 7, p2w - 14, "Defect Category Breakdown", 22, size=9)
    cats = metrics.category_table(sel)
    if cats:
        p.image(charts.category_donut(cats[:6], w=1.70, h=1.70,
                                      centre_total=tot["error_tasks"]),
                p2x + 20, py + 40, 1.70 * IN)
        body = [(c["category"], c["total"], f"{c['pct']:.2f}%") for c in cats[:7]]
        colors = {(i, 0): T.CATEGORY_COLORS.get(c["category"], T.TEXT)
                  for i, c in enumerate(cats[:7])}
        p.table(p2x + 1.92 * IN, py + 38, p2w - 2.02 * IN, ["Category", "No.", "%"], body,
                col_w=[2.5, 0.8, 1.2], row_h=17, header_h=18, font=6.2, head_font=6.2,
                cell_colors=colors, max_h=ph - 58, pad=3)
    else:
        p.text(p2x, py + 1.4 * IN, "No defects in this selection", 10, True, T.GREEN, "c", p2w)

    p.rect(p3x, py, p3w, ph)
    p.bar(p3x + 7, py + 7, p3w - 14, "Top Performers", 22, size=9)
    top, bar_n = metrics.top_developers(sel, n=3)
    rh = (ph - 54) / 3
    for i, d in enumerate(top):
        yy = py + 38 + i * rh
        p.image(charts.rank_badge(i + 1), p3x + 13, yy + (rh - 36) / 2, 36, 36)
        p.text(p3x + 56, yy + 3, _fit(d["name"], HEAD, 10.5, p3w - 68), 10.5, True, T.BLUE)
        p.text(p3x + 56, yy + 20, f"{d['total']} tasks   \u2022   {d['error_free']} error free",
               7.8, False, T.TEXT_MUTED)
        p.text(p3x + 56, yy + 34, f"{FS(d['score'])} quality score", 10, True,
               T.score_color(d["score"]))
    if top:
        p.text(p3x, py + ph - 16, f"Ranked on score, minimum {bar_n} audited tasks to qualify.",
               6.4, False, T.TEXT_MUTED, "c", p3w)

    iy = py + ph + 0.14 * IN
    p.bar(MARGIN, iy, PAGE_W - MARGIN * 2, "Key Insights", 22, size=9)
    ins = metrics.insights(sel)
    if ins:
        n = len(ins)
        iw = (PAGE_W - MARGIN * 2 - 7 * (n - 1)) / n
        cols = [T.BLUE, T.GREEN, T.ORANGE, T.PURPLE, T.TEAL, T.RED]
        for i, item in enumerate(ins):
            x = MARGIN + i * (iw + 7)
            p.rect(x, iy + 26, iw, 76)
            col = cols[i % len(cols)]
            p.icon(item["icon"], col, x + (iw - 22) / 2, iy + 32, 22)
            p.text(x, iy + 58, item["value"], 8.6, True, col, "c", iw)
            p.para(x + 4, iy + 70, iw - 8, item["text"], 6.4, T.TEXT_MUTED, align="c",
                   max_lines=3)
    p.footer(foot, "Quality score dashboard")


def _closing_page(p, org, market, period, tot):
    p.text(0, 2.75 * IN, "Thank You", 42, True, T.WHITE, "c", PAGE_W)
    p.rect((PAGE_W - 1.7 * IN) / 2, 3.78 * IN, 1.7 * IN, 4, fill=T.BLUE, line=None, radius=0)
    p.text(0, 4.08 * IN, f"{_brand(org, market)} Quality Assurance  \u2022  {period}", 13,
           False, "C6D4EC", "c", PAGE_W)
    if tot["score"] is not None:
        p.text(0, 4.62 * IN, f"{tot['total_tasks']:,} tasks audited  \u2022  "
                             f"{FS(tot['score'])} overall quality score",
               10.5, False, "7E9AC8", "c", PAGE_W)
