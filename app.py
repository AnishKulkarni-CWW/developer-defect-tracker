"""
QA Report Studio — Streamlit front end.

Design rule that shapes this file: nothing expensive runs while the user is
setting up a report. Every filter lives inside an `st.form`, so changing a
dropdown does not rerun the script; charts, decks and PDFs are built only when
Generate is pressed. Finished files are held in session state so a download
click never rebuilds them.

The app is a single-page console with a product rail down the left:

    Home · Upload & Configure · Results & Insights · Data Manager ·
    Compare · Settings · Help

The market (India / C3 / Japan) and the reporting period are chosen once in the
top bar and apply to every page, so a report is set up in one place and read in
another instead of every market owning its own copy of the whole workflow.

The underlying four-step workflow is unchanged:

    1 Upload   2 Review & validate   3 Configure   4 Generate & download
"""

from __future__ import annotations

import html
import inspect
import io
import os
import sys
import traceback
from datetime import datetime

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qars import charts, deck, ingest, metrics, normalize as nz, pdf, store, theme as T  # noqa: E402


# --------------------------------------------------------------------------
# Streamlit renamed `use_container_width` to `width="stretch"`. Use whichever
# the installed version accepts, so the app is correct on an older pinned
# release and on the newest one without deprecation noise in the console.
# --------------------------------------------------------------------------
def _wide(fn):
    try:
        if "width" in inspect.signature(fn).parameters:
            return {"width": "stretch"}
    except (TypeError, ValueError):
        pass
    return {"use_container_width": True}


WIDE_BTN = _wide(st.button)
WIDE_DF = _wide(st.dataframe)
WIDE_IMG = _wide(st.image)


# --------------------------------------------------------------------------
# Chart caching for the on-screen dashboard.
#
# Streamlit reruns the whole script on any widget interaction. Without a cache
# the browser dashboard would redraw every chart each time — exactly the
# mid-work processing this app is built to avoid. Keyed on the figures
# themselves, so a cache entry is reused until the numbers actually change.
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False, max_entries=48)
def _dash_charts(rows, cats, error_total, target, comp):
    return {
        "trend": charts.quality_trend(rows, w=6.0, h=3.0, target=target),
        "donut": charts.category_donut(cats[:6], w=3.2, h=3.2,
                                       centre_total=error_total) if cats else None,
        "comp": charts.composition_bar(*comp, w=11.0, h=1.5),
    }


APP_TITLE = "QA Report Studio"
APP_TAGLINE = "Defects to better products"
MONTHS = metrics.MONTH_FULL
FS = metrics.fmt_score

# key, icon, label, one-line description used as the page subtitle
PAGES = [
    ("home", "🏠", "Home", "Your QA data at a glance."),
    ("upload", "☁️", "Upload & Configure", "Upload your audit files and set the report up."),
    ("results", "📊", "Results & Insights", "The full analysis, ready to export."),
    ("data", "🗄️", "Data Manager", "Merge developer names, manage periods and backups."),
    ("compare", "⚖️", "Compare", "Put markets side by side."),
    ("settings", "⚙️", "Settings", "Branding, benchmarks and stored data."),
    ("help", "❓", "Help", "How every number on the page is worked out."),
]
PAGE_BY_KEY = {p[0]: p for p in PAGES}

st.set_page_config(page_title=APP_TITLE, page_icon="🐞", layout="wide",
                   initial_sidebar_state="expanded")


# ==========================================================================
# state
# ==========================================================================
def boot():
    # In session mode load_db() returns a fresh empty store, so each browser
    # session starts clean and stays isolated from every other visitor.
    st.session_state.setdefault("db", store.load_db())
    st.session_state.setdefault("settings", store.load_settings())
    st.session_state.setdefault("reports", {})
    st.session_state.setdefault("flash", [])
    st.session_state.setdefault("pending", {})     # market -> parsed-but-unconfirmed uploads
    st.session_state.setdefault("confirm_clear", False)
    # Bumped whenever data is cleared. It forms part of every file_uploader key,
    # so Streamlit builds a fresh widget and the previously selected file really
    # disappears instead of lingering and leaving Read file(s) greyed out.
    st.session_state.setdefault("upload_epoch", 0)

    st.session_state.setdefault("nav", "home")
    st.session_state.setdefault("market", store.MARKETS[0])
    st.session_state.setdefault("dark", dark_theme())
    # Report configuration, per market. Held outside widget state on purpose:
    # Streamlit discards the state of a widget that did not render this run, and
    # the filters are set on one page and read on another.
    st.session_state.setdefault("cfg", {})
    # Bumped whenever the stored rows change. It forms part of every configure
    # widget key, so the form is rebuilt from what is actually available rather
    # than holding a year or a developer that has just been deleted.
    st.session_state.setdefault("cfg_epoch", 0)


def dark_theme():
    """
    True when Streamlit itself is running dark.

    The app used to own a light/dark switch of its own, which looked right
    until you reached a table: Streamlit paints its data grid, dropdown menus
    and widget chrome from `theme.base` in .streamlit/config.toml, and no
    amount of CSS moves them at runtime. Reading that one setting instead means
    the whole product — ours and Streamlit's — is dark or light together, never
    half of each. Switching themes is four lines in that file; it is documented
    there and on the Settings page.
    """
    try:
        return str(st.get_option("theme.base") or "light").lower() == "dark"
    except Exception:                                         # noqa: BLE001
        return False


def persist():
    store.save_db(st.session_state.db)
    store.save_settings(st.session_state.settings)


def flash(kind, msg):
    st.session_state.flash.append((kind, msg))


def drain_flash():
    for kind, msg in st.session_state.flash:
        getattr(st, kind)(msg)
    st.session_state.flash = []


def go(page, **extra):
    """Switch page on the next run. Used by every nav and call-to-action."""
    st.session_state.nav = page
    for k, v in extra.items():
        st.session_state[k] = v
    st.rerun()


def has_data(db, market):
    return bool(db["tasks"].get(market)) or bool(db["monthly"].get(market))


def progress_bar(slot, pct, message, done=False):
    """
    Draw the app's own progress bar in the sticky strip under the top bar.

    Streamlit's built-in "running" indicator is hidden in CSS: it appears in the
    top-right corner, says nothing about what is happening, and shifts the page
    while you read it.
    """
    pct = max(0, min(100, int(round(pct))))
    cls = "qrs-fill done" if done else "qrs-fill"
    on = "on" if pct >= 55 else ""
    slot.markdown(
        f'<div class="qrs-sticky"><div class="qrs-track">'
        f'<div class="{cls}" style="width:{pct}%"></div>'
        f'<span class="{on}">{message}</span></div></div>'
        f'<div class="qrs-spacer"></div>',
        unsafe_allow_html=True)


# ==========================================================================
# view atoms
# ==========================================================================
def esc(v):
    return html.escape(str(v), quote=True)


def md(html_str):
    st.markdown(html_str, unsafe_allow_html=True)


def bar(label, sub=None):
    """Section heading with the brand tick down its left edge."""
    md(f'<div class="qrs-bar">{esc(label)}'
       + (f'<span class="sub">{esc(sub)}</span>' if sub else "") + "</div>")


def page_header(title, sub=None, crumb=None):
    if crumb:
        md(f'<div class="qrs-crumb">{crumb}</div>')
    md(f'<div class="qrs-page-title">{esc(title)}</div>')
    if sub:
        md(f'<div class="qrs-page-sub">{esc(sub)}</div>')


def pill(text, color):
    return (f'<span class="qrs-pill" style="background:{T.hx(T.soft(color))};'
            f'color:{T.hx(color)}">{esc(text)}</span>')


def kpi_row(items, compact=False, cols=None):
    """
    items: [(value, label, colour, sub_or_None)] with an optional 5th icon slot.

    `compact` shrinks the number so a four-across row still fits inside a
    two-thirds-width column at 100% zoom. Streamlit's own st.metric truncates
    "94.05%" to "9…" at that width, which is worse than useless.

    `cols` pins the row to a column count. Left to auto-fit, eight tiles land
    as a ragged six-plus-two; pinned to four they read as two even rows.
    """
    cls = "qrs-kpi small" if compact else "qrs-kpi"
    grid = "qrs-kpis"
    if compact:
        grid += " tight"
    elif cols:
        grid += f" c{cols}"
    out = [f'<div class="{grid}">']
    for item in items:
        value, label, color, sub = item[:4]
        icon = item[4] if len(item) > 4 else None
        out.append(f'<div class="{cls}">')
        if icon and not compact:
            out.append(f'<div class="ico" style="background:{T.hx(T.soft(color))};'
                       f'color:{T.hx(color)}">{icon}</div>')
        out.append(f'<div class="v" style="color:{T.hx(color)}">{value}</div>'
                   f'<div class="l">{esc(label)}</div>')
        if sub:
            out.append(f'<div class="s">{sub}</div>')
        out.append("</div>")
    out.append("</div>")
    md("".join(out))


def delta(current, previous, better="up", suffix="vs previous month"):
    """
    Month-on-month movement, rendered the way the dashboard reads it.

    Returns raw HTML for the KPI sub-line, or a neutral note when there is no
    earlier month to compare against — never a fabricated 0%.
    """
    if previous in (None, 0) or current is None:
        return '<span style="opacity:.75">No earlier month to compare</span>'
    change = (current - previous) / abs(previous) * 100.0
    if abs(change) < 0.05:
        return f'<span style="opacity:.8">No change</span> {esc(suffix)}'
    up = change > 0
    good = up if better == "up" else not up
    return (f'<span class="{"up" if good else "down"}">{"↑" if up else "↓"} '
            f'{abs(change):.1f}%</span> {esc(suffix)}')


def steps(active, names=None):
    """The workflow indicator: upload, review, configure, generate."""
    names = names or ["Upload data", "Review & validate", "Configure", "Generate"]
    out = ['<div class="qrs-steps">']
    for i, n in enumerate(names, 1):
        if i > 1:
            out.append(f'<div class="line{" done" if i <= active else ""}"></div>')
        cls = "done" if i < active else ("active" if i == active else "todo")
        out.append(f'<div class="st {cls}"><div class="dot">{"✓" if i < active else i}</div>'
                   f'<div class="lb">{esc(n)}</div></div>')
    out.append("</div>")
    md("".join(out))


def rank_rows(top):
    """Podium list with a medal badge and a bar showing the score."""
    colors = {1: T.GOLD, 2: T.SILVER, 3: T.BRONZE}
    out = []
    for i, d in enumerate(top, 1):
        sc = d["score"] or 0
        out.append(
            f'<div class="qrs-rank">'
            f'<div class="badge" style="background:{T.hx(colors.get(i, T.BRAND))}">{i}</div>'
            f'<div class="body"><div class="nm">{esc(d["name"])}</div>'
            f'<div class="mt">{d["total"]} tasks &bull; {d["error_free"]} error free</div>'
            f'<div class="meter"><i style="width:{max(2, min(100, sc)):.0f}%"></i></div></div>'
            f'<div class="sc" style="color:{T.hx(T.score_color(d["score"]))}">'
            f'{FS(d["score"])}</div></div>')
    md("".join(out))


def storage_notice():
    """
    Say plainly what happens to the data, because the answer differs between a
    laptop and a shared server and getting it wrong loses someone's work.
    """
    if store.storage_mode() != "session":
        return
    md('<div class="qrs-info">☁️ <b>Running on a hosted server.</b> Nothing is saved to '
       'disk here: your data lives in this browser session only, and is cleared when '
       'the tab closes or the server restarts. Other people using this link get their '
       'own separate copy. Use <b>Export database</b> on the Data Manager page to keep '
       'your work, and <b>Restore database</b> to pick it back up.</div>')


def empty_state(icon, title, text, cta=None, page=None, key="cta"):
    md(f'<div class="qrs-panel" style="text-align:center;padding:38px 24px;">'
       f'<div style="font-size:2.6rem;line-height:1">{icon}</div>'
       f'<div style="font-weight:800;font-size:1.06rem;margin-top:10px">{esc(title)}</div>'
       f'<div style="color:{T.hx(T.TEXT_MUTED)};font-size:.86rem;margin-top:6px">'
       f'{esc(text)}</div></div>')
    if cta and page:
        c = st.columns([1, 1.1, 1])[1]
        if c.button(cta, type="primary", key=key, **WIDE_BTN):
            go(page)


# ==========================================================================
# chrome — sidebar rail and top bar
# ==========================================================================
def sidebar():
    with st.sidebar:
        md(f'<div class="qrs-brand"><div class="mark">🐞</div>'
           f'<div><div class="name">{esc(APP_TITLE)}</div>'
           f'<div class="tag">{esc(APP_TAGLINE)}</div></div></div>')

        md('<div class="qrs-navlabel">Menu</div>')
        for key, icon, label, _ in PAGES:
            active = st.session_state.nav == key
            if st.button(f"{icon} {label}", key=f"nav_{key}",
                         type="primary" if active else "secondary", **WIDE_BTN):
                if not active:
                    go(key)

        md('<div class="qrs-help-card"><div class="t">💡 Need a hand?</div>'
           '<div class="d">Every figure on the page is explained on the Help '
           'page — including why an observation is never counted twice.</div></div>')
        if st.button("Open the guide", key="nav_help_cta", **WIDE_BTN):
            go("help")

        who = (st.session_state.settings.get("prepared_by") or "").strip()
        org = st.session_state.settings.get("org_name") or "—"
        initials = "".join(w[0] for w in who.split()[:2]).upper() if who else "QA"
        md(f'<div class="qrs-foot"><div class="av">{esc(initials)}</div>'
           f'<div><div class="n">{esc(who or "QA team")}</div>'
           f'<div class="s">{esc(org)} &middot; {esc(store.storage_mode())} storage</div>'
           f'</div></div>')


def topbar():
    """Market, period and appearance — chosen once, applied on every page."""
    db = st.session_state.db
    c1, c2, c3 = st.columns([3.1, 1.3, 1.5])

    with c1:
        query = st.text_input("Search", key="global_search", label_visibility="collapsed",
                              placeholder="🔎  Search developers, defects or periods…")
    with c2:
        market = st.selectbox("Market", store.MARKETS, label_visibility="collapsed",
                              index=store.MARKETS.index(st.session_state.market),
                              key="topbar_market")
        st.session_state.market = market
    with c3:
        periods = metrics.available_periods(db, market)
        opts = ["All periods"] + [f"{MONTHS[m - 1]} {y}" for y, m in periods]
        pick = st.selectbox("Period", opts, label_visibility="collapsed",
                            key=f"topbar_period_{market}")
        st.session_state.period_pick = (None if pick == "All periods"
                                        else periods[opts.index(pick) - 1])
    return (query or "").strip()


def search_results(query):
    """
    A read-only jump-to panel over everything already loaded.

    Nothing here changes state — it exists so a name or a defect can be found
    without first working out which market and month it lives in.
    """
    db, s = st.session_state.db, st.session_state.settings
    q = query.lower()
    lookup = nz.build_alias_lookup(s.get("dev_aliases"))

    devs, tasks, per = {}, [], []
    for m in store.MARKETS:
        for r in db["tasks"].get(m, []):
            name = nz.resolve_name(r.get("dev_raw") or "", lookup)
            if q in name.lower():
                d = devs.setdefault((m, name), {"total": 0, "err": 0})
                d["total"] += 1
                d["err"] += 1 if r.get("status") == nz.STATUS_ERR else 0
            hay = " ".join(str(r.get(k) or "") for k in
                           ("title", "category", "severity", "details", "env", "qa"))
            if q in hay.lower() and len(tasks) < 40:
                tasks.append((m, r))
        for y, mo in metrics.available_periods(db, m):
            if q in f"{MONTHS[mo - 1]} {y} {m}".lower():
                per.append((m, y, mo))

    bar("Search results", f'for “{query}”')
    if not (devs or tasks or per):
        md('<div class="qrs-info">Nothing matched. Search looks at developer names, '
           'defect titles, categories, severities, environments and periods.</div>')
        return

    if devs:
        md("<b>Developers</b>")
        rows = ['<table class="qrs-table"><tr><th>Developer</th><th>Market</th>'
                '<th class="num">Tasks</th><th class="num">Defects</th></tr>']
        for (m, name), d in sorted(devs.items(), key=lambda x: -x[1]["total"])[:12]:
            rows.append(f'<tr><td>{esc(name)}</td><td>{esc(m)}</td>'
                        f'<td class="num">{d["total"]}</td>'
                        f'<td class="num">{d["err"]}</td></tr>')
        md("".join(rows) + "</table>")
    if per:
        md("<b>Periods</b>")
        md(" ".join(pill(f"{m} · {MONTHS[mo - 1]} {y}", T.BRAND) for m, y, mo in per[:12]))
    if tasks:
        md(f"<b>Matching rows</b> <span style='color:{T.hx(T.TEXT_MUTED)}'>"
           f"(first {len(tasks)})</span>")
        st.dataframe([{"Market": m, "Date": r.get("date"), "Developer": r.get("dev"),
                       "Status": r.get("status"), "Category": r.get("category") or "",
                       "Severity": r.get("severity") or "", "Task": r.get("title")}
                      for m, r in tasks], hide_index=True, **WIDE_DF)
    st.caption("Search is read-only — it never changes a filter or a stored figure.")


# ==========================================================================
# STEP 1-2 — upload, review mapping, validate
# ==========================================================================
def upload_cards(market):
    db = st.session_state.db
    ep = st.session_state.upload_epoch
    c1, c2 = st.columns(2)

    with c1:
        with st.container(border=True):
            md('<div style="font-weight:800;font-size:.95rem">📄 Audit sheet '
               f'<span style="color:{T.hx(T.BRAND)};font-weight:700">(required)</span></div>'
               '<div style="color:' + T.hx(T.TEXT_MUTED) + ';font-size:.78rem;margin:4px 0 10px">'
               'The monthly QA audit log. Gives full detail, so every filter and every '
               'chart works. .xlsx, .xlsm, .xls or .csv.</div>')
            files = st.file_uploader("Audit file(s)", type=["xlsx", "xlsm", "xls", "csv"],
                                     accept_multiple_files=True,
                                     key=f"xl_{market}_{ep}",
                                     label_visibility="collapsed")
            if st.button("Read file(s)", key=f"bxl_{market}", disabled=not files,
                         type="primary", **WIDE_BTN):
                _stage_excel(market, files)
                st.rerun()

    with c2:
        with st.container(border=True):
            md('<div style="font-weight:800;font-size:.95rem">📊 Existing PowerPoint report '
               f'<span style="color:{T.hx(T.TEXT_MUTED)};font-weight:600">(optional)</span></div>'
               '<div style="color:' + T.hx(T.TEXT_MUTED) + ';font-size:.78rem;margin:4px 0 10px">'
               'A deck you already issued. Recovers the monthly totals so earlier months '
               'appear without re-keying.</div>')
            ppts = st.file_uploader("PPTX file(s)", type=["pptx"],
                                    accept_multiple_files=True,
                                    key=f"pp_{market}_{ep}",
                                    label_visibility="collapsed")
            if st.button("Import PowerPoint", key=f"bpp_{market}", disabled=not ppts,
                         **WIDE_BTN):
                _import_ppt(market, ppts)

    if has_data(db, market):
        md('<div class="qrs-ok">✅ <b>' + esc(market) + '</b> already has data loaded. '
           'Uploading the same period again replaces it rather than adding to it, so a '
           'corrected sheet is safe to re-read.</div>')


def _stage_excel(market, files):
    """Parse now, but hold the rows until the user has reviewed step 2."""
    staged, failed = [], []
    for f in files:
        try:
            rows, rep = ingest.read_excel(f, market, filename=f.name)
            staged.append({"rows": rows, "report": rep, "name": f.name})
        except ingest.IngestError as exc:
            failed.append((f.name, str(exc)))
        except Exception as exc:                              # noqa: BLE001
            failed.append((f.name, "This file could not be read. It may be corrupted or "
                                   f"in an unexpected layout. ({type(exc).__name__})"))
    st.session_state.pending[market] = {"staged": staged, "failed": failed}


def _review_and_confirm(market, pend):
    db = st.session_state.db
    for name, msg in pend["failed"]:
        st.error(f"**{name}** — {msg}")

    if not pend["staged"]:
        if st.button("Dismiss", key=f"dismiss_{market}"):
            st.session_state.pending.pop(market, None)
            st.rerun()
        return

    bar("Review the mapping", "Check the columns and the reporting period before importing")
    corrections = {}
    for i, item in enumerate(pend["staged"]):
        rep = item["report"]
        with st.container(border=True):
            md(f'<div style="font-weight:800;font-size:.92rem">📗 {esc(rep["file"])}</div>'
               f'<div style="color:{T.hx(T.TEXT_MUTED)};font-size:.76rem;margin-top:3px">'
               f'sheet <b>{esc(rep["sheet"])}</b> &nbsp;·&nbsp; header on row '
               f'{rep["header_row"]} &nbsp;·&nbsp; {rep["rows_kept"]} usable row(s)</div>')
            m1, m2 = st.columns([2, 1])
            with m1:
                found = ", ".join(rep["columns_found"])
                st.caption(f"**Columns recognised:** {found}")
                if rep["columns_missing"]:
                    st.caption(f"**Not present:** {', '.join(rep['columns_missing'])} — "
                               "these simply will not be available as filters.")
            with m2:
                det = rep["month_detection"]
                src_txt = " · ".join(f"{k}: {ingest.month_label(v)}"
                                     for k, v in det["sources"].items()) or "no signal"
                if det["conflict"]:
                    st.warning(f"⚠ Month conflict detected — {src_txt}. "
                               "Confirm the reporting period below.")
                else:
                    st.caption(f"**Month detected from** {src_txt}")

                periods = sorted({(r["year"], r["month"]) for r in item["rows"]})
                choices = _month_choices(det, periods)
                opts = ["Keep dates as they are in the sheet"] + [
                    f"Force everything to {MONTHS[m - 1]} {y}" for y, m in choices]

                # A handful of rows dated outside the dominant month are almost
                # always typos. Left alone they stretch the report title to
                # "Feb 2025 - Feb 2026" and put two identical "Feb" bars on the
                # trend chart, so the correction is pre-selected — still visible,
                # still overridable.
                default_idx = 0
                counts = {}
                for r in item["rows"]:
                    counts[(r["year"], r["month"])] = counts.get((r["year"], r["month"]), 0) + 1
                if len(counts) > 1:
                    dom = max(counts, key=counts.get)
                    if counts[dom] / sum(counts.values()) >= 0.85 and dom in choices:
                        default_idx = choices.index(dom) + 1
                        st.info(f"{sum(counts.values()) - counts[dom]} row(s) fall outside "
                                f"{MONTHS[dom[1] - 1]} {dom[0]}. They look like date typos, "
                                "so the whole file is set to that month below. Change it if "
                                "the sheet really does span several months.")
                pick = st.selectbox("Reporting period", opts, index=default_idx,
                                    key=f"per_{market}_{i}")
                if pick != opts[0]:
                    lbl = pick.replace("Force everything to ", "")
                    mon, yr = lbl.split()
                    corrections[i] = (int(yr), MONTHS.index(mon) + 1)
            st.caption(f"Detected period(s) in the data: {', '.join(rep['periods'])}")

    bar("Validate", "Anything the sheet could not answer for itself")
    for item in pend["staged"]:
        rep = item["report"]
        msgs = []
        if rep["skipped_unreadable"]:
            msgs.append(f"{rep['skipped_unreadable']} row(s) skipped — no recognisable "
                        f"Status or Developer ({', '.join(rep['skipped_examples'])}…).")
        if rep["date_outliers"]:
            msgs.append(f"{len(rep['date_outliers'])} row(s) dated outside "
                        f"{rep['dominant_year']}: {', '.join(rep['date_outliers'][:5])}. "
                        "These are usually typos in the sheet.")
        if rep["undated"]:
            msgs.append(f"{rep['undated']} row(s) have no date and will be filed under "
                        "the reporting period chosen above.")
        if msgs:
            md(f'<div class="qrs-note"><b>{esc(rep["file"])}</b><br>' + "<br>".join(msgs)
               + "</div>")
        else:
            md(f'<div class="qrs-ok"><b>{esc(rep["file"])}</b> — '
               f'{rep["rows_kept"]} row(s) read with no issues.</div>')

    c1, c2, _ = st.columns([1.3, 1, 2.4])
    if c1.button("✅  Confirm and import", type="primary", key=f"conf_{market}", **WIDE_BTN):
        total = 0
        for i, item in enumerate(pend["staged"]):
            rows = item["rows"]
            if i in corrections:
                y, m = corrections[i]
                for r in rows:
                    r["year"], r["month"] = y, m
                    if r.get("date"):
                        r["date"] = f"{y:04d}-{m:02d}-{r['date'][-2:]}"
            store.add_tasks(db, market, rows, item["name"])
            total += len(rows)
        _apply_auto_merge()
        persist()
        st.session_state.pending.pop(market, None)
        st.session_state.reports.pop(market, None)
        st.session_state.cfg.pop(market, None)
        flash("success", f"Imported {total} row(s) into {market}. Developer name "
                         "variants are flagged on the Data Manager page — nothing was "
                         "merged automatically.")
        st.rerun()
    if c2.button("Cancel", key=f"canc_{market}", **WIDE_BTN):
        st.session_state.pending.pop(market, None)
        st.rerun()


def _apply_auto_merge():
    """
    Fold obvious name variants together across every market, automatically.

    Only unambiguous groups are applied: a short spelling is merged when
    exactly one fuller name could own it. Anything a human would have to guess
    at ("Amol" with both an Amol Dohale and an Amol Gaikwad on the team) is
    returned instead, and surfaced as a warning rather than silently decided.
    """
    db, s = st.session_state.db, st.session_state.settings
    names = set()
    for m in store.MARKETS:
        for r in db["tasks"].get(m, []):
            if r.get("dev_raw"):
                names.add(r["dev_raw"])
        for b in db["monthly"].get(m, []):
            for d in b.get("developers", []):
                if d.get("raw"):
                    names.add(d["raw"])
    merged, ambiguous = nz.auto_merge_map(names, s.get("dev_aliases"))
    s["dev_aliases"] = merged
    st.session_state.reports.clear()
    return merged, ambiguous


def _month_choices(det, periods):
    seen, out = set(), []
    for cand in list(det["sources"].values()) + periods:
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out[:8]


def _import_ppt(market, files):
    db = st.session_state.db
    imported = 0
    for f in files:
        try:
            blocks, rep = ingest.read_pptx(f, market, filename=f.name)
        except ingest.IngestError as exc:
            st.error(f"**{f.name}** — {exc}")
            continue
        except Exception as exc:                              # noqa: BLE001
            st.error(f"**{f.name}** — this presentation could not be read. "
                     f"({type(exc).__name__})")
            continue
        store.add_monthly(db, market, blocks, f.name)
        imported += 1
        st.success(f"**{f.name}** — recovered {len(blocks)} month(s): "
                   f"{', '.join(rep['months'])}.")
        if any(b.get("observation_convention") == "overlay" for b in blocks):
            st.info(f"**{f.name}** — this deck counted observations inside its No Error "
                    "figure. They have been separated out so the totals match what the "
                    "deck published, under the current rule.")
    if imported:
        _apply_auto_merge()
        persist()
        st.session_state.reports.pop(market, None)
        st.session_state.cfg.pop(market, None)
        st.rerun()


# ==========================================================================
# selection — one calculation shared by every surface
# ==========================================================================
def default_cfg(market):
    """Everything switched on, every stored period in scope."""
    db, s = st.session_state.db, st.session_state.settings
    fac = metrics.facet_values(db, market, s)
    return {
        "years": list(fac["years"]),
        "months": sorted({m for _, m in fac["periods"]}),
        "developers": [], "categories": [], "severities": [], "environments": [],
        "weeks": [], "days": [], "qa_people": [],
        "include_monthly": True, "include_summary": True, "include_developer": True,
        "include_category": True, "include_recommendations": True,
        "include_dashboard": True, "include_aging": False, "include_critical": False,
        "want_pdf": True, "label": market, "note": "",
    }


def get_cfg(market):
    cfg = st.session_state.cfg.get(market)
    if not cfg:
        cfg = default_cfg(market)
        st.session_state.cfg[market] = cfg
    return cfg


def build_selection(market):
    """
    Resolve the configured filters, narrowed by the period chosen in the top bar.

    Returns `(sel, totals, note)` — or `(None, None, reason)` when the filters
    match nothing. Every surface calls this, so the dashboard, the PPTX, the PDF
    and the CSV are always built from exactly the same rows.
    """
    db, s = st.session_state.db, st.session_state.settings
    cfg = get_cfg(market)
    fac = metrics.facet_values(db, market, s)

    periods = [p for p in fac["periods"]
               if p[0] in cfg["years"] and p[1] in cfg["months"]]
    if not periods:
        return None, None, "No months selected — pick at least one year and one month."

    note = None
    pick = st.session_state.get("period_pick")
    if pick and pick in periods and len(periods) > 1:
        periods = [pick]
        note = (f"Narrowed to {MONTHS[pick[1] - 1]} {pick[0]} by the period picker in the "
                "top bar. Choose “All periods” there to see the whole configured range.")

    sel = metrics.select(db, market, s, {
        "periods": periods, "developers": cfg["developers"], "categories": cfg["categories"],
        "severities": cfg["severities"], "environments": cfg["environments"],
        "weeks": cfg["weeks"], "days": cfg["days"], "qa_people": cfg["qa_people"]})
    tot = metrics.totals(sel)
    if tot["total_tasks"] == 0:
        return None, None, "These filters match no tasks. Widen the selection and try again."
    return sel, tot, note


def data_warning_panel(market):
    db, s = st.session_state.db, st.session_state.settings
    for w in metrics.data_warnings(db, market, s):
        cls = "qrs-note" if w["severity"] == "warning" else "qrs-info"
        icon = "⚠️" if w["severity"] == "warning" else "ℹ️"
        md(f'<div class="{cls}">{icon} {w["text"]}</div>')
        if w["kind"] == "aliases":
            with st.expander("Show the names involved"):
                for canon, members in w["detail"].items():
                    st.write(f"**{canon}** ← {', '.join(members)}")
                st.caption("Merge them on the **Data Manager** page. Nothing is merged "
                           "automatically, because two people can genuinely share a "
                           "first name.")


# ==========================================================================
# STEP 3 — configure (inside a form -> no reruns while you set it up)
# ==========================================================================
def configure_form(market):
    db, s = st.session_state.db, st.session_state.settings
    fac = metrics.facet_values(db, market, s)
    cfg = get_cfg(market)
    month_nums = sorted({m for _, m in fac["periods"]})
    # Widget keys carry the data epoch. When an import, a delete or a restore
    # changes what is available, the form is rebuilt from scratch instead of
    # holding a stale selection that no longer exists in the options.
    ep = st.session_state.cfg_epoch

    def keep(values, allowed):
        return [v for v in values if v in allowed]

    with st.form(key=f"form_{market}_{ep}"):
        bar("Configure the report",
            "Nothing is recalculated until you press Generate")
        c1, c2, c3 = st.columns([0.95, 1.85, 1.5])
        with c1:
            years = st.multiselect("Year(s)", fac["years"],
                                   default=keep(cfg["years"], fac["years"]) or fac["years"],
                                   key=f"y_{market}_{ep}")
        with c2:
            months = st.multiselect("Month(s)", month_nums,
                                    default=keep(cfg["months"], month_nums) or month_nums,
                                    format_func=lambda m: MONTHS[m - 1],
                                    key=f"m_{market}_{ep}")
        with c3:
            devs = st.multiselect("Developer(s) — empty means all", fac["developers"],
                                  default=keep(cfg["developers"], fac["developers"]),
                                  key=f"d_{market}_{ep}")

        with st.expander("More filters — category, severity, environment, week, day, QA analyst"):
            f1, f2, f3 = st.columns(3)
            with f1:
                cats = st.multiselect("Defect category", fac["categories"],
                                      default=keep(cfg["categories"], fac["categories"]),
                                      key=f"c_{market}_{ep}")
                envs = st.multiselect("Environment", fac["environments"],
                                      default=keep(cfg["environments"], fac["environments"]),
                                      key=f"e_{market}_{ep}")
            with f2:
                sevs = st.multiselect("Severity", fac["severities"],
                                      default=keep(cfg["severities"], fac["severities"]),
                                      key=f"s_{market}_{ep}")
                qas = st.multiselect("QA analyst", fac["qa_people"],
                                     default=keep(cfg["qa_people"], fac["qa_people"]),
                                     key=f"q_{market}_{ep}")
            with f3:
                weeks = st.multiselect("ISO week", fac["weeks"],
                                       default=keep(cfg["weeks"], fac["weeks"]),
                                       key=f"w_{market}_{ep}")
                days = st.multiselect("Day of month", fac["days"],
                                      default=keep(cfg["days"], fac["days"]),
                                      key=f"day_{market}_{ep}")
            st.caption("Category and severity narrow the **defects** only — they never "
                       "remove passing tasks, which would inflate every score.")

        with st.expander("Sections to include and report options"):
            s1, s2, s3 = st.columns(3)
            inc = {
                "include_monthly": s1.checkbox("Monthly section", cfg["include_monthly"],
                                               key=f"i2_{market}_{ep}"),
                "include_summary": s2.checkbox("QA summary", cfg["include_summary"],
                                               key=f"i4_{market}_{ep}"),
                "include_developer": s3.checkbox("Developer summary", cfg["include_developer"],
                                                 key=f"i5_{market}_{ep}"),
            }
            s4, s5, s6 = st.columns(3)
            inc["include_category"] = s4.checkbox("Defect categories", cfg["include_category"],
                                                  key=f"i6_{market}_{ep}")
            inc["include_recommendations"] = s5.checkbox("Recommendations",
                                                         cfg["include_recommendations"],
                                                         key=f"i9_{market}_{ep}")
            inc["include_dashboard"] = s6.checkbox("Score dashboard (final slide)",
                                                   cfg["include_dashboard"],
                                                   key=f"i3_{market}_{ep}")
            s7, s8, s9 = st.columns(3)
            inc["include_aging"] = s7.checkbox("Aging analysis", cfg["include_aging"],
                                               key=f"i7_{market}_{ep}")
            inc["include_critical"] = s8.checkbox("Critical defects", cfg["include_critical"],
                                                  key=f"i8_{market}_{ep}")
            want_pdf = s9.checkbox("Also build PDF", cfg["want_pdf"], key=f"i10_{market}_{ep}")

            c4, c5 = st.columns([1, 2])
            label = c4.text_input("Market label on the cover", cfg["label"] or market,
                                  key=f"l_{market}_{ep}")
            note = c5.text_input("Optional note for the recommendations page", cfg["note"],
                                 key=f"n_{market}_{ep}")

        st.markdown("")
        b1, b2, _ = st.columns([1.5, 1.2, 2.3])
        gen = b1.form_submit_button("🚀   Generate report", type="primary", **WIDE_BTN)
        applied = b2.form_submit_button("Apply filters", **WIDE_BTN)

    # Read back outside the form: these are the values the user is looking at,
    # whether or not a button was pressed this run.
    cfg.update({"years": years, "months": months, "developers": devs, "categories": cats,
                "severities": sevs, "environments": envs, "weeks": weeks, "days": days,
                "qa_people": qas, "want_pdf": want_pdf, "label": label, "note": note})
    cfg.update(inc)
    st.session_state.cfg[market] = cfg
    return gen, applied


def _generate(market, sel, opts, want_pdf, slot):
    out = {"meta": {"when": datetime.now().strftime("%d %b %Y %H:%M"),
                    "period": metrics.totals(sel)["period_label"]}}
    try:
        progress_bar(slot, 8, "Preparing the report…")
        out["pptx"] = deck.build_deck(sel, opts)
        progress_bar(slot, 60, "PowerPoint ready. Building the PDF…" if want_pdf
                     else "PowerPoint ready.")
        if want_pdf:
            out["pdf"] = pdf.build_pdf(sel, opts)
        progress_bar(slot, 88, "Exporting the underlying rows…")
        out["csv"] = _csv_bytes(sel)
        progress_bar(slot, 100, "REPORT GENERATED", done=True)
    except MemoryError:
        progress_bar(slot, 100, "Could not build the report", done=False)
        st.error("The report was too large to build in memory. Try selecting fewer "
                 "months, or switch off the monthly section.")
        return False
    except Exception as exc:                                  # noqa: BLE001
        progress_bar(slot, 100, "Could not build the report", done=False)
        st.error("The report could not be generated. Nothing has been changed, so you "
                 "can adjust the filters and try again. If it keeps happening, send "
                 "the technical detail below to whoever maintains this tool.")
        with st.expander("Technical detail (for support)"):
            st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
        return False
    st.session_state.reports[market] = out
    return True


def _csv_bytes(sel):
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Market", "Developer", "QA Analyst", "Status", "Environment",
                "Category", "Severity", "Task", "Details", "Source file", "Sheet",
                "Imported at"])
    for r in sorted(sel.tasks, key=lambda x: x.get("date") or ""):
        w.writerow([r.get("date"), r.get("market"), r.get("dev"), r.get("qa"),
                    r.get("status"), r.get("env"), r.get("category") or "",
                    r.get("severity") or "", r.get("title"), r.get("details"),
                    r.get("source_file", ""), r.get("source_sheet", ""),
                    r.get("imported_at", "")])
    return buf.getvalue().encode("utf-8-sig")


# ==========================================================================
# STEP 4 — download
# ==========================================================================
def download_panel(market):
    rep = st.session_state.reports.get(market)
    if not rep:
        return False
    meta = rep["meta"]
    stem = f"{market}_QA_Report_{meta['period'].replace(' ', '_').replace('–', 'to')}"

    md('<div class="qrs-panel" style="text-align:center;padding:26px 22px 18px;'
       f'background:linear-gradient(120deg,{T.hx(T.BRAND_SOFT)},{T.hx(T.CARD_BG)} 70%)">'
       '<div style="font-size:2rem;line-height:1">🎉</div>'
       '<div style="font-weight:800;font-size:1.22rem;margin-top:6px">'
       'Your QA report is ready</div>'
       f'<div style="color:{T.hx(T.TEXT_MUTED)};font-size:.85rem;margin-top:5px">'
       f'{esc(meta["period"])} &nbsp;·&nbsp; generated {esc(meta["when"])}</div></div>')

    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇  PowerPoint (.pptx)", rep["pptx"], f"{stem}.pptx",
                       "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                       key=f"dl_pptx_{market}", type="primary", **WIDE_BTN)
    if rep.get("pdf"):
        c2.download_button("⬇  PDF (.pdf)", rep["pdf"], f"{stem}.pdf", "application/pdf",
                           key=f"dl_pdf_{market}", **WIDE_BTN)
    else:
        c2.button("PDF not generated", disabled=True, key=f"dl_none_{market}", **WIDE_BTN)
    c3.download_button("⬇  Underlying rows (.csv)", rep["csv"], f"{stem}.csv", "text/csv",
                       key=f"dl_csv_{market}", **WIDE_BTN)
    st.caption(f"Generated {meta['when']} · {meta['period']}. The dashboard below, the "
               "PPTX, the PDF and the CSV all come from the same calculation, so their "
               "numbers match exactly. Re-run Generate after changing a filter.")
    return True


# ==========================================================================
# the dashboard, on screen
# ==========================================================================
def render_dashboard(sel, tot=None):
    """The same executive dashboard the deck produces, rendered in the browser."""
    tot = tot or metrics.totals(sel)
    rows = metrics.monthly_series(sel)

    kpi_row([
        (f"{tot['total_tasks']:,}", "Total tasks audited", T.BLUE, None, "📋"),
        (f"{tot['error_free']:,}", "Error free tasks", T.GREEN,
         f"{tot['no_error']} no error + {tot['observations']} observation", "✅"),
        (f"{tot['observations']:,}", "Observations", T.TEAL, "inside error free", "📝"),
        (f"{tot['error_tasks']:,}", "Total defects", T.RED, None, "🐞"),
        (f"{tot['internal']:,}", "Internal defects", T.ORANGE,
         f"{tot['internal_pct']:.2f}% of defects", "🛡️"),
        (f"{tot['external']:,}", "External defects", T.PURPLE,
         f"{tot['external_pct']:.2f}% of defects", "🌐"),
        (f"{tot['developers']}", "Developers audited", T.BRAND, None, "👥"),
        (FS(tot["score"]), "Overall quality score", T.score_color(tot["score"]),
         T.score_band(tot["score"]), "⭐"),
    ], cols=4)

    cats = metrics.category_table(sel)
    art = _dash_charts(rows, cats, tot["error_tasks"],
                       float(sel.settings.get("target_score", 95)),
                       (tot["total_tasks"], tot["error_tasks"], tot["no_error"],
                        tot["observations"]))

    # Three tight columns squeeze every label at 100% zoom, so the trend chart
    # gets the widest share and the other two panels take what is left.
    st.markdown("")
    c1, c2, c3 = st.columns([1.42, 1.0, 1.0])
    with c1:
        bar("Quality score trend", "Monthly")
        st.image(art["trend"], **WIDE_IMG)
        scored = [r for r in rows if r["score"] is not None]
        if scored:
            best = max(scored, key=lambda r: r["score"])
            worst = min(scored, key=lambda r: r["score"])
            kpi_row([(FS(best["score"]), "Highest", T.GREEN, best["label"]),
                     (FS(worst["score"]), "Lowest", T.RED, worst["label"]),
                     (FS(tot["score"]), "Overall", T.BRAND, "pooled"),
                     (FS(tot["avg_monthly_score"]), "Avg monthly", T.PURPLE, "per month")],
                    compact=True)
            st.caption("**Overall** pools every task across the period. **Avg monthly** is "
                       "the mean of the monthly percentages. They differ when months have "
                       "very different volumes.")
    with c2:
        bar("Defect categories")
        if cats:
            st.image(art["donut"], **WIDE_IMG)
            legend = []
            for c in cats:
                col = T.hx(T.CATEGORY_COLORS.get(c["category"], T.TEXT))
                legend.append(
                    f'<div style="display:flex;align-items:center;gap:9px;padding:5px 0;'
                    f'font-size:.79rem">'
                    f'<i style="width:9px;height:9px;border-radius:50%;background:{col};'
                    f'flex:0 0 9px"></i>'
                    f'<span style="flex:1 1 auto;min-width:0;overflow:hidden;'
                    f'text-overflow:ellipsis;white-space:nowrap">{esc(c["category"])}</span>'
                    f'<b>{c["total"]}</b>'
                    f'<span style="color:{T.hx(T.TEXT_MUTED)}">({c["pct"]:.2f}%)</span>'
                    f'</div>')
            md("".join(legend))
        else:
            md('<div class="qrs-ok">No defects in this selection.</div>')
    with c3:
        bar("Top performers")
        top, bar_n = metrics.top_developers(sel, n=3)
        if top:
            rank_rows(top)
            st.caption(f"Ranked on score, minimum **{bar_n} audited tasks** to qualify.")
        else:
            st.caption("No developer data in this selection.")

    bar("Task composition")
    st.image(art["comp"], **WIDE_IMG)
    st.caption("Observations sit **inside** the error-free segment. They are never added "
               "on top of it — that would double-count the same tasks.")

    ins = metrics.insights(sel)
    if ins:
        bar("Key insights")
        cells = []
        for i, item in enumerate(ins):
            col = T.ACCENTS[i % len(T.ACCENTS)]
            cells.append(f'<div class="it"><div class="v" style="color:{T.hx(col)}">'
                         f'{esc(item["value"])}</div>'
                         f'<div class="t">{esc(item["text"])}</div></div>')
        md('<div class="qrs-ins">' + "".join(cells) + "</div>")

    recs = metrics.recommendations(sel)
    if recs:
        bar("Recommendations")
        cells = []
        for i, rec in enumerate(recs, 1):
            cells.append(
                f'<div style="display:flex;gap:12px;padding:11px 0;'
                f'border-bottom:1px solid {T.hx(T.GRID)}">'
                f'<div style="width:24px;height:24px;border-radius:8px;flex:0 0 24px;'
                f'background:{T.hx(T.soft(T.BRAND))};color:{T.hx(T.BRAND)};font-weight:800;'
                f'font-size:.74rem;display:flex;align-items:center;justify-content:center">'
                f'{i}</div><div><div style="font-weight:700;font-size:.87rem">'
                f'{esc(rec["title"])}</div>'
                f'<div style="color:{T.hx(T.TEXT_MUTED)};font-size:.79rem;margin-top:2px;'
                f'line-height:1.55">{esc(rec["text"])}</div></div></div>')
        md('<div class="qrs-panel">' + "".join(cells) + "</div>")

    with st.expander("Monthly detail and developer table"):
        st.markdown("**Month by month**")
        st.dataframe([{"Month": r["label"], "Total tasks": r["total"], "Error": r["error"],
                       "No error": r["no_error"], "Observation": r["observation"],
                       "Error free": r["error_free"], "Quality score": FS(r["score"]),
                       "Source": "Excel detail" if r["source"] == "detail" else "Imported deck"}
                      for r in rows], hide_index=True, **WIDE_DF)
        st.markdown("**Developers**")
        st.dataframe([{"Developer": d["name"], "Total": d["total"], "Error": d["error"],
                       "No error": d["no_error"], "Observation": d["observation"],
                       "Error free": d["error_free"], "Quality score": FS(d["score"])}
                      for d in metrics.developer_table(sel)], hide_index=True, **WIDE_DF)


def bump_data(market=None):
    """
    Invalidate everything derived from the stored data.

    Called after any import, delete or restore: a finished report and a set of
    filters both describe rows that may no longer exist, and the configure form
    is rebuilt so it can never offer a year that has just been deleted.
    """
    st.session_state.cfg_epoch += 1
    if market:
        st.session_state.reports.pop(market, None)
        st.session_state.cfg.pop(market, None)
    else:
        st.session_state.reports.clear()
        st.session_state.cfg.clear()


# ==========================================================================
# PAGE — home
# ==========================================================================
def page_home():
    db, s = st.session_state.db, st.session_state.settings
    market = st.session_state.market

    who = (s.get("prepared_by") or "").strip().split(" ")[0]
    md('<div class="qrs-hero"><div class="art">📈</div>'
       f'<div class="eyebrow">Welcome{" back, " + esc(who) if who else " to " + esc(APP_TITLE)}</div>'
       '<h1>Turn QA data into <span class="accent">actionable insights</span></h1>'
       '<p>Upload your audit sheets, analyse defects, compare developers and build '
       'better products — entirely offline, with every figure traceable back to the '
       'row it came from.</p>'
       '<div class="chips"><span class="chip">⚡ Automated analysis</span>'
       '<span class="chip">📊 Visual insights</span>'
       '<span class="chip">📤 Export to PPTX &amp; PDF</span>'
       '<span class="chip">🔒 Nothing leaves this machine</span></div></div>')

    if not has_data(db, market):
        empty_state("📥", f"No data stored for {market} yet",
                    "Upload an audit sheet to see the dashboard fill in.",
                    "Upload your first audit sheet", "upload", key="home_empty_cta")
        recent_activity()
        return

    fac = metrics.facet_values(db, market, s)
    pick = st.session_state.get("period_pick")
    periods = [pick] if pick else list(fac["periods"])
    sel = metrics.select(db, market, s, {"periods": periods})
    tot = metrics.totals(sel)

    # Month-on-month movement comes from the full series, so the deltas stay
    # meaningful even when the top bar has narrowed the view to one month.
    series = metrics.monthly_series(metrics.select(db, market, s,
                                                   {"periods": list(fac["periods"])}))
    cur = prev = None
    if series:
        idx = len(series) - 1
        if pick:
            for i, r in enumerate(series):
                if (r.get("year"), r.get("month")) == pick:
                    idx = i
                    break
        cur = series[idx]
        prev = series[idx - 1] if idx > 0 else None

    # The headline value can cover several months, so the movement line names
    # the two months it actually compares rather than implying the total moved.
    span = (f"{cur['label'].split()[0]} vs {prev['label']}" if cur and prev else "")

    def d(field, better="up"):
        if not cur or not prev:
            return '<span style="opacity:.75">No earlier month to compare</span>'
        return delta(cur[field], prev[field], better=better, suffix=span)

    kpi_row([
        (f"{tot['total_tasks']:,}", "Total tasks audited", T.BLUE, d("total"), "📋"),
        (f"{tot['error_free']:,}", "Error free tasks", T.GREEN, d("error_free"), "✅"),
        (f"{tot['observations']:,}", "Observations", T.TEAL, d("observation", "down"), "📝"),
        (f"{tot['error_tasks']:,}", "Total defects", T.RED, d("error", "down"), "🐞"),
        (f"{tot['developers']}", "Developers audited", T.BRAND,
         f"across {len(fac['periods'])} stored period(s)", "👥"),
        (FS(tot["score"]), "Overall quality score", T.score_color(tot["score"]),
         d("score"), "⭐"),
    ], cols=6)

    bar("Quick actions", "Everything you need to produce a report")
    q1, q2, q3, q4 = st.columns(4)
    if q1.button("☁️  Upload new file", type="primary", key="qa_upload", **WIDE_BTN):
        go("upload")
    if q2.button("📊  Open full results", key="qa_results", **WIDE_BTN):
        go("results")
    if q3.button("👥  Manage developers", key="qa_devs", **WIDE_BTN):
        go("data")
    if q4.button("⚖️  Compare markets", key="qa_cmp", **WIDE_BTN):
        go("compare")

    cats = metrics.category_table(sel)
    art = _dash_charts(metrics.monthly_series(sel), cats, tot["error_tasks"],
                       float(s.get("target_score", 95)),
                       (tot["total_tasks"], tot["error_tasks"], tot["no_error"],
                        tot["observations"]))
    c1, c2 = st.columns([1.5, 1.0])
    with c1:
        bar("Quality score trend", f"{market} · {tot['period_label']}")
        st.image(art["trend"], **WIDE_IMG)
    with c2:
        bar("Defect category breakdown")
        if cats:
            st.image(art["donut"], **WIDE_IMG)
        else:
            md('<div class="qrs-ok">No defects in this selection — nothing to break down.</div>')

    c3, c4 = st.columns([1.0, 1.5])
    with c3:
        bar("Top performers")
        top, bar_n = metrics.top_developers(sel, n=3)
        if top:
            rank_rows(top)
            st.caption(f"Minimum **{bar_n} audited tasks** to qualify.")
        else:
            st.caption("No developer data in this selection.")
    with c4:
        bar("Key insights")
        ins = metrics.insights(sel)
        if ins:
            cells = []
            for i, item in enumerate(ins):
                col = T.ACCENTS[i % len(T.ACCENTS)]
                cells.append(f'<div class="it"><div class="v" style="color:{T.hx(col)}">'
                             f'{esc(item["value"])}</div>'
                             f'<div class="t">{esc(item["text"])}</div></div>')
            md('<div class="qrs-ins">' + "".join(cells) + "</div>")
        else:
            st.caption("Insights appear once there are tasks in the selection.")

    data_warning_panel(market)
    recent_activity()


def recent_activity():
    db = st.session_state.db
    bar("Recent activity", "Every import, restore and reset, oldest kept")
    src = list(reversed(db.get("sources", [])))[:6]
    if not src:
        md('<div class="qrs-info">Nothing imported yet. The history records every file '
           'you read, and survives a reset.</div>')
        return
    rows = ['<table class="qrs-table"><tr><th>When</th><th>Market</th><th>Action</th>'
            '<th>File</th><th class="num">Records</th><th>Status</th></tr>']
    for x in src:
        rows.append(f'<tr><td>{esc(x["at"].replace("T", " "))}</td>'
                    f'<td>{esc(x["market"])}</td><td>{esc(x["kind"].upper())}</td>'
                    f'<td>{esc(x["name"])}</td><td class="num">{x["rows"]}</td>'
                    f'<td>{pill("Completed", T.GREEN)}</td></tr>')
    md("".join(rows) + "</table>")


# ==========================================================================
# PAGE — upload & configure
# ==========================================================================
def page_upload(prog_slot):
    db = st.session_state.db
    market = st.session_state.market
    pend = st.session_state.pending.get(market)

    page_header("Upload & Configure",
                f"Upload your {market} QA files and set the report up.",
                crumb=f"Workflow &nbsp;/&nbsp; <b>{esc(market)}</b>")

    if pend:
        active = 2
    elif not has_data(db, market):
        active = 1
    elif st.session_state.reports.get(market):
        active = 4
    else:
        active = 3
    steps(active)

    upload_cards(market)

    if pend:
        _review_and_confirm(market, pend)
        return
    if not has_data(db, market):
        md('<div class="qrs-info">ℹ️ Read an audit sheet above to unlock the report '
           'configuration below.</div>')
        return

    data_warning_panel(market)
    gen, applied = configure_form(market)

    sel, tot, note = build_selection(market)
    if sel is None:
        md(f'<div class="qrs-note">⚠️ {esc(note)}</div>')
        return
    if note:
        md(f'<div class="qrs-info">ℹ️ {esc(note)}</div>')
    if applied:
        st.success("Filters applied — the figures below and any report you generate "
                   "now use this selection.")

    cfg = get_cfg(market)
    bar("Review the metrics", "The same numbers the report will carry")
    kpi_row([
        (f"{tot['total_tasks']:,}", "Total tasks audited", T.BLUE, None, "📋"),
        (f"{tot['error_free']:,}", "Error free tasks", T.GREEN, None, "✅"),
        (f"{tot['error_tasks']:,}", "Total defects", T.RED, None, "🐞"),
        (f"{tot['developers']}", "Developers audited", T.BRAND, None, "👥"),
        (FS(tot["score"]), "Overall quality score", T.score_color(tot["score"]),
         T.score_band(tot["score"]), "⭐"),
    ], cols=5)
    st.caption(f"Selection: **{tot['period_label']}** · {len(sel.tasks):,} task row(s). "
               "Open **Results & Insights** for the full dashboard.")

    if gen:
        opts = {"market_label": cfg["label"] or market,
                "org": st.session_state.settings.get("org_name", "BMW"),
                "prepared_by": st.session_state.settings.get("prepared_by", ""),
                "notes": cfg["note"]}
        for k in ("include_monthly", "include_summary", "include_developer",
                  "include_category", "include_recommendations", "include_dashboard",
                  "include_aging", "include_critical"):
            opts[k] = cfg[k]
        if _generate(market, sel, opts, cfg["want_pdf"], prog_slot):
            flash("success", "Report generated. Download it below, or scroll on for the "
                             "full analysis.")
            go("results")


# ==========================================================================
# PAGE — results & insights
# ==========================================================================
def page_results():
    db = st.session_state.db
    market = st.session_state.market

    if not has_data(db, market):
        page_header("Results & Insights", f"Nothing stored for {market} yet.")
        empty_state("📊", "No analysis to show",
                    "Upload an audit sheet and the full dashboard appears here.",
                    "Go to Upload & Configure", "upload", key="res_empty_cta")
        return

    sel, tot, note = build_selection(market)
    cfg = get_cfg(market)
    label = cfg["label"] or market

    if sel is None:
        page_header("Results & Insights", f"{market}")
        md(f'<div class="qrs-note">⚠️ {esc(note)}</div>')
        if st.button("Adjust the filters", type="primary", key="res_fix", **WIDE_BTN):
            go("upload")
        return

    ready = bool(st.session_state.reports.get(market))
    badge = pill("Report generated", T.GREEN) if ready else pill("Preview", T.ORANGE)
    h1, h2 = st.columns([3, 1.5])
    with h1:
        md(f'<div class="qrs-crumb">Results &nbsp;/&nbsp; <b>{esc(market)}</b></div>'
           f'<div class="qrs-page-title">{esc(label)} QA summary report &nbsp;{badge}</div>'
           f'<div class="qrs-page-sub">{esc(tot["period_label"])} · '
           f'{len(sel.tasks):,} task rows · prepared for '
           f'{esc(st.session_state.settings.get("org_name") or "—")}</div>')
    with h2:
        if st.button("⚙️  Change filters", key="res_cfg", **WIDE_BTN):
            go("upload")
        if not ready and st.button("🚀  Generate report", type="primary", key="res_gen",
                                   **WIDE_BTN):
            go("upload")

    if note:
        md(f'<div class="qrs-info">ℹ️ {esc(note)}</div>')

    download_panel(market)
    render_dashboard(sel, tot=tot)


# ==========================================================================
# PAGE — compare
# ==========================================================================
def page_compare():
    db, s = st.session_state.db, st.session_state.settings
    page_header("Compare", "Put markets side by side over the same years.")

    live = [m for m in store.MARKETS if has_data(db, m)]
    if len(live) < 2:
        empty_state("⚖️", "At least two markets are needed",
                    f"Data is loaded for {len(live)} market(s). Import another market "
                    "to compare them.", "Go to Upload & Configure", "upload",
                    key="cmp_empty_cta")
        return

    with st.form("cmp"):
        bar("Choose what to compare")
        c1, c2 = st.columns(2)
        picked = c1.multiselect("Markets", live, default=live)
        all_years = sorted({y for m in live for y, _ in metrics.available_periods(db, m)})
        years = c2.multiselect("Year(s)", all_years, default=all_years)
        st.markdown("")
        gc1, _gc2 = st.columns([1, 3])
        go_cmp = gc1.form_submit_button("📊   Compare", type="primary", **WIDE_BTN)

    if not go_cmp or not picked:
        md('<div class="qrs-info">ℹ️ Choose the markets and years, then press '
           '<b>Compare</b>.</div>')
        return

    series, summary, scored = {}, [], []
    for m in picked:
        periods = [p for p in metrics.available_periods(db, m) if p[0] in years]
        if not periods:
            continue
        sel = metrics.select(db, m, s, {"periods": periods})
        series[m] = metrics.monthly_series(sel)
        t = metrics.totals(sel)
        summary.append({"Market": m, "Tasks": t["total_tasks"], "Error free": t["error_free"],
                        "Observations": t["observations"], "Defects": t["error_tasks"],
                        "Developers": t["developers"],
                        "Overall score": FS(t["score"]),
                        "Avg monthly": FS(t["avg_monthly_score"]),
                        "Period": t["period_label"]})
        if t["score"] is not None:
            scored.append((m, t["score"], t["total_tasks"]))

    if not summary:
        md('<div class="qrs-note">⚠️ Nothing matched those years.</div>')
        return

    bar("Overall quality score")
    kpi_row([(FS(sc), m, T.score_color(sc), f"{n:,} tasks audited", "🏁")
             for m, sc, n in scored] or [("N/A", "No scored market", T.TEXT_MUTED, None)])

    bar("Side by side")
    st.dataframe(summary, hide_index=True, **WIDE_DF)
    st.image(charts.market_compare(series, w=11.0, h=3.8), **WIDE_IMG)
    st.caption("Each market is scored on its own audited volume, so a market with far "
               "fewer tasks will move more sharply month to month.")

    if len(scored) > 1:
        bar("Comparison insights")
        scored.sort(key=lambda x: -x[1])
        best = scored[0]
        cells = [f'<div class="it"><div class="v" style="color:{T.hx(T.GREEN)}">'
                 f'{esc(best[0])}</div><div class="t">has the highest quality score at '
                 f'{FS(best[1])} over {best[2]:,} audited tasks.</div></div>']
        for m, sc, n in scored[1:]:
            gap = best[1] - sc
            cells.append(f'<div class="it"><div class="v" '
                         f'style="color:{T.hx(T.score_color(sc))}">{gap:.2f} pts</div>'
                         f'<div class="t">{esc(m)} sits {gap:.2f} points below '
                         f'{esc(best[0])} ({FS(sc)} over {n:,} tasks).</div></div>')
        md('<div class="qrs-ins">' + "".join(cells) + "</div>")


def refresh_forms():
    """
    Lighter than `bump_data`: the rows are unchanged, but what they resolve to
    is. Finished reports are dropped and the configure form is rebuilt, while
    the user's section choices and filters survive.
    """
    st.session_state.reports.clear()
    st.session_state.cfg_epoch += 1


# ==========================================================================
# PAGE — data manager
# ==========================================================================
def page_data():
    page_header("Data Manager",
                "Merge developer names, manage stored periods and keep backups.")
    t1, t2, t3, t4 = st.tabs(["👥  Developer name merging", "🗓  Stored periods",
                              "🧾  Import history", "🛠  Maintenance"])
    with t1:
        _dm_names()
    with t2:
        _dm_periods()
    with t3:
        _dm_history()
    with t4:
        _dm_maintenance()


def _dm_names():
    db, s = st.session_state.db, st.session_state.settings
    st.caption("Audit sheets spell the same person several ways. Nothing is merged "
               "automatically — two people can genuinely share a first name, so "
               "ambiguity is flagged for you to decide.")

    all_raw = sorted({r.get("dev_raw") for m in store.MARKETS
                      for r in db["tasks"].get(m, []) if r.get("dev_raw")})
    aliases = dict(s.get("dev_aliases") or {})

    if not all_raw:
        md('<div class="qrs-info">ℹ️ No task-level data loaded yet.</div>')
        return

    lookup = nz.build_alias_lookup(aliases)
    grouped = {}
    for raw in all_raw:
        grouped.setdefault(nz.resolve_name(raw, lookup), []).append(raw)

    confident, ambiguous = nz.classify_name_groups(all_raw)
    pending = {c: m for c, m in confident.items()
               if len({nz.resolve_name(x, lookup) for x in m}) > 1}
    still = {c: v for c, v in ambiguous.items()
             if len({nz.resolve_name(x, lookup) for x in v["members"]}) > 1}

    if pending:
        md(f'<div class="qrs-note">⚠️ {len(pending)} clear name variant group(s) are not '
           'merged yet.</div>')
    elif not still:
        md('<div class="qrs-ok">✅ All clear name variants are already merged.</div>')

    left, right = st.columns([1.55, 1.0])

    with left:
        bar("Current grouping", f"{len(grouped)} developer(s) · {len(all_raw)} spellings")
        st.dataframe([{"Counted as": k, "Spellings in the sheets": ", ".join(v),
                       "Variants": len(v)} for k, v in sorted(grouped.items())],
                     hide_index=True, **WIDE_DF)

        if pending:
            bar("Clear variants", "Safe to merge")
            for canon, members in pending.items():
                st.write(f"**{canon}** ← {', '.join(members)}")
            if st.button("Merge all clear variants", type="primary", key="dm_merge_all",
                         **WIDE_BTN):
                _apply_auto_merge()
                persist()
                refresh_forms()
                flash("success", "Clear name variants merged.")
                st.rerun()

        if still:
            bar("Ambiguous", "Needs your decision")
            for canon, info in still.items():
                md(f'<div class="qrs-note">⚠️ {esc(info["reason"])}</div>')
                cc1, cc2 = st.columns([3, 1])
                pickn = cc1.selectbox(f"Count “{info['short']}” as",
                                      ["Leave separate"] + info["rivals"],
                                      key=f"amb_{canon}")
                if cc2.button("Apply", key=f"ambb_{canon}", **WIDE_BTN):
                    if pickn != "Leave separate":
                        host = nz.display_name(pickn)
                        aliases[host] = sorted(set(aliases.get(host, []))
                                               | {pickn, info["short"]})
                        s["dev_aliases"] = aliases
                        persist()
                        refresh_forms()
                    st.rerun()

    with right:
        bar("Merge names manually")
        with st.container(border=True):
            keep_as = st.selectbox("Count everything as", sorted(grouped.keys()),
                                   key="dm_keep")
            fold = st.multiselect("Fold these spellings in", all_raw, key="dm_fold")
            if st.button("Apply merge", disabled=not fold, type="primary",
                         key="dm_manual", **WIDE_BTN):
                aliases[keep_as] = sorted(set(aliases.get(keep_as, [])) | set(fold))
                s["dev_aliases"] = aliases
                persist()
                refresh_forms()
                flash("success", f"{len(fold)} spelling(s) now count as {keep_as}.")
                st.rerun()

        bar("Undo a merge")
        with st.container(border=True):
            if aliases:
                drop = st.selectbox("Remove grouping for", sorted(aliases.keys()),
                                    key="dm_drop")
                if st.button("Remove grouping", key="dm_undo", **WIDE_BTN):
                    aliases.pop(drop, None)
                    s["dev_aliases"] = aliases
                    persist()
                    refresh_forms()
                    flash("success", f"Grouping for {drop} removed.")
                    st.rerun()
            else:
                st.caption("No merges defined.")


def _dm_periods():
    db = st.session_state.db
    bar("Stored periods", "Everything currently held, by market")
    rows = []
    for m in store.MARKETS:
        for (y, mo) in metrics.available_periods(db, m):
            n_t = sum(1 for r in db["tasks"].get(m, []) if r["year"] == y and r["month"] == mo)
            rows.append({"Market": m, "Period": f"{MONTHS[mo - 1]} {y}", "Task rows": n_t,
                         "Source": "Excel detail" if n_t else "Imported deck",
                         "_k": (m, y, mo)})
    if not rows:
        md('<div class="qrs-info">ℹ️ Nothing stored yet.</div>')
        return
    st.dataframe([{k: v for k, v in r.items() if k != "_k"} for r in rows],
                 hide_index=True, **WIDE_DF)
    d1, d2 = st.columns([3, 1])
    pick = d1.selectbox("Delete a period",
                        [f"{r['Market']} — {r['Period']}" for r in rows], key="dm_del_pick")
    if d2.button("Delete", key="dm_del", **WIDE_BTN):
        key = next(r["_k"] for r in rows if f"{r['Market']} — {r['Period']}" == pick)
        store.backup_db("before_delete")
        n = store.delete_period(db, *key)
        persist()
        bump_data()
        flash("success", f"Removed {n} record(s) for {pick}.")
        st.rerun()
    st.caption("A backup is written before anything is deleted.")


def _dm_history():
    db = st.session_state.db
    bar("Import history", "Preserved across every reset, including Clear all data")
    src = list(reversed(db.get("sources", [])))[:40]
    if not src:
        md('<div class="qrs-info">ℹ️ No imports yet.</div>')
        return
    st.dataframe([{"When": x["at"].replace("T", " "), "Market": x["market"],
                   "Action": x["kind"].upper(), "File": x["name"], "Records": x["rows"],
                   "Replaced": x.get("replaced", 0),
                   "Periods": ", ".join(x.get("periods", []))} for x in src],
                 hide_index=True, **WIDE_DF)


def _dm_maintenance():
    db = st.session_state.db
    bar("Database maintenance")
    m1, m2, m3 = st.columns(3)
    with m1:
        with st.container(border=True):
            md('<div style="font-weight:700;font-size:.88rem">💾 Back up database</div>'
               f'<div style="color:{T.hx(T.TEXT_MUTED)};font-size:.76rem;margin:4px 0 9px">'
               'Writes a dated copy alongside your data.</div>')
            if st.button("Back up now", key="dm_backup", **WIDE_BTN):
                path = store.backup_db("manual")
                if path:
                    st.success(f"Saved to `{os.path.basename(path)}`")
                else:
                    st.info("Nothing to back up — this session keeps no files on disk.")
    with m2:
        with st.container(border=True):
            md('<div style="font-weight:700;font-size:.88rem">📤 Export database</div>'
               f'<div style="color:{T.hx(T.TEXT_MUTED)};font-size:.76rem;margin:4px 0 9px">'
               'One JSON file holding every market.</div>')
            st.download_button("Export (.json)", store.export_bytes(db),
                               "qa_report_studio_database.json", "application/json",
                               key="dm_export", **WIDE_BTN)
    with m3:
        with st.container(border=True):
            md('<div style="font-weight:700;font-size:.88rem">🧹 Clear one market</div>'
               f'<div style="color:{T.hx(T.TEXT_MUTED)};font-size:.76rem;margin:4px 0 9px">'
               'Import history is always kept.</div>')
            wipe = st.selectbox("Market", ["—"] + store.MARKETS, key="dm_wipe",
                                label_visibility="collapsed")
            if st.button("Clear selected market", disabled=wipe == "—", key="dm_wipe_go",
                         **WIDE_BTN):
                store.backup_db("before_clear")
                n = store.clear_market(db, wipe)
                persist()
                bump_data(wipe)
                flash("success", f"Cleared {n} record(s) from {wipe}. "
                                 "A backup was saved first.")
                st.rerun()

    bar("Restore a database", "Replaces everything currently stored")
    st.caption("Loads a file saved with Export database. On a hosted server this is how "
               "you pick up where you left off.")
    r1, r2 = st.columns([3, 1])
    up = r1.file_uploader("Database file (.json)", type=["json"],
                          key=f"restore_{st.session_state.upload_epoch}",
                          label_visibility="collapsed")
    if r2.button("Restore", disabled=up is None, type="primary", key="dm_restore",
                 **WIDE_BTN):
        try:
            restored, counts = store.import_bytes(up.getvalue())
        except ValueError as exc:
            st.error(str(exc))
        else:
            store.backup_db("before_restore")
            st.session_state.db = restored
            _apply_auto_merge()
            persist()
            st.session_state.upload_epoch += 1
            bump_data()
            flash("success", "Database restored — "
                             + ", ".join(f"{m}: {n} record(s)" for m, n in counts.items()))
            st.rerun()


# ==========================================================================
# PAGE — settings
# ==========================================================================
def page_settings():
    s, db = st.session_state.settings, st.session_state.db
    page_header("Settings", "Branding, benchmarks, appearance and stored data.")

    with st.form("settings_form"):
        c1, c2 = st.columns(2)
        with c1:
            bar("Organisation / brand")
            org = st.text_input("Brand name", s.get("org_name", "BMW"))
            prep = st.text_input("Prepared by", s.get("prepared_by", ""),
                                 placeholder="Your name (optional)")
            st.caption("Both appear on the cover of every generated PPTX and PDF.")
        with c2:
            bar("Score benchmarks")
            target = st.number_input("Target score (%)", 50.0, 100.0,
                                     float(s.get("target_score", 95.0)), 0.5)
            watch = st.number_input("Watch benchmark (%)", 50.0, 100.0,
                                    float(s.get("watch_score", 90.0)), 0.5)
            st.caption("A score at or above the target is green, above the watch "
                       "benchmark amber, and below it red — everywhere in the product.")
        st.markdown("")
        sc1, _sc2 = st.columns([1, 3])
        saved = sc1.form_submit_button("💾   Save changes", type="primary", **WIDE_BTN)

    if watch > target:
        md('<div class="qrs-note">⚠️ The watch benchmark sits above the target — '
           'check these values.</div>')
    if saved:
        s["org_name"], s["prepared_by"] = org, prep
        s["target_score"], s["watch_score"] = float(target), float(watch)
        store.save_settings(s)
        refresh_forms()
        flash("success", "Settings saved.")
        st.rerun()

    bar("Appearance")
    with st.container(border=True):
        active = "Dark" if st.session_state.dark else "Light"
        md(f'Current theme: {pill(active, T.BRAND)}')
        st.caption(
            "The theme is set once, in **`.streamlit/config.toml`** next to the app, "
            "and covers everything — this page, the charts and Streamlit's own tables "
            "and dropdowns. Comment out the light block in that file, uncomment the "
            "dark one and restart. It is not a button here on purpose: a switch that "
            "only recoloured half the page would be worse than no switch at all.")

    bar("Data & storage")
    with st.container(border=True):
        counts = {m: len(db["tasks"].get(m, [])) for m in store.MARKETS}
        md(" ".join(pill(f"{m}: {n:,} rows", T.BRAND if n else T.TEXT_MUTED)
                    for m, n in counts.items())
           + f' {pill("Storage: " + store.storage_mode(), T.BLUE)}')
        st.markdown("")
        d1, d2 = st.columns(2)
        d1.download_button("📤  Export database (.json)", store.export_bytes(db),
                           "qa_report_studio_database.json", "application/json",
                           key="set_export", **WIDE_BTN)
        if d2.button("🗄  Open Data Manager", key="set_dm", **WIDE_BTN):
            go("data")

    bar("Reset")
    with st.container(border=True):
        st.caption("Clears every market so you can upload fresh. Your import history is "
                   "kept, and a backup is written first.")
        if not st.session_state.confirm_clear:
            rc1, _rc2 = st.columns([1, 3])
            if rc1.button("🗑  Clear all data", key="set_clear", **WIDE_BTN):
                st.session_state.confirm_clear = True
                st.rerun()
        else:
            md('<div class="qrs-note">⚠️ This removes all task rows and imported months '
               'from all three markets. Import history is preserved.</div>')
            c1, c2, _ = st.columns([1, 1, 2])
            if c1.button("Yes, clear everything", type="primary", key="set_clear_yes",
                         **WIDE_BTN):
                store.backup_db("before_clear_all")
                n = store.clear_all_data(db)
                persist()
                st.session_state.pending.clear()
                st.session_state.confirm_clear = False
                st.session_state.upload_epoch += 1
                bump_data()
                flash("success", f"Cleared {n} record(s) from all markets. "
                                 "A backup was saved to data/backups and the import "
                                 "history was kept.")
                st.rerun()
            if c2.button("Cancel", key="set_clear_no", **WIDE_BTN):
                st.session_state.confirm_clear = False
                st.rerun()


# ==========================================================================
# PAGE — help
# ==========================================================================
def page_help():
    page_header("Help", "How every number on the page is worked out.")

    bar("How the quality score works")
    st.markdown("""
An **observation** is a task that is error free but carries a remark. It is a
*subset* of the error-free tasks, never an extra bucket on top of them.

```
Error-Free Tasks = No Error + Observation
Total Tasks      = Error + Error-Free Tasks
Quality Score    = Error-Free Tasks ÷ Total Tasks × 100
```

Worked example — Total 20, Error 2, No Error 15, Observation 3:

```
Error-Free    = 15 + 3 = 18
Total Tasks   =  2 + 18 = 20
Quality Score = 18 / 20 = 90.00%
```

Adding `Error + No Error + Observation + Error-Free` would double-count the
error-free tasks. Nothing in this app does that.

**Zero tasks → the score is N/A**, never 100%.
""")

    bar("Two headline scores, and why they differ")
    st.markdown("""
- **Overall Quality Score** — pooled: `SUM(Error-Free) ÷ SUM(Total)`. This is the
  headline figure on every report.
- **Average Monthly Quality Score** — the mean of the monthly percentages.

They diverge when months have very different volumes. A 100% month with 4 tasks
lifts the *average* far more than it lifts the *overall*. Both are shown, always
labelled.
""")

    bar("Imported decks use an older convention")
    st.markdown("""
Decks issued before this tool counted observations **inside** the No Error
figure, so a row read `0 error, 19 no-error, 3 observation, Grand Total 19`.
Under the current rule those three counts are separate. The importer detects the
old convention and lifts the observations out of No Error, so an imported month
keeps exactly the totals it was published with instead of gaining phantom tasks.
""")

    bar("What gets tidied automatically")
    st.markdown("""
| In the sheet | Becomes |
|---|---|
| `First Time Correct`, `FTC`, `Pass` | No Error |
| `Error`, `Fail`, `Defect` | Error |
| `Observation`, `Obs` | Observation |
| `Test` | Internal — caught before release |
| `Live`, `live` | External |
| `Design layout Related` / `Design Related` | Design Related |
| `Redirected link` / `Redirect Links Related` | Redirect Links |

Developer name variants are **flagged, not merged** — two people can share a
first name, so the decision is yours on the Data Manager page.
""")

    bar("Finding your way around")
    st.markdown("""
| Page | What it is for |
|---|---|
| **Home** | The headline numbers for the market chosen in the top bar. |
| **Upload & Configure** | Read a sheet, review the mapping, set the filters, generate. |
| **Results & Insights** | The full dashboard, plus the PPTX, PDF and CSV downloads. |
| **Data Manager** | Developer name merging, stored periods, import history, backups. |
| **Compare** | Two or more markets side by side over the same years. |
| **Settings** | Brand, benchmarks, appearance and resetting the data. |

The **market** and **period** pickers in the top bar apply everywhere. Setting
the period to a single month narrows the dashboard *and* the report that is
generated from it, so what you see is always what you download.
""")

    bar("Working offline")
    st.markdown("""
Nothing calls the internet. There is no API key, no account, no usage limit and
no external database — everything lives in `data/database.json`, which you can
copy, back up or hand to a colleague.
""")


# ==========================================================================
def main():
    boot()
    st.markdown(T.app_css(dark=st.session_state.dark), unsafe_allow_html=True)

    sidebar()
    query = topbar()

    # Claimed before the page body is drawn, so the progress bar sits at the top
    # and stays put while you scroll, rather than appearing halfway down next to
    # whichever step happened to render it.
    prog_slot = st.empty()
    if any(st.session_state.reports.get(m) for m in store.MARKETS):
        progress_bar(prog_slot, 100, "REPORT GENERATED", done=True)

    storage_notice()
    drain_flash()

    if query:
        search_results(query)
        return

    page = st.session_state.nav
    if page == "home":
        page_home()
    elif page == "upload":
        page_upload(prog_slot)
    elif page == "results":
        page_results()
    elif page == "data":
        page_data()
    elif page == "compare":
        page_compare()
    elif page == "settings":
        page_settings()
    else:
        page_help()


if __name__ == "__main__":
    main()
