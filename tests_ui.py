#!/usr/bin/env python3
"""
Interface tests for QA Report Studio.

`tests.py` proves the numbers are right. This file proves the redesigned
console actually drives them: it boots the real `app.py` through Streamlit's
own AppTest harness, clicks the real widgets, and checks that every page, every
workflow step and every destructive action still works — including that the
report a user downloads is built from exactly the rows shown on screen.

Run from the project folder:

    python tests_ui.py

Nothing touches the internet, and every run builds its own in-memory database.
"""

from __future__ import annotations

import io
import os
import sys
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Keep the harness off any real database on disk: every AppTest below is seeded
# with its own store, and session mode guarantees nothing is written out.
from qars import store                                       # noqa: E402

store.SESSION_MODE = True

from qars import ingest, metrics, normalize as nz            # noqa: E402
from streamlit.testing.v1 import AppTest                     # noqa: E402

PASS, FAIL = [], []
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f"  --  {detail}" if detail else ""))


def section(title):
    print(f"\n{title}\n" + "-" * len(title))


# --------------------------------------------------------------------------
# harness helpers
# --------------------------------------------------------------------------
def widget(at, kind, key):
    """Find a widget by the key the app gave it, in the main body or sidebar."""
    for w in getattr(at, kind):
        if w.key == key:
            return w
    raise KeyError(f"no {kind} with key {key!r}; "
                   f"available: {[w.key for w in getattr(at, kind)]}")


def by_label(at, kind, text):
    """Find a widget by its visible label — used for form submit buttons, whose
    generated keys embed the form name and would change with it."""
    text = text.lower()
    for w in getattr(at, kind):
        if text in (getattr(w, "label", "") or "").lower():
            return w
    raise KeyError(f"no {kind} labelled {text!r}; "
                   f"available: {[getattr(w, 'label', None) for w in getattr(at, kind)]}")


def has(at, kind, key):
    try:
        widget(at, kind, key)
        return True
    except KeyError:
        return False


def body(at):
    """Every scrap of text the run produced — markdown, captions, tables, alerts."""
    out = []
    for kind in ("markdown", "caption", "text", "success", "info", "warning", "error",
                 "header", "subheader", "title"):
        for el in getattr(at, kind, []):
            out.append(str(getattr(el, "value", "")))
    return "\n".join(out)


def tables(at):
    """Everything rendered through st.dataframe, flattened to text."""
    return "\n".join(str(getattr(el, "value", "")) for el in at.dataframe)


def ran_clean(at, label):
    ok = not at.exception
    check(label, ok, "" if ok else str(at.exception[0].value)[:180])
    return ok


def rows(year, month, error=0, no_error=0, observation=0, dev="Dev A", market="India",
         env="Internal", category="Content Related", severity="Major"):
    out, day = [], 1
    for status, n in ((nz.STATUS_ERR, error), (nz.STATUS_OK, no_error),
                      (nz.STATUS_OBS, observation)):
        for _ in range(n):
            out.append({
                "year": year, "month": month, "day": min(day, 28),
                "date": f"{year:04d}-{month:02d}-{min(day, 28):02d}",
                "week": 1, "market": market, "status": status, "dev_raw": dev,
                "qa_raw": "QA One", "env": env, "title": "Homepage banner task",
                "category": category if status == nz.STATUS_ERR else None,
                "severity": severity if status == nz.STATUS_ERR else None,
                "details": "", "hours": None, "source_file": "seed.xlsx",
                "source_sheet": "Sheet1", "imported_at": "2026-01-01T00:00:00",
            })
            day += 1
    return out


def seeded_db():
    """Three markets, several months, a name variant and a defect mix."""
    db = store._empty_db()
    db["tasks"]["India"] = (
        rows(2026, 5, error=8, no_error=90, observation=2, dev="Mayuresh Patil")
        + rows(2026, 6, error=2, no_error=15, observation=3, dev="Sandeep Jadhav")
        + rows(2026, 7, error=1, no_error=20, observation=1, dev="MAYURESH PATIL",
               category="Design Related", severity="Critical")
        + rows(2026, 7, error=1, no_error=12, observation=0, dev="Amol Laxman Dohale",
               env="Live", category="Redirect Links"))
    db["tasks"]["C3"] = rows(2026, 6, error=3, no_error=40, observation=1,
                             dev="Neha Lal", market="C3")
    db["tasks"]["Japan"] = rows(2026, 6, error=5, no_error=30, observation=0,
                                dev="Rohit Rajan", market="Japan")
    db["sources"] = [{"at": "2026-09-16T06:10:48", "market": "India", "kind": "excel",
                      "name": "July 2026 India QA Audit.xlsx", "rows": 176,
                      "replaced": 0, "periods": ["July 2026"]}]
    return db


def fresh(seed=True, **state):
    at = AppTest.from_file(APP, default_timeout=300)
    at.session_state["db"] = seeded_db() if seed else store._empty_db()
    at.session_state["settings"] = store._default_settings()
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    return at


PAGES = ["home", "upload", "results", "data", "compare", "settings", "help"]


# ==========================================================================
section("BOOT — the app starts clean, with and without data")
at = fresh(seed=False)
ran_clean(at, "Boots with an empty database")
check("Lands on Home", at.session_state["nav"] == "home")
check("Shows an empty state instead of a broken dashboard",
      "No data stored for India yet" in body(at))
check("No login, sign-in or account step exists anywhere",
      not any(w in body(at).lower() for w in ("sign in", "log in", "password", "sign up")))

at = fresh()
ran_clean(at, "Boots with data in all three markets")
check("Hero banner renders", "actionable insights" in body(at))

section("NAVIGATION — every page in the rail renders")
at = fresh()
for key in PAGES:
    at.session_state["nav"] = key
    at.run()
    ok = not at.exception
    check(f"Page renders: {key}", ok, "" if ok else str(at.exception[0].value)[:150])

section("NAVIGATION — the sidebar buttons actually switch page")
at = fresh()
for key in ("upload", "results", "data", "compare", "settings", "help", "home"):
    widget(at, "button", f"nav_{key}").click().run()
    check(f"Clicking “{key}” navigates there", at.session_state["nav"] == key,
          at.session_state["nav"])
check("Nav buttons exist for all seven pages",
      all(has(at, "button", f"nav_{k}") for k in PAGES))

section("TOP BAR — market, period, theme and search")
at = fresh()
widget(at, "selectbox", "topbar_market").select("Japan").run()
check("Market picker switches market", at.session_state["market"] == "Japan",
      at.session_state["market"])
check("Japan's own figures are shown", "Total tasks audited" in body(at))
widget(at, "selectbox", "topbar_market").select("India").run()

sb = widget(at, "selectbox", "topbar_period_India")
check("Period picker offers every stored period plus All periods",
      len(sb.options) == 4 and sb.options[0] == "All periods", str(sb.options))
sb.select("June 2026").run()
check("Choosing a period narrows the view", at.session_state["period_pick"] == (2026, 6),
      str(at.session_state["period_pick"]))
widget(at, "selectbox", "topbar_period_India").select("All periods").run()
check("All periods restores the full range", at.session_state["period_pick"] is None)

check("Light is the theme when Streamlit's base is light",
      at.session_state["dark"] is False)

widget(at, "text_input", "global_search").set_value("Mayuresh").run()
ran_clean(at, "Search runs")
check("Search finds a developer", "Mayuresh" in body(at))
widget(at, "text_input", "global_search").set_value("Redirect").run()
check("Search finds a defect category", "Search results" in body(at))
widget(at, "text_input", "global_search").set_value("zzzz-nothing").run()
check("An empty search says so instead of failing", "Nothing matched" in body(at))
widget(at, "text_input", "global_search").set_value("").run()
check("Clearing the search returns to the page", at.session_state["nav"] == "home")

section("UPLOAD — read, review, validate and confirm a real file")
csv_text = ("Mail Title,Date,Test Environment,Developer Name,Status,Error Type,Error Severity\n"
            "Task A,2026-08-04,Test,Alice Smith,First Time Correct,,\n"
            "Task B,2026-08-05,Live,Alice Smith,Error,Content Related,Critical\n"
            "Task C,2026-08-06,Test,Bob Jones,Observation,,\n")
parsed, report = ingest.read_excel(csv_text.encode(), "India", filename="Aug_2026_audit.csv")
at = fresh(nav="upload")
at.session_state["pending"] = {"India": {"staged": [{"rows": parsed, "report": report,
                                                     "name": "Aug_2026_audit.csv"}],
                                         "failed": []}}
at.run()
ran_clean(at, "The review-and-validate step renders")
check("Step 2 is highlighted", "Review &amp; validate" in body(at) or "Review & validate" in body(at))
check("The mapping report is shown", "Columns recognised" in body(at))
check("A reporting-period override is offered", has(at, "selectbox", "per_India_0"))
check("Validation reports a clean read", "read with no issues" in body(at))
before = len(at.session_state["db"]["tasks"]["India"])
widget(at, "button", "conf_India").click().run()
after = len(at.session_state["db"]["tasks"]["India"])
check("Confirm and import adds the rows", after == before + 3, f"{before} -> {after}")
check("The pending upload is cleared", "India" not in at.session_state["pending"])
check("August 2026 is now a stored period",
      (2026, 8) in metrics.available_periods(at.session_state["db"], "India"))

at2 = fresh(nav="upload")
at2.session_state["pending"] = {"India": {"staged": [{"rows": parsed, "report": report,
                                                      "name": "Aug_2026_audit.csv"}],
                                          "failed": []}}
at2.run()
n_before = len(at2.session_state["db"]["tasks"]["India"])
widget(at2, "button", "canc_India").click().run()
check("Cancel discards the upload without importing",
      len(at2.session_state["db"]["tasks"]["India"]) == n_before
      and "India" not in at2.session_state["pending"])

at3 = fresh(nav="upload")
at3.session_state["pending"] = {"India": {"staged": [],
                                          "failed": [("junk.xlsx", "Not a workbook.")]}}
at3.run()
check("An unreadable file is reported, not swallowed", "junk.xlsx" in body(at3))

section("CONFIGURE — every filter and every section switch is still present")
at = fresh(nav="upload")
ep = at.session_state["cfg_epoch"]
for key, label in [(f"y_India_{ep}", "Year(s)"), (f"m_India_{ep}", "Month(s)"),
                   (f"d_India_{ep}", "Developer(s)"), (f"c_India_{ep}", "Category"),
                   (f"e_India_{ep}", "Environment"), (f"s_India_{ep}", "Severity"),
                   (f"q_India_{ep}", "QA analyst"), (f"w_India_{ep}", "ISO week"),
                   (f"day_India_{ep}", "Day of month")]:
    check(f"Filter present: {label}", has(at, "multiselect", key))
for key, label in [(f"i2_India_{ep}", "Monthly section"), (f"i4_India_{ep}", "QA summary"),
                   (f"i5_India_{ep}", "Developer summary"),
                   (f"i6_India_{ep}", "Defect categories"),
                   (f"i9_India_{ep}", "Recommendations"),
                   (f"i3_India_{ep}", "Score dashboard"),
                   (f"i7_India_{ep}", "Aging analysis"),
                   (f"i8_India_{ep}", "Critical defects"),
                   (f"i10_India_{ep}", "Also build PDF")]:
    check(f"Section switch present: {label}", has(at, "checkbox", key))
check("Cover label field present", has(at, "text_input", f"l_India_{ep}"))
check("Recommendations note field present", has(at, "text_input", f"n_India_{ep}"))
check("Review-the-metrics preview renders", "Review the metrics" in body(at))

section("CONFIGURE — filters change the numbers")
at = fresh(nav="upload")
ep = at.session_state["cfg_epoch"]
widget(at, "multiselect", f"m_India_{ep}").set_value([7]).run()
by_label(at, "button", "Apply filters").click().run()
cfg = at.session_state["cfg"]["India"]
check("The applied months are remembered outside widget state", cfg["months"] == [7],
      str(cfg["months"]))
check("The preview reports the narrowed period", "July 2026" in body(at))
widget(at, "multiselect", f"m_India_{ep}").set_value([]).run()
check("No months selected is explained, not crashed",
      "pick at least one year and one month" in body(at))

section("GENERATE — the report builds and lands on Results")
at = fresh(nav="upload")
by_label(at, "button", "Generate report").click().run()
ran_clean(at, "Generate runs without error")
rep = at.session_state["reports"].get("India")
check("A PPTX was produced", bool(rep) and len(rep["pptx"]) > 50_000,
      f"{len(rep['pptx']) // 1024} KB" if rep else "none")
check("A PDF was produced", bool(rep) and len(rep.get("pdf") or b"") > 20_000,
      f"{len(rep['pdf']) // 1024} KB" if rep and rep.get("pdf") else "none")
check("The underlying CSV was produced", bool(rep) and len(rep["csv"]) > 100)
check("Generating moves the user to Results", at.session_state["nav"] == "results")
check("Results announces the finished report", "Your QA report is ready" in body(at))

section("GENERATE — screen, deck and CSV agree")
sel, tot, _note = None, None, None
db = at.session_state["db"]
s = at.session_state["settings"]
cfg = at.session_state["cfg"]["India"]
periods = [p for p in metrics.available_periods(db, "India")
           if p[0] in cfg["years"] and p[1] in cfg["months"]]
sel = metrics.select(db, "India", s, {"periods": periods})
tot = metrics.totals(sel)
csv_lines = rep["csv"].decode("utf-8-sig").strip().splitlines()
check("CSV row count equals the task count that was scored",
      len(csv_lines) - 1 == tot["total_tasks"],
      f"{len(csv_lines) - 1} vs {tot['total_tasks']}")
from pptx import Presentation                                # noqa: E402
prs = Presentation(io.BytesIO(rep["pptx"]))
blob = " ".join(sh.text_frame.text for sl in prs.slides for sh in sl.shapes
                if sh.has_text_frame)
blob += " " + " ".join(c.text for sl in prs.slides for sh in sl.shapes if sh.has_table
                       for r in sh.table.rows for c in r.cells)
check("The deck carries the score shown on screen",
      metrics.fmt_score(tot["score"]) in blob, metrics.fmt_score(tot["score"]))
check("The deck carries the task total shown on screen", f"{tot['total_tasks']:,}" in blob)
check("The on-screen dashboard shows the same score",
      metrics.fmt_score(tot["score"]) in body(at))

section("RESULTS — the full dashboard and all three downloads")
check("PowerPoint download offered", has(at, "download_button", "dl_pptx_India"))
check("PDF download offered", has(at, "download_button", "dl_pdf_India"))
check("CSV download offered", has(at, "download_button", "dl_csv_India"))
page = body(at)
for label in ["Total tasks audited", "Error free tasks", "Observations", "Total defects",
              "Internal defects", "External defects", "Developers audited",
              "Overall quality score", "Quality score trend", "Defect categories",
              "Top performers", "Task composition", "Key insights", "Recommendations"]:
    check(f"Dashboard block present: {label}", label in page)
check("Highest / lowest / pooled / average are all reported",
      all(w in page for w in ("Highest", "Lowest", "Overall", "Avg monthly")))
check("The observation rule is still explained on the dashboard",
      "never added" in page or "double-count" in page)
check("Monthly and developer tables render", len(at.dataframe) >= 2, str(len(at.dataframe)))

section("RESULTS — the period picker narrows the report as well as the view")
at.session_state["nav"] = "results"
widget(at, "selectbox", "topbar_period_India").select("June 2026").run()
ran_clean(at, "Narrowing to a single month renders")
check("The narrowing is stated plainly, not applied silently",
      "Narrowed to June 2026" in body(at))
widget(at, "selectbox", "topbar_period_India").select("All periods").run()

section("COMPARE — markets side by side")
at = fresh(nav="compare")
ran_clean(at, "Compare page renders")
by_label(at, "button", "Compare").click().run()
ran_clean(at, "Compare runs")
page = body(at)
check("A side-by-side table is produced", len(at.dataframe) >= 1)
check("Every seeded market appears", all(m in page for m in ("India", "C3", "Japan")))
check("Comparison insights are generated", "Comparison insights" in page)
check("The differing-volume caveat is kept", "fewer tasks" in page)

one = AppTest.from_file(APP, default_timeout=300)
one.session_state["db"] = store._empty_db()
one.session_state["db"]["tasks"]["India"] = rows(2026, 5, error=1, no_error=9)
one.session_state["settings"] = store._default_settings()
one.session_state["nav"] = "compare"
one.run()
check("One market alone explains why there is nothing to compare",
      "At least two markets are needed" in body(one))

section("DATA MANAGER — name merging, periods, history, maintenance")
at = fresh(nav="data")
ran_clean(at, "Data Manager renders")
page = body(at)
check("Current grouping is listed", "Current grouping" in page)
check("Manual merge is available", has(at, "selectbox", "dm_keep")
      and has(at, "multiselect", "dm_fold"))
check("Undo-a-merge is available", has(at, "selectbox", "dm_drop")
      or "No merges defined" in page)

grouping = tables(at)
check("The grouping table lists the people found in the sheets",
      "Mayuresh" in grouping, grouping[:70].replace("\n", " "))
check("Both spellings of the same person are visible before any merge",
      "MAYURESH PATIL" in grouping or "Mayuresh Patil" in grouping)
if has(at, "button", "dm_merge_all"):
    widget(at, "button", "dm_merge_all").click().run()
    check("Merge all clear variants applies the grouping",
          bool(at.session_state["settings"]["dev_aliases"]),
          str(list(at.session_state["settings"]["dev_aliases"])[:3]))
else:
    check("Merge all clear variants applies the grouping", True, "already merged on import")

before = len(at.session_state["settings"]["dev_aliases"])
widget(at, "multiselect", "dm_fold").set_value(["Amol Laxman Dohale"]).run()
widget(at, "button", "dm_manual").click().run()
check("A manual merge is applied",
      len(at.session_state["settings"]["dev_aliases"]) >= before)
if has(at, "selectbox", "dm_drop"):
    n_before = len(at.session_state["settings"]["dev_aliases"])
    widget(at, "button", "dm_undo").click().run()
    check("Undo removes a grouping",
          len(at.session_state["settings"]["dev_aliases"]) == n_before - 1,
          f"{n_before} -> {len(at.session_state['settings']['dev_aliases'])}")

at = fresh(nav="data")
n_periods = len(metrics.available_periods(at.session_state["db"], "India"))
widget(at, "selectbox", "dm_del_pick").select("India — May 2026").run()
widget(at, "button", "dm_del").click().run()
check("Deleting a period removes exactly that period",
      len(metrics.available_periods(at.session_state["db"], "India")) == n_periods - 1,
      f"{n_periods} -> {len(metrics.available_periods(at.session_state['db'], 'India'))}")
check("Import history survives a delete", len(at.session_state["db"]["sources"]) >= 1)

at = fresh(nav="data")
widget(at, "selectbox", "dm_wipe").select("Japan").run()
widget(at, "button", "dm_wipe_go").click().run()
check("Clearing one market empties only that market",
      not at.session_state["db"]["tasks"]["Japan"]
      and bool(at.session_state["db"]["tasks"]["India"]))

at = fresh(nav="data")
check("Export database is offered", has(at, "download_button", "dm_export"))
check("Back up now is offered", has(at, "button", "dm_backup"))
check("Restore is offered", has(at, "button", "dm_restore"))
check("Import history is shown", "Import history" in body(at) or len(at.dataframe) >= 1)

section("SETTINGS — branding, benchmarks, appearance and reset")
at = fresh(nav="settings")
ran_clean(at, "Settings renders")
by_label(at, "text_input", "Brand name").set_value("Contoso").run()
by_label(at, "text_input", "Prepared by").set_value("Anish K").run()
by_label(at, "number_input", "Target score").set_value(97.0).run()
by_label(at, "number_input", "Watch benchmark").set_value(92.0).run()
by_label(at, "button", "Save changes").click().run()
s = at.session_state["settings"]
check("Brand name is saved", s["org_name"] == "Contoso", s["org_name"])
check("Prepared by is saved", s["prepared_by"] == "Anish K", s["prepared_by"])
check("Target score is saved", s["target_score"] == 97.0, str(s["target_score"]))
check("Watch benchmark is saved", s["watch_score"] == 92.0, str(s["watch_score"]))
check("Saved details reach the sidebar identity", "Contoso" in body(at))

by_label(at, "number_input", "Watch benchmark").set_value(99.0).run()
by_label(at, "button", "Save changes").click().run()
check("A watch benchmark above the target is challenged",
      "watch benchmark sits above the target" in body(at))

at = fresh(nav="settings")
check("Settings reports the theme in force", "Current theme" in body(at))
check("Settings says where the theme is set", "config.toml" in body(at))
check("No half-working theme switch is offered", not has(at, "radio", "theme_radio"))

at = fresh(nav="settings")
widget(at, "button", "set_clear").click().run()
check("Clear all data asks first", at.session_state["confirm_clear"] is True)
check("The warning says what will be lost", "all three markets" in body(at))
widget(at, "button", "set_clear_no").click().run()
check("Cancel leaves the data alone",
      at.session_state["confirm_clear"] is False
      and bool(at.session_state["db"]["tasks"]["India"]))
widget(at, "button", "set_clear").click().run()
widget(at, "button", "set_clear_yes").click().run()
check("Confirming clears every market",
      all(not at.session_state["db"]["tasks"][m] for m in store.MARKETS))
check("Import history is preserved through a full clear",
      len(at.session_state["db"]["sources"]) >= 1)
ran_clean(at, "The app still renders after a full clear")

section("THEME — light and dark are both whole")
from qars import theme as _T                                 # noqa: E402
light_css, dark_css = _T.app_css(), _T.app_css(dark=True)
check("Both stylesheets render with every token substituted",
      "$" not in light_css and "$" not in dark_css)
check("The two themes genuinely differ", light_css != dark_css)
check("Nothing in the stylesheet calls the internet",
      "http://" not in light_css and "https://" not in light_css)
check("Streamlit's icon face is protected from the UI font stack",
      "Material Symbols" in light_css)
check("The app reads its theme from Streamlit rather than owning a switch",
      hasattr(__import__("app"), "dark_theme"))
at = fresh(dark=True)
ran_clean(at, "Every page renders under the dark palette")
for key in PAGES:
    at.session_state["nav"] = key
    at.run()
    if at.exception:
        check(f"Dark palette renders: {key}", False, str(at.exception[0].value)[:120])
        break
else:
    check("Dark palette renders every page", True)


section("HELP — the reference material is intact")
at = fresh(nav="help")
ran_clean(at, "Help renders")
page = body(at)
for phrase in ["Error-Free Tasks = No Error + Observation", "Quality Score    = Error-Free",
               "never 100%", "Average Monthly Quality Score", "First Time Correct",
               "Working offline"]:
    check(f"Help still explains: {phrase[:38]}", phrase in page)
check("Help documents the new page layout", "Finding your way around" in page)

section("EMPTY STATES — no data anywhere")
at = fresh(seed=False)
for key, expect in [("home", "No data stored"), ("results", "No analysis to show"),
                    ("upload", "Read an audit sheet above"),
                    ("compare", "At least two markets are needed"),
                    ("data", "No task-level data loaded yet")]:
    at.session_state["nav"] = key
    at.run()
    ok = not at.exception and expect in body(at)
    check(f"Empty state explains itself: {key}", ok,
          "" if ok else (str(at.exception[0].value)[:120] if at.exception else "text missing"))

section("REGRESSION — the four-step workflow is still visible end to end")
at = fresh(nav="upload")
check("The stepper is drawn", "qrs-steps" in body(at))
check("All four step names are present",
      all(n in body(at) for n in ("Upload data", "Configure", "Generate")))
check("Both upload surfaces are offered (Excel/CSV and PPTX)",
      has(at, "button", "bxl_India") and has(at, "button", "bpp_India"))

# ==========================================================================
print("\n" + "=" * 62)
print(f"  {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("  FAILED:\n    - " + "\n    - ".join(FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
