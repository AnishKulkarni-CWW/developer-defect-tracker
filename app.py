"""
QA Report Studio — Streamlit front end.

Design rule that shapes this file: nothing expensive runs while the user is
setting up a report. Every filter lives inside an `st.form`, so changing a
dropdown does not rerun the script; charts, decks and PDFs are built only when
Generate is pressed. Finished files are held in session state so a download
click never rebuilds them.

The workflow follows seven visible steps:
    1 Upload  2 Review mapping  3 Validate  4 Review metrics
    5 Configure report  6 Generate  7 Download
"""

from __future__ import annotations

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
# Streamlit reruns the whole script on any widget interaction, and all three
# market tabs render on every run. Without a cache the browser dashboard would
# redraw every chart each time — exactly the mid-work processing this app is
# built to avoid. Keyed on the figures themselves, so a cache entry is reused
# until the underlying numbers actually change.
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
MONTHS = metrics.MONTH_FULL
FS = metrics.fmt_score

st.set_page_config(page_title=APP_TITLE, page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown(T.app_css(), unsafe_allow_html=True)


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


def persist():
    store.save_db(st.session_state.db)
    store.save_settings(st.session_state.settings)


def flash(kind, msg):
    st.session_state.flash.append((kind, msg))


def drain_flash():
    for kind, msg in st.session_state.flash:
        getattr(st, kind)(msg)
    st.session_state.flash = []


def progress_bar(slot, pct, message, done=False):
    """
    Draw the app's own progress bar in the sticky strip under the masthead.

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


def has_data(db, market):
    return bool(db["tasks"].get(market)) or bool(db["monthly"].get(market))


# ==========================================================================
# view helpers
# ==========================================================================
def bar(label):
    st.markdown(f'<div class="qrs-bar">{label.upper()}</div>', unsafe_allow_html=True)


def kpi_row(items, compact=False):
    """
    items: [(value, label, colour, sub_or_None)]

    `compact` shrinks the number so a four-across row still fits inside a
    two-thirds-width column at 100% zoom. Streamlit's own st.metric truncates
    "94.05%" to "9…" at that width, which is worse than useless.
    """
    cls = "qrs-kpi small" if compact else "qrs-kpi"
    html = [f'<div class="qrs-kpis{" tight" if compact else ""}">']
    for value, label, color, sub in items:
        html.append(f'<div class="{cls}"><div class="v" style="color:{T.hx(color)}">{value}</div>'
                    f'<div class="l">{label}</div>'
                    + (f'<div class="s">{sub}</div>' if sub else "") + "</div>")
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def steps(active):
    """The seven-step workflow indicator."""
    names = ["Upload", "Review mapping", "Validate", "Review metrics",
             "Configure", "Generate", "Download"]
    cells = []
    for i, n in enumerate(names, 1):
        if i < active:
            bg, fg, mark = "#E8F3EA", T.hx(T.GREEN), "✓"
        elif i == active:
            bg, fg, mark = T.hx(T.NAVY), "#FFFFFF", str(i)
        else:
            bg, fg, mark = "#EDF1F8", T.hx(T.TEXT_MUTED), str(i)
        cells.append(
            f'<div style="flex:1;text-align:center;background:{bg};color:{fg};'
            f'padding:7px 4px;border-radius:8px;font-size:.72rem;font-weight:700;">'
            f'{mark} &nbsp;{n}</div>')
    st.markdown('<div style="display:flex;gap:6px;margin:6px 0 14px;">'
                + "".join(cells) + "</div>", unsafe_allow_html=True)


def storage_notice():
    """
    Say plainly what happens to the data, because the answer differs between a
    laptop and a shared server and getting it wrong loses someone's work.
    """
    if store.storage_mode() != "session":
        return
    st.markdown(
        '<div class="qrs-note">☁️ <b>Running on a hosted server.</b> Nothing is saved to '
        'disk here: your data lives in this browser session only, and is cleared when '
        'the tab closes or the server restarts. Other people using this link get their '
        'own separate copy. Use <b>Export database</b> on the Data manager tab to keep '
        'your work, and <b>Restore database</b> to pick it back up.</div>',
        unsafe_allow_html=True)


def masthead():
    st.markdown(f'<div class="qrs-head"><h1>{APP_TITLE}</h1>'
                "<p>Offline QA reporting for BMW India, C3 and Japan &mdash; "
                "Excel or CSV in, branded PPTX and PDF out.</p></div>",
                unsafe_allow_html=True)


# ==========================================================================
# sidebar
# ==========================================================================
def sidebar():
    s = st.session_state.settings
    db = st.session_state.db
    with st.sidebar:
        st.markdown("## Report settings")
        s["org_name"] = st.text_input("Organisation / brand", s.get("org_name", "BMW"))
        s["prepared_by"] = st.text_input("Prepared by", s.get("prepared_by", ""),
                                         placeholder="Your name (optional)")
        st.markdown("### Score benchmarks")
        s["target_score"] = st.number_input("Target score (%)", 50.0, 100.0,
                                            float(s.get("target_score", 95.0)), 0.5)
        s["watch_score"] = st.number_input("Watch benchmark (%)", 50.0, 100.0,
                                           float(s.get("watch_score", 90.0)), 0.5)
        if s["watch_score"] > s["target_score"]:
            st.warning("The watch benchmark sits above the target — check these values.")
        if st.button("Save settings", **WIDE_BTN):
            store.save_settings(s)
            st.success("Saved.")

        st.divider()
        st.markdown("### Reset")
        st.caption("Clears every market so you can upload fresh. Your import "
                   "history is kept, and a backup is written first.")
        if not st.session_state.confirm_clear:
            if st.button("🗑  Clear all data", **WIDE_BTN):
                st.session_state.confirm_clear = True
                st.rerun()
        else:
            st.warning("This removes all task rows and imported months from all "
                       "three markets. Import history is preserved.")
            c1, c2 = st.columns(2)
            if c1.button("Yes, clear", type="primary", **WIDE_BTN):
                store.backup_db("before_clear_all")
                n = store.clear_all_data(db)
                persist()
                st.session_state.reports.clear()
                st.session_state.pending.clear()
                st.session_state.confirm_clear = False
                st.session_state.upload_epoch += 1
                flash("success", f"Cleared {n} record(s) from all markets. "
                                 "A backup was saved to data/backups and the import "
                                 "history was kept.")
                st.rerun()
            if c2.button("Cancel", **WIDE_BTN):
                st.session_state.confirm_clear = False
                st.rerun()


# ==========================================================================
# STEP 1-3 — upload, review mapping, validate
# ==========================================================================
def upload_panel(market):
    db = st.session_state.db
    pend = st.session_state.pending.get(market)

    with st.expander("➕  Step 1 — Upload data", expanded=not has_data(db, market) or bool(pend)):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Audit sheet — Excel or CSV**")
            st.caption("The monthly QA audit log. Gives full detail, so every "
                       "filter and every chart works. .xlsx, .xlsm, .xls or .csv.")
            ep = st.session_state.upload_epoch
            files = st.file_uploader("Audit file(s)", type=["xlsx", "xlsm", "xls", "csv"],
                                     accept_multiple_files=True,
                                     key=f"xl_{market}_{ep}",
                                     label_visibility="collapsed")
            if st.button("Read file(s)", key=f"bxl_{market}", disabled=not files, **WIDE_BTN):
                _stage_excel(market, files)
                st.rerun()
        with c2:
            st.markdown("**Existing PowerPoint report** *(optional)*")
            st.caption("A deck you already issued. Recovers the monthly totals so "
                       "earlier months appear without re-keying.")
            ppts = st.file_uploader("PPTX file(s)", type=["pptx"],
                                    accept_multiple_files=True,
                                    key=f"pp_{market}_{st.session_state.upload_epoch}",
                                    label_visibility="collapsed")
            if st.button("Import PowerPoint", key=f"bpp_{market}", disabled=not ppts, **WIDE_BTN):
                _import_ppt(market, ppts)

    if pend:
        _review_and_confirm(market, pend)
        return True
    return False


def _stage_excel(market, files):
    """Parse now, but hold the rows until the user has reviewed steps 2 and 3."""
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

    bar("Step 2 — Review mapping")
    corrections = {}
    for i, item in enumerate(pend["staged"]):
        rep = item["report"]
        with st.container(border=True):
            st.markdown(f"**{rep['file']}** &nbsp;·&nbsp; sheet *{rep['sheet']}* "
                        f"&nbsp;·&nbsp; header on row {rep['header_row']}",
                        unsafe_allow_html=True)
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
            st.caption(f"Detected period(s) in the data: "
                       f"{', '.join(rep['periods'])} · {rep['rows_kept']} usable row(s)")

    bar("Step 3 — Validate")
    ok = True
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
            st.markdown(f'<div class="qrs-note"><b>{rep["file"]}</b><br>'
                        + "<br>".join(msgs) + "</div>", unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="qrs-ok"><b>{rep["file"]}</b> — '
                        f"{rep['rows_kept']} row(s) read with no issues.</div>",
                        unsafe_allow_html=True)

    c1, c2 = st.columns([1, 3])
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
        merged, ambiguous = _apply_auto_merge()
        persist()
        st.session_state.pending.pop(market, None)
        st.session_state.reports.pop(market, None)
        flash("success", f"Imported {total} row(s) into {market}. Developer name "
                         "variants are flagged on the Data manager tab — nothing was "
                         "merged automatically.")
        st.rerun()
    if c2.button("Cancel", key=f"canc_{market}", **WIDE_BTN):
        st.session_state.pending.pop(market, None)
        st.rerun()
    return ok


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
        st.rerun()


# ==========================================================================
# STEP 4 — the dashboard, on screen
# ==========================================================================
def render_dashboard(sel, market, period):
    """The same executive dashboard the deck produces, rendered in the browser."""
    tot = metrics.totals(sel)
    rows = metrics.monthly_series(sel)

    st.markdown(
        f'<div style="background:{T.hx(T.NAVY)};color:#fff;border-radius:12px;'
        f'padding:14px 20px;margin:4px 0 14px;text-align:center;font-family:'
        f'{T.FONT_HEAD},sans-serif;font-weight:800;font-size:1.18rem;letter-spacing:.6px;">'
        f"{market.upper()} QA SUMMARY REPORT &nbsp;•&nbsp; {period.upper()}</div>",
        unsafe_allow_html=True)

    kpi_row([
        (f"{tot['total_tasks']:,}", "Total tasks audited", T.BLUE, None),
        (f"{tot['error_free']:,}", "Error free tasks", T.GREEN,
         f"{tot['no_error']} no error + {tot['observations']} observation"),
        (f"{tot['observations']:,}", "Observations", T.TEAL, "inside error free"),
        (f"{tot['error_tasks']:,}", "Total defects", T.RED, None),
        (f"{tot['internal']:,}", "Internal defects", T.ORANGE, f"{tot['internal_pct']:.2f}%"),
        (f"{tot['external']:,}", "External defects", T.NAVY, f"{tot['external_pct']:.2f}%"),
        (f"{tot['developers']}", "Developers audited", T.PURPLE, None),
        (FS(tot["score"]), "Overall quality score", T.score_color(tot["score"]),
         T.score_band(tot["score"])),
    ])

    cats = metrics.category_table(sel)
    art = _dash_charts(rows, cats, tot["error_tasks"],
                       float(sel.settings.get("target_score", 95)),
                       (tot["total_tasks"], tot["error_tasks"], tot["no_error"],
                        tot["observations"]))

    # Three tight columns squeeze every label at 100% zoom, so the trend chart
    # gets its own full-width row and the other two panels share the next.
    st.markdown("")
    c1, c2, c3 = st.columns([1.42, 1.0, 1.0])
    with c1:
        bar("Quality score trend (monthly)")
        st.image(art["trend"], **WIDE_IMG)
        scored = [r for r in rows if r["score"] is not None]
        if scored:
            best = max(scored, key=lambda r: r["score"])
            worst = min(scored, key=lambda r: r["score"])
            kpi_row([(FS(best["score"]), "Highest", T.GREEN, best["label"]),
                     (FS(worst["score"]), "Lowest", T.RED, worst["label"]),
                     (FS(tot["score"]), "Overall", T.BLUE, "pooled"),
                     (FS(tot["avg_monthly_score"]), "Avg monthly", T.PURPLE, "per month")],
                    compact=True)
            st.caption("**Overall** pools every task across the period. **Avg monthly** is "
                       "the mean of the monthly percentages. They differ when months have "
                       "very different volumes.")
    with c2:
        bar("Defect category breakdown")
        if cats:
            st.image(art["donut"], **WIDE_IMG)
            html = ['<table class="qrs-table"><tr><th>Category</th>'
                    '<th class="num">No.</th><th class="num">%</th></tr>']
            for c in cats:
                col = T.hx(T.CATEGORY_COLORS.get(c["category"], T.TEXT))
                html.append(f'<tr><td style="color:{col};font-weight:600">'
                            f'{c["category"]}</td><td class="num">{c["total"]}</td>'
                            f'<td class="num">{c["pct"]:.2f}%</td></tr>')
            html.append("</table>")
            st.markdown("".join(html), unsafe_allow_html=True)
        else:
            st.markdown('<div class="qrs-ok">No defects in this selection.</div>',
                        unsafe_allow_html=True)
    with c3:
        bar("Top performers")
        top, bar_n = metrics.top_developers(sel, n=3)
        if top:
            for i, d in enumerate(top, 1):
                medal = {1: "\U0001F947", 2: "\U0001F948", 3: "\U0001F949"}[i]
                st.markdown(
                    f'<div class="qrs-card" style="padding:10px 13px;margin-bottom:7px;">'
                    f'<div style="font-weight:800;color:{T.hx(T.BLUE)};font-size:.94rem;">'
                    f'{medal} {d["name"]}</div>'
                    f'<div style="color:{T.hx(T.TEXT_MUTED)};font-size:.75rem;">'
                    f'{d["total"]} tasks &bull; {d["error_free"]} error free</div>'
                    f'<div style="font-weight:800;color:{T.hx(T.score_color(d["score"]))};'
                    f'font-size:1.02rem;">{FS(d["score"])}</div></div>',
                    unsafe_allow_html=True)
            st.caption(f"Ranked on score, minimum **{bar_n} audited tasks** to qualify.")
        else:
            st.caption("No developer data in this selection.")

    bar("Task composition")
    st.image(art["comp"], **WIDE_IMG)
    st.caption("Observations sit **inside** the error-free segment. They are never added "
               "on top of it — that would double-count the same tasks.")

    bar("Key insights")
    ins = metrics.insights(sel)
    if ins:
        cols = st.columns(len(ins))
        for col, item in zip(cols, ins):
            col.markdown(
                f'<div class="qrs-card" style="text-align:center;padding:13px 10px;">'
                f'<div style="font-weight:800;color:{T.hx(T.BLUE)};font-size:1.05rem;">'
                f'{item["value"]}</div>'
                f'<div style="color:{T.hx(T.TEXT_MUTED)};font-size:.76rem;margin-top:4px;">'
                f'{item["text"]}</div></div>', unsafe_allow_html=True)

    with st.expander("Monthly detail, developer table and recommendations"):
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
        st.markdown("**Recommendations**")
        for rec in metrics.recommendations(sel):
            st.markdown(f"**{rec['title']}** — {rec['text']}")


# ==========================================================================
# market tab
# ==========================================================================
def market_tab(market, prog_slot):
    db, s = st.session_state.db, st.session_state.settings
    reviewing = upload_panel(market)
    if reviewing:
        steps(2)
        return
    if not has_data(db, market):
        steps(1)
        st.info(f"No data stored for **{market}** yet. Upload an audit sheet above to begin.")
        return

    fac = metrics.facet_values(db, market, s)
    warnings = metrics.data_warnings(db, market, s)
    for w in warnings:
        css = "qrs-note" if w["severity"] == "warning" else "qrs-card"
        st.markdown(f'<div class="{css}">{"⚠️" if w["severity"] == "warning" else "ℹ️"} '
                    f'{w["text"]}</div>', unsafe_allow_html=True)
        if w["kind"] == "aliases":
            with st.expander("Show the names involved"):
                for canon, members in w["detail"].items():
                    st.write(f"**{canon}** ← {', '.join(members)}")
                st.caption("Merge them on the **Data manager** tab. Nothing is merged "
                           "automatically, because two people can genuinely share a "
                           "first name.")

    # ---------------- step 5: configure (inside a form -> no reruns) --------
    with st.form(key=f"form_{market}"):
        bar("Step 5 — Configure the report")
        c1, c2, c3 = st.columns([1.1, 1.4, 1.5])
        with c1:
            years = st.multiselect("Year(s)", fac["years"], default=fac["years"],
                                   key=f"y_{market}")
        month_nums = sorted({m for _, m in fac["periods"]})
        with c2:
            months = st.multiselect("Month(s)", month_nums, default=month_nums,
                                    format_func=lambda m: MONTHS[m - 1], key=f"m_{market}")
        with c3:
            devs = st.multiselect("Developer(s) — empty means all", fac["developers"],
                                  key=f"d_{market}")

        with st.expander("More filters — category, severity, environment, week, day, QA analyst"):
            f1, f2, f3 = st.columns(3)
            with f1:
                cats = st.multiselect("Defect category", fac["categories"], key=f"c_{market}")
                envs = st.multiselect("Environment", fac["environments"], key=f"e_{market}")
            with f2:
                sevs = st.multiselect("Severity", fac["severities"], key=f"s_{market}")
                qas = st.multiselect("QA analyst", fac["qa_people"], key=f"q_{market}")
            with f3:
                weeks = st.multiselect("ISO week", fac["weeks"], key=f"w_{market}")
                days = st.multiselect("Day of month", fac["days"], key=f"day_{market}")
            st.caption("Category and severity narrow the **defects** only — they never "
                       "remove passing tasks, which would inflate every score.")

        with st.expander("Sections to include and report options"):
            s1, s2, s3 = st.columns(3)
            inc = {
                "include_monthly": s1.checkbox("Monthly section", True, key=f"i2_{market}"),
                "include_summary": s2.checkbox("QA summary", True, key=f"i4_{market}"),
                "include_developer": s3.checkbox("Developer summary", True, key=f"i5_{market}"),
            }
            s4, s5, s6 = st.columns(3)
            inc["include_category"] = s4.checkbox("Defect categories", True, key=f"i6_{market}")
            inc["include_recommendations"] = s5.checkbox("Recommendations", True,
                                                         key=f"i9_{market}")
            inc["include_dashboard"] = s6.checkbox("Score dashboard (final slide)", True,
                                                   key=f"i3_{market}")
            s7, s8, s9 = st.columns(3)
            inc["include_aging"] = s7.checkbox("Aging analysis", False, key=f"i7_{market}")
            inc["include_critical"] = s8.checkbox("Critical defects", False, key=f"i8_{market}")
            want_pdf = s9.checkbox("Also build PDF", True, key=f"i10_{market}")

            c4, c5 = st.columns([1, 2])
            label = c4.text_input("Market label on the cover", market, key=f"l_{market}")
            note = c5.text_input("Optional note for the recommendations page",
                                 key=f"n_{market}")

        st.markdown("")
        go = st.form_submit_button("🚀   Step 6 — Generate report", type="primary", **WIDE_BTN)

    periods = [p for p in fac["periods"] if p[0] in years and p[1] in months]
    if not periods:
        steps(5)
        st.warning("No months selected — pick at least one year and one month.")
        return

    sel = metrics.select(db, market, s, {
        "periods": periods, "developers": devs, "categories": cats, "severities": sevs,
        "environments": envs, "weeks": weeks, "days": days, "qa_people": qas})
    tot = metrics.totals(sel)
    if tot["total_tasks"] == 0:
        steps(5)
        st.error("These filters match no tasks. Widen the selection and try again.")
        return

    steps(7 if st.session_state.reports.get(market) else (6 if go else 4))

    bar("Step 4 — Review metrics")
    render_dashboard(sel, label or market, tot["period_label"])

    if go:
        opts = {"market_label": label or market, "org": s.get("org_name", "BMW"),
                "prepared_by": s.get("prepared_by", ""), "notes": note}
        opts.update(inc)
        _generate(market, sel, opts, want_pdf, prog_slot)

    _download_panel(market)


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
        return
    except Exception as exc:                                  # noqa: BLE001
        progress_bar(slot, 100, "Could not build the report", done=False)
        st.error("The report could not be generated. Nothing has been changed, so you "
                 "can adjust the filters and try again. If it keeps happening, send "
                 "the technical detail below to whoever maintains this tool.")
        with st.expander("Technical detail (for support)"):
            st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
        return
    st.session_state.reports[market] = out


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


def _download_panel(market):
    rep = st.session_state.reports.get(market)
    if not rep:
        return
    bar("Step 7 — Download")
    meta = rep["meta"]
    stem = f"{market}_QA_Report_{meta['period'].replace(' ', '_').replace('–', 'to')}"
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇  PowerPoint (.pptx)", rep["pptx"], f"{stem}.pptx",
                       "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                       key=f"dl_pptx_{market}", **WIDE_BTN)
    if rep.get("pdf"):
        c2.download_button("⬇  PDF (.pdf)", rep["pdf"], f"{stem}.pdf", "application/pdf",
                           key=f"dl_pdf_{market}", **WIDE_BTN)
    else:
        c2.button("PDF not generated", disabled=True, key=f"dl_none_{market}", **WIDE_BTN)
    c3.download_button("⬇  Underlying rows (.csv)", rep["csv"], f"{stem}.csv", "text/csv",
                       key=f"dl_csv_{market}", **WIDE_BTN)
    st.caption(f"Generated {meta['when']} · {meta['period']}. The dashboard above, the "
               "PPTX, the PDF and the CSV all come from the same calculation, so their "
               "numbers match exactly. Re-run Generate after changing a filter.")


# ==========================================================================
# compare
# ==========================================================================
def compare_tab():
    db, s = st.session_state.db, st.session_state.settings
    live = [m for m in store.MARKETS if has_data(db, m)]
    if len(live) < 2:
        st.info("Load data for at least two markets to compare them.")
        return
    with st.form("cmp"):
        bar("Compare markets")
        picked = st.multiselect("Markets", live, default=live)
        all_years = sorted({y for m in live for y, _ in metrics.available_periods(db, m)})
        years = st.multiselect("Year(s)", all_years, default=all_years)
        go = st.form_submit_button("📊   Compare", type="primary", **WIDE_BTN)
    if not go or not picked:
        st.caption("Choose markets and press Compare.")
        return

    series, summary = {}, []
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
    if not summary:
        st.warning("Nothing matched those years.")
        return
    bar("Side by side")
    st.dataframe(summary, hide_index=True, **WIDE_DF)
    st.image(charts.market_compare(series, w=11.0, h=3.8), **WIDE_IMG)
    st.caption("Each market is scored on its own audited volume, so a market with far "
               "fewer tasks will move more sharply month to month.")


# ==========================================================================
# data manager
# ==========================================================================
def data_tab():
    db, s = st.session_state.db, st.session_state.settings

    bar("Developer name merging")
    st.caption("Audit sheets spell the same person several ways. Nothing is merged "
               "automatically — two people can genuinely share a first name, so "
               "ambiguity is flagged for you to decide.")

    all_raw = sorted({r.get("dev_raw") for m in store.MARKETS
                      for r in db["tasks"].get(m, []) if r.get("dev_raw")})
    aliases = dict(s.get("dev_aliases") or {})

    if not all_raw:
        st.info("No task-level data loaded yet.")
    else:
        lookup = nz.build_alias_lookup(aliases)
        grouped = {}
        for raw in all_raw:
            grouped.setdefault(nz.resolve_name(raw, lookup), []).append(raw)
        st.markdown("**Current grouping**")
        st.dataframe([{"Counted as": k, "Spellings in the sheets": ", ".join(v),
                       "Variants": len(v)} for k, v in sorted(grouped.items())],
                     hide_index=True, **WIDE_DF)

        confident, ambiguous = nz.classify_name_groups(all_raw)
        pending = {c: m for c, m in confident.items()
                   if len({nz.resolve_name(x, lookup) for x in m}) > 1}
        if pending:
            st.markdown("**Clear variants — safe to merge**")
            for canon, members in pending.items():
                st.write(f"**{canon}** ← {', '.join(members)}")
            if st.button("Merge all", type="primary", **WIDE_BTN):
                _apply_auto_merge()
                persist()
                st.rerun()
        else:
            st.markdown('<div class="qrs-ok">All clear name variants are already '
                        'merged.</div>', unsafe_allow_html=True)

        still = {c: v for c, v in ambiguous.items()
                 if len({nz.resolve_name(x, lookup) for x in v["members"]}) > 1}
        if still:
            st.markdown("**Ambiguous — needs your decision**")
            for canon, info in still.items():
                st.markdown(f'<div class="qrs-note">{info["reason"]}</div>',
                            unsafe_allow_html=True)
                cc1, cc2 = st.columns([3, 1])
                pick = cc1.selectbox(f"Count \u201c{info['short']}\u201d as",
                                     ["Leave separate"] + info["rivals"],
                                     key=f"amb_{canon}")
                if cc2.button("Apply", key=f"ambb_{canon}", **WIDE_BTN):
                    if pick != "Leave separate":
                        host = nz.display_name(pick)
                        aliases[host] = sorted(set(aliases.get(host, []))
                                               | {pick, info["short"]})
                        s["dev_aliases"] = aliases
                        persist()
                        st.session_state.reports.clear()
                    st.rerun()

        with st.expander("Merge names manually"):
            m1, m2 = st.columns(2)
            keep = m1.selectbox("Count everything as", sorted(grouped.keys()))
            fold = m2.multiselect("Fold these spellings in", all_raw)
            if st.button("Apply manual merge", disabled=not fold):
                aliases[keep] = sorted(set(aliases.get(keep, [])) | set(fold))
                s["dev_aliases"] = aliases
                persist()
                st.session_state.reports.clear()
                st.rerun()

        with st.expander("Undo a merge"):
            if aliases:
                drop = st.selectbox("Remove grouping for", sorted(aliases.keys()))
                if st.button("Remove grouping"):
                    aliases.pop(drop, None)
                    s["dev_aliases"] = aliases
                    persist()
                    st.session_state.reports.clear()
                    st.rerun()
            else:
                st.caption("No merges defined.")

    st.divider()
    bar("Stored periods")
    rows = []
    for m in store.MARKETS:
        for (y, mo) in metrics.available_periods(db, m):
            n_t = sum(1 for r in db["tasks"].get(m, []) if r["year"] == y and r["month"] == mo)
            rows.append({"Market": m, "Period": f"{MONTHS[mo - 1]} {y}", "Task rows": n_t,
                         "Source": "Excel detail" if n_t else "Imported deck",
                         "_k": (m, y, mo)})
    if rows:
        st.dataframe([{k: v for k, v in r.items() if k != "_k"} for r in rows],
                     hide_index=True, **WIDE_DF)
        d1, d2 = st.columns([3, 1])
        pick = d1.selectbox("Delete a period",
                            [f"{r['Market']} — {r['Period']}" for r in rows])
        if d2.button("Delete", **WIDE_BTN):
            key = next(r["_k"] for r in rows if f"{r['Market']} — {r['Period']}" == pick)
            store.backup_db("before_delete")
            n = store.delete_period(db, *key)
            persist()
            st.session_state.reports.clear()
            flash("success", f"Removed {n} record(s) for {pick}.")
            st.rerun()
    else:
        st.caption("Nothing stored yet.")

    st.divider()
    bar("Import history")
    st.caption("Preserved across every reset, including Clear all data.")
    src = list(reversed(db.get("sources", [])))[:40]
    if src:
        st.dataframe([{"When": x["at"].replace("T", " "), "Market": x["market"],
                       "Action": x["kind"].upper(), "File": x["name"], "Records": x["rows"],
                       "Replaced": x.get("replaced", 0),
                       "Periods": ", ".join(x.get("periods", []))} for x in src],
                     hide_index=True, **WIDE_DF)
    else:
        st.caption("No imports yet.")

    st.divider()
    bar("Maintenance")
    m1, m2, m3 = st.columns(3)
    if m1.button("Back up database now", **WIDE_BTN):
        path = store.backup_db("manual")
        st.success(f"Saved to `{os.path.basename(path)}`" if path else "Nothing to back up.")
    m2.download_button("Export database (.json)", store.export_bytes(db),
                       "qa_report_studio_database.json", "application/json", **WIDE_BTN)
    wipe = m3.selectbox("Clear one market", ["—"] + store.MARKETS,
                        label_visibility="collapsed")
    if m3.button("Clear selected market", disabled=wipe == "—", **WIDE_BTN):
        store.backup_db("before_clear")
        n = store.clear_market(db, wipe)
        persist()
        st.session_state.reports.pop(wipe, None)
        flash("success", f"Cleared {n} record(s) from {wipe}. A backup was saved first.")
        st.rerun()


    st.markdown("**Restore a database**")
    st.caption("Loads a file saved with Export database, replacing everything "
               "currently stored. On a hosted server this is how you pick up "
               "where you left off.")
    r1, r2 = st.columns([3, 1])
    up = r1.file_uploader("Database file (.json)", type=["json"],
                          key=f"restore_{st.session_state.upload_epoch}",
                          label_visibility="collapsed")
    if r2.button("Restore", disabled=up is None, **WIDE_BTN):
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
            flash("success", "Database restored — "
                             + ", ".join(f"{m}: {n} record(s)" for m, n in counts.items()))
            st.rerun()


# ==========================================================================
# help
# ==========================================================================
def help_tab():
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
first name, so the decision is yours on the Data manager tab.
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
    # Claimed before anything else is drawn, so the progress bar sits at the very
    # top of the page and stays put while you scroll, rather than appearing
    # halfway down next to whichever step happened to render it.
    prog_slot = st.empty()
    if any(st.session_state.reports.get(m) for m in store.MARKETS):
        progress_bar(prog_slot, 100, "REPORT GENERATED", done=True)

    masthead()
    storage_notice()
    drain_flash()
    sidebar()
    tabs = st.tabs(["🇮🇳  India", "🌍  C3", "🇯🇵  Japan",
                    "⚖️  Compare", "🗂  Data manager", "❓  Help"])
    with tabs[0]:
        market_tab("India", prog_slot)
    with tabs[1]:
        market_tab("C3", prog_slot)
    with tabs[2]:
        market_tab("Japan", prog_slot)
    with tabs[3]:
        compare_tab()
    with tabs[4]:
        data_tab()
    with tabs[5]:
        help_tab()


if __name__ == "__main__":
    main()
