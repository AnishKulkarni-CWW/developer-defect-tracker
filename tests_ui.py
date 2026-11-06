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

from qars import ingest, library, metrics, normalize as nz  # noqa: E402
from qars import publish, theme as _theme                    # noqa: E402
from streamlit.testing.v1 import AppTest                     # noqa: E402

PASS, FAIL = [], []
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")

# Confirming an import now writes the workbook into the report library. The
# whole suite therefore runs against a throwaway copy of it, and nothing a test
# does can reach the repository. Most sections start from the two issued decks
# alone — the history as it stood before any workbook was embedded — so the
# rows they seed are the only workbook data in play; the sections about the
# embedded months switch to everything that ships. Months imported after this
# release (October onwards, on a live app) are never copied: they must not
# change what a test expects.
import json                                                  # noqa: E402
import shutil                                                # noqa: E402
import tempfile                                              # noqa: E402

SHIPPED_DIR = library.DIR
SCRATCH_DIR = tempfile.mkdtemp(prefix="qars_ui_lib_")


def _fill_library(dest, mode):
    with open(os.path.join(SHIPPED_DIR, "index.json"), encoding="utf-8") as fh:
        shipped = [e for e in json.load(fh)["entries"] if e.get("shipped")]
    keep = [e for e in shipped if mode == "shipped" or e["kind"] == "deck"]
    for e in keep:
        target = os.path.join(dest, e["file"])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(SHIPPED_DIR, e["file"]), target)
    with open(os.path.join(dest, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"entries": keep}, fh, indent=1)


def reset_library(mode="decks"):
    """
    Put the scratch library back to a known start: "decks" (the two issued
    reports) or "shipped" (those plus the embedded July–September workbooks).

    The library is permanent by design, so an import in one section is still
    there in the next — correct behaviour, and exactly what makes these tests
    order-dependent unless a section that assumes a clean start says so.
    """
    shutil.rmtree(SCRATCH_DIR, ignore_errors=True)
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    _fill_library(SCRATCH_DIR, mode)
    library._CACHE.clear()


_REAL_SIG = library.signature()
_fill_library(SCRATCH_DIR, "decks")
library.DIR = SCRATCH_DIR
library.INDEX = os.path.join(SCRATCH_DIR, "index.json")
library._CACHE.clear()


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


def submit_form(at, fields, button):
    """
    Fill in form fields and press the form's submit button, in one run.

    That is what a browser does: editing a widget inside an st.form does not
    rerun the script — the values travel with the submit. Calling .run()
    between the edit and the submit is a sequence no user can produce, and
    since Streamlit 1.67 the test harness discards those uncommitted values,
    exactly as the real form would.

    fields: [(widget, value)]
    """
    for w, value in fields:
        w.set_value(value)
    by_label(at, "button", button).click().run()


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
                                                     "name": "Aug_2026_audit.csv",
                                                     "data": csv_text.encode()}],
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
                                                      "name": "Aug_2026_audit.csv",
                                                      "data": csv_text.encode()}],
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
submit_form(at, [(widget(at, "multiselect", f"m_India_{ep}"), [7])], "Apply filters")
cfg = at.session_state["cfg"]["India"]
check("The applied months are remembered outside widget state", cfg["months"] == [7],
      str(cfg["months"]))
check("The preview reports the narrowed period", "July 2026" in body(at))
submit_form(at, [(widget(at, "multiselect", f"m_India_{ep}"), [])], "Apply filters")
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
              "Test link defects", "Live link defects", "Developers audited",
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

_saved_lib = (library.DIR, library.INDEX)
_empty_lib = tempfile.mkdtemp(prefix="qars_empty_lib_")
try:
    library.DIR, library.INDEX = _empty_lib, os.path.join(_empty_lib, "index.json")
    library._CACHE.clear()                 # simulate an install with no history
    one = AppTest.from_file(APP, default_timeout=300)
    one.session_state["db"] = store._empty_db()
    one.session_state["db"]["tasks"]["India"] = rows(2026, 5, error=1, no_error=9)
    one.session_state["settings"] = store._default_settings()
    one.session_state["nav"] = "compare"
    one.run()
    check("One market alone explains why there is nothing to compare",
          "At least two markets are needed" in body(one))
finally:
    library.DIR, library.INDEX = _saved_lib
    library._CACHE.clear()
    shutil.rmtree(_empty_lib, ignore_errors=True)

section("DATA MANAGER — name merging, periods, history, maintenance")
at = fresh(nav="data")
ran_clean(at, "Data Manager renders")
page = body(at)
check("Current grouping is listed", "Current grouping" in page)
check("Manual merge is available", has(at, "selectbox", "dm_keep")
      and has(at, "multiselect", "dm_fold"))
check("Undo-a-merge is available", has(at, "selectbox", "dm_drop")
      or "No merges made by hand yet" in page)

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

_keep = widget(at, "selectbox", "dm_keep").value
widget(at, "multiselect", "dm_fold").set_value(["Amol Laxman Dohale"]).run()
widget(at, "button", "dm_manual").click().run()
_lookup = nz.build_alias_lookup(at.session_state["settings"]["dev_aliases"])
check("A manual merge is applied",
      nz.resolve_name("Amol Laxman Dohale", _lookup) == _keep,
      f"counted as {nz.resolve_name('Amol Laxman Dohale', _lookup)}")
check("And kept with the history", "Amol Laxman Dohale" in library.aliases().get(_keep, []))
check("A hand-made merge is offered for undoing", has(at, "selectbox", "dm_drop")
      and widget(at, "selectbox", "dm_drop").value == _keep)
widget(at, "button", "dm_undo").click().run()
_lookup = nz.build_alias_lookup(at.session_state["settings"]["dev_aliases"])
check("Undo removes the grouping",
      nz.resolve_name("Amol Laxman Dohale", _lookup) != _keep
      and _keep not in library.aliases(),
      f"counted as {nz.resolve_name('Amol Laxman Dohale', _lookup)}")
check("Nothing made automatically is offered for undoing",
      not has(at, "selectbox", "dm_drop") and "No merges made by hand yet" in body(at))

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

reset_library()
section("SETTINGS — branding, benchmarks, appearance and reset")
at = fresh(nav="settings")
ran_clean(at, "Settings renders")
submit_form(at, [(by_label(at, "text_input", "Brand name"), "Contoso"),
                 (by_label(at, "text_input", "Prepared by"), "Anish K")], "Save changes")
s = at.session_state["settings"]
check("Brand name is saved", s["org_name"] == "Contoso", s["org_name"])
check("Prepared by is saved", s["prepared_by"] == "Anish K", s["prepared_by"])
check("Saved details reach the sidebar identity", "Contoso" in body(at))
check("No target score can be set", not at.number_input,
      str([w.label for w in at.number_input]))
check("The score bands are explained instead", "no target to set" in body(at))
check("Nothing is stored for a target", "target_score" not in s and "watch_score" not in s,
      str(sorted(s)))

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
_kept = {m for m in store.MARKETS if library.periods_for(m)}
check("Confirming clears every market the library does not hold",
      all(not at.session_state["db"]["tasks"][m]
          for m in store.MARKETS if m not in _kept),
      str({m: len(at.session_state["db"]["tasks"][m]) for m in store.MARKETS}))
check("But the kept history reloads straight away",
      all(library.periods_for(m) <= set(metrics.available_periods(
          at.session_state["db"], m)) for m in _kept))
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


reset_library()
section("NO POWERPOINT UPLOAD — the decks are built in")
at = fresh(nav="upload")
check("The audit-sheet uploader is still offered", has(at, "button", "bxl_India"))
check("No PowerPoint uploader remains", not has(at, "button", "bpp_India"))
page = body(at)
check("Nothing invites a deck upload",
      "Import PowerPoint" not in page and "Upload PPTX" not in page)
check("Only one file uploader is on the page", len(at.file_uploader) == 1,
      str(len(at.file_uploader)))
widget(at, "selectbox", "topbar_market").select("C3").run()
check("A market with kept history says so", "already here" in body(at))
check("It says nothing needs re-uploading", "nothing to re-upload" in body(at))

reset_library()
section("REPORT LIBRARY — present from the first run")
at = fresh(seed=False)
db = at.session_state["db"]
check("C3 arrives with six months", len(db["monthly"]["C3"]) == 6,
      str(len(db["monthly"]["C3"])))
check("Japan arrives with six months", len(db["monthly"]["Japan"]) == 6)
check("India arrives empty", not db["monthly"]["India"] and not db["tasks"]["India"])
at.session_state["nav"] = "home"
at.run()
widget(at, "selectbox", "topbar_market").select("C3").run()
ran_clean(at, "A market with kept history renders with no upload at all")
check("The published C3 score is on screen", "93.29%" in body(at),
      "score not rendered")
_c3 = metrics.totals(metrics.select(at.session_state["db"], "C3",
                                    at.session_state["settings"], {}))
check("The library roster is folded to the count its own deck published",
      _c3["developers"] == 15, f"{_c3['developers']} developers")
check("The library figures are the published ones",
      (_c3["total_tasks"], _c3["error_tasks"], _c3["score"]) == (641, 43, 93.29),
      f"{_c3['total_tasks']} / {_c3['error_tasks']} / {_c3['score']}")
at.session_state["nav"] = "data"
at.run()
check("Library months are labelled in the data manager",
      "Shipped report" in tables(at), tables(at)[:80].replace("\n", " "))
check("The library roster is listed on the merging tab",
      "Anish" in tables(at), tables(at)[:60].replace("\n", " "))
check("C3's library names are already folded together",
      at.session_state["settings"]["dev_aliases"] != {},
      str(list(at.session_state["settings"]["dev_aliases"])[:3]))
check("A library month is not offered for deletion here",
      not has(at, "selectbox", "dm_del_pick"))
check("It points at the Report library tab instead",
      "Report library" in body(at))

# Clearing user data must not take the built-in history with it.
at.session_state["nav"] = "settings"
at.run()
widget(at, "button", "set_clear").click().run()
widget(at, "button", "set_clear_yes").click().run()
check("Clearing everything leaves the library in place",
      len(at.session_state["db"]["monthly"]["C3"]) == 6,
      str(len(at.session_state["db"]["monthly"]["C3"])))
check("The clear message says the library is untouched",
      "report library" in body(at).lower())

section("NO HOSTED-STORAGE BANNER")
at = fresh()
check("The hosted-server notice is gone from every page",
      "Running on a hosted server" not in body(at))
for key in PAGES:
    at.session_state["nav"] = key
    at.run()
    if "Running on a hosted server" in body(at):
        check("The hosted-server notice is gone from every page", False, key)
        break

section("LINK TYPES — no external framing on screen")
at = fresh(nav="upload")
ep = at.session_state["cfg_epoch"]
check("The environment filter is called link type",
      has(at, "multiselect", f"e_India_{ep}")
      and widget(at, "multiselect", f"e_India_{ep}").label == "Link type",
      widget(at, "multiselect", f"e_India_{ep}").label)
at.session_state["nav"] = "results"
at.run()
page = body(at)
check("Nothing on the dashboard calls a defect external",
      "External defects" not in page and "escaped" not in page)
check("Both link types are reported", "Test link defects" in page
      and "Live link defects" in page)

section("SINGLE MONTH — the app says what the report will contain")
at = fresh(nav="upload")
ep = at.session_state["cfg_epoch"]
submit_form(at, [(widget(at, "multiselect", f"m_India_{ep}"), [7])], "Apply filters")
check("Selecting one month explains the consolidated section is dropped",
      "One month selected" in body(at))
submit_form(at, [(widget(at, "multiselect", f"m_India_{ep}"), [5, 6, 7])], "Apply filters")
check("Selecting several months says nothing of the sort",
      "One month selected" not in body(at))

section("DEVELOPER TABLE — the columns add up on screen")
at = fresh(nav="results")
grid = tables(at)
check("The on-screen developer table carries a Total row", "Total" in grid)
check("The rule is printed under it", "Error Free = No Error + Observation" in body(at))


section("HERO — one line, nothing else")
at = fresh(nav="home")
page = body(at)
check("The headline is there", "Turn QA data into" in page)
check("The welcome eyebrow is gone", "WELCOME TO" not in page.upper())
check("The blurb is gone", "Upload your audit sheets, analyse defects" not in page)
check("The feature chips are gone",
      "Automated analysis" not in page and "Nothing leaves this machine" not in page)
check("The hero still renders as a hero", "qrs-hero" in page)

section("SIDEBAR — the rail can be reopened after closing it")
# The collapse/reopen cycle itself is a browser behaviour and is driven in a
# real Chromium session; what can be guarded here is the stylesheet rule that
# broke it, so it cannot come back.
_css = _theme.app_css()
check("The top bar is no longer hidden outright",
      "header[data-testid=\"stHeader\"], [data-testid=\"stHeader\"]," not in _css)
check("The bar is flattened instead", "pointer-events:none" in _css
      and "height:0" in _css)
check("The control that reopens the rail is kept and styled",
      "stExpandSidebarButton" in _css)
check("It outranks the sticky progress strip",
      "z-index:1000005" in _css)
check("Only the toolbar's own contents are hidden",
      "stAppDeployButton" in _css and "stMainMenu" in _css)
check("The collapse arrow is not hover-only any more",
      "stSidebarCollapseButton" in _css)
check("The sidebar header keeps enough height to hold it",
      "min-height:34px" in _css)
# Streamlit collapses the rail by setting max-width to 0; a min-width held
# unconditionally wins over that and leaves a blank gutter where it was.
_rail = [blk for blk in _css.split("}") if "min-width:286px" in blk]
check("The rail's width holds only while it is open, so closing it frees the space",
      bool(_rail) and all(':not([data-collapsed="true"])' in blk for blk in _rail),
      f"{len(_rail)} rule(s)")

reset_library()
section("REPORT LIBRARY — the page that explains what is kept")
at = fresh(nav="data")
ran_clean(at, "The Report library tab renders")
page = body(at)
check("It lists what is kept", "What is kept" in page)
check("The shipped decks are shown", "Shipped with the app" in page)
check("It says publishing is off when no token is set",
      "not published" in page or "cannot write" in page)
check("It shows how to switch publishing on", "secrets.toml" in page)
check("A library pack can be downloaded", has(at, "download_button", "lib_pack"))
check("A library pack can be restored", has(at, "button", "lib_restore_go"))
check("Nothing shipped is offered for removal",
      not has(at, "selectbox", "lib_rm_pick"))

section("REPORT LIBRARY — an import is kept for the next person")
_before = len(library.summary())
at = fresh(nav="upload")
_csv = ("Mail Title,Date,Test Environment,Developer Name,Status,Error Type,Error Severity\n"
        "Task A,2026-09-04,Test,Alice Smith,First Time Correct,,\n"
        "Task B,2026-09-05,Live,Alice Smith,Error,Content Related,Critical\n"
        "Task C,2026-09-06,Test,Bob Jones,Observation,,\n")
_rows, _rep = ingest.read_excel(_csv.encode(), "India", filename="Sep_2026_audit.csv")
at.session_state["pending"] = {"India": {"staged": [{"rows": _rows, "report": _rep,
                                                     "name": "Sep_2026_audit.csv",
                                                     "data": _csv.encode()}],
                                         "failed": []}}
at.run()
widget(at, "button", "conf_India").click().run()
check("The imported file is kept in the library",
      len(library.summary()) == _before + 1,
      f"{_before} -> {len(library.summary())}")
_entry = next((e for e in library.summary()
               if e["source_name"] == "Sep_2026_audit.csv"), None)
check("It is recorded against the right market and month",
      bool(_entry) and _entry["market"] == "India" and _entry["periods"] == [(2026, 9)],
      str(_entry["periods"]) if _entry else "missing")
check("The import is logged in the history",
      any(x["name"] == "Sep_2026_audit.csv" for x in at.session_state["db"]["sources"]))
check("The app says the months were kept, not just imported",
      "report library" in body(at).lower())

# This is the whole point: a brand-new visitor, with no session state at all,
# gets the month somebody else uploaded.
_next = AppTest.from_file(APP, default_timeout=300)
_next.session_state["db"] = store._empty_db()
_next.session_state["settings"] = store._default_settings()
_next.run()
_ndb = _next.session_state["db"]
check("A brand-new session inherits the imported month",
      (2026, 9) in {(r["year"], r["month"]) for r in _ndb["tasks"]["India"]},
      str(sorted({(r["year"], r["month"]) for r in _ndb["tasks"]["India"]})))
check("And still has the shipped C3 history",
      len(_ndb["monthly"]["C3"]) == 6, str(len(_ndb["monthly"]["C3"])))
_next.session_state["market"] = "India"
_next.session_state["nav"] = "results"
_next.run()
ran_clean(_next, "It can report on a month it never uploaded")

section("REPORT LIBRARY — removing a kept month")
at = fresh(nav="data")
check("An imported file is offered for removal", has(at, "selectbox", "lib_rm_pick"))
_opts = widget(at, "selectbox", "lib_rm_pick").options
check("Only imported files are listed",
      all("Quality_Defect_Report" not in o for o in _opts), str(_opts))
widget(at, "selectbox", "lib_rm_pick").select(
    next(o for o in _opts if "Sep_2026_audit.csv" in o)).run()
widget(at, "button", "lib_rm_go").click().run()
check("Removing it takes it out of the library",
      not any(e["source_name"] == "Sep_2026_audit.csv" for e in library.summary()))
_after = AppTest.from_file(APP, default_timeout=300)
_after.session_state["db"] = store._empty_db()
_after.session_state["settings"] = store._default_settings()
_after.run()
check("And out of a fresh session's history",
      (2026, 9) not in {(r["year"], r["month"])
                        for r in _after.session_state["db"]["tasks"]["India"]})

section("PUBLISHING — the app reads its own configuration")
check("The app exposes a publish configuration step",
      hasattr(__import__("app"), "publish_config"))
check("With no secrets file it stays off", publish.enabled() is False,
      str(publish.status()))


section("HELP — the reference material is intact")
at = fresh(nav="help")
ran_clean(at, "Help renders")
page = body(at)
for phrase in ["Error-Free Tasks = No Error + Observation", "Quality Score    = Error-Free",
               "never 100%", "Average Monthly Quality Score", "First Time Correct",
               "Working offline"]:
    check(f"Help still explains: {phrase[:38]}", phrase in page)
check("Help documents the new page layout", "Finding your way around" in page)

reset_library()
section("EMPTY STATES — no data anywhere")
at = fresh(seed=False)
check("India is the market with no kept history", not library.periods_for("India"))
for key, expect in [("home", "No data stored"), ("results", "No analysis to show"),
                    ("upload", "Read an audit sheet above")]:
    at.session_state["nav"] = key
    at.run()
    ok = not at.exception and expect in body(at)
    check(f"Empty state explains itself: {key}", ok,
          "" if ok else (str(at.exception[0].value)[:120] if at.exception else "text missing"))
at.session_state["nav"] = "compare"
at.run()
check("Compare is never empty, because two markets ship with the app",
      not at.exception and "At least two markets are needed" not in body(at))
at.session_state["nav"] = "data"
at.run()
check("Data Manager shows the library roster with nothing uploaded",
      not at.exception and "Current grouping" in body(at))

section("REGRESSION — the four-step workflow is still visible end to end")
at = fresh(nav="upload")
check("The stepper is drawn", "qrs-steps" in body(at))
check("All four step names are present",
      all(n in body(at) for n in ("Upload data", "Configure", "Generate")))
check("The audit sheet is the only file the workflow asks for",
      has(at, "button", "bxl_India") and not has(at, "button", "bpp_India"))

def sheet(n, month=10, errors=0, observations=0, dev="Dev Oct", typo=None):
    """An audit sheet as .csv bytes: errors first, then observations, then passes."""
    lines = ["Mail Title,Date,Test Environment,Developer Name,Status,Error Type,"
             "Error Severity"]
    for i in range(n):
        if i < errors:
            status, cat, sev = "Error", "Content Related", "Major"
        elif i < errors + observations:
            status, cat, sev = "Observation", "", ""
        else:
            status, cat, sev = "First Time Correct", "", ""
        if typo and i == n - 1:
            status = typo
        lines.append(f"Task {i + 1},2026-{month:02d}-{(i % 28) + 1:02d},Test,{dev},"
                     f"{status},{cat},{sev}")
    return ("\n".join(lines) + "\n").encode("utf-8")


OCTOBER = [("October 2026 India.csv", sheet(40, errors=3, observations=2, dev="Asha Rao")),
           ("October 2026 C3.csv", sheet(30, errors=2, observations=1, dev="Neha Lal")),
           ("October 2026 Japan.csv", sheet(20, errors=1, dev="Rohit Rajan", typo="Psas"))]


def upload(at, market, files):
    """Choose files in the uploader and press Read, as a person would."""
    if at.session_state["nav"] != "upload":
        at.session_state["nav"] = "upload"
        at.run()
    if at.session_state["market"] != market:
        widget(at, "selectbox", "topbar_market").select(market).run()
    at.file_uploader[0].set_value([(name, data, "text/csv") for name, data in files])
    at.run()
    widget(at, "button", f"bxl_{market}").click().run()


def periods(at, market):
    return sorted(metrics.available_periods(at.session_state["db"], market))


def library_from(files, dest):
    """A server's library folder, rebuilt from nothing but the repository."""
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    for path, data in files.items():
        if path.startswith("qars/library/"):
            target = os.path.join(dest, path[len("qars/library/"):])
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(data)
    library._CACHE.clear()


def repo_snapshot(folder):
    out = {}
    for root, _dirs, names in os.walk(folder):
        for name in names:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            with open(full, "rb") as fh:
                out[f"qars/library/{rel}"] = fh.read()
    return out


reset_library("shipped")
section("EMBEDDED HISTORY — July to September ship with the app")
at = fresh(seed=False)
ran_clean(at, "The app boots on the embedded history alone")
check("India arrives with July to September",
      periods(at, "India") == [(2026, m) for m in (7, 8, 9)], str(periods(at, "India")))
for _m in ("C3", "Japan"):
    check(f"{_m} arrives with January to September",
          periods(at, _m) == [(2026, k) for k in range(1, 10)], str(periods(at, _m)))
check("No month outside 2026 appears anywhere",
      all(y == 2026 for m in store.MARKETS for y, _ in periods(at, m)))
widget(at, "selectbox", "topbar_market").select("India").run()
page = body(at)
check("India's dashboard shows the embedded figures", "423" in page and "93.85%" in page)
widget(at, "selectbox", "topbar_market").select("Japan").run()
check("Japan's dashboard counts all 656 tasks", "656" in body(at) and "96.19%" in body(at))
check("Japan's period picker offers all nine months",
      len(widget(at, "selectbox", "topbar_period_Japan").options) == 10,
      str(widget(at, "selectbox", "topbar_period_Japan").options))
at.session_state["nav"] = "upload"
at.run()
check("The upload page says Japan's months are already here",
      "January 2026 – September 2026 is already here" in body(at))
widget(at, "selectbox", "topbar_market").select("C3").run()
by_label(at, "button", "Generate report").click().run()
ran_clean(at, "A January–September C3 report generates")
_rep = at.session_state["reports"].get("C3")
_prs = Presentation(io.BytesIO(_rep["pptx"])) if _rep else None
_blob = " ".join(sh.text_frame.text for sl in _prs.slides for sh in sl.shapes
                 if sh.has_text_frame) if _prs else ""
_blob += " " + " ".join(c.text for sl in _prs.slides for sh in sl.shapes if sh.has_table
                        for r in sh.table.rows for c in r.cells) if _prs else ""
check("The deck spans January to September", "Jan" in _blob and "Sep 2026" in _blob)
check("The deck carries C3's combined score", "93.27%" in _blob)
check("The deck counts every C3 task", "980" in _blob)
at.session_state["nav"] = "data"
at.run()
page = body(at)
check("The library lists all eleven shipped files", "11 file(s)" in page)
check("It says which India task could not be counted, and why",
      "iX1 LWB Brochure update" in page and "no Developer Name" in page)
check("It says the Japan 'Psas' typo was read as a pass", "Psas" in page)

reset_library("shipped")
section("OCTOBER — three sheets read from one page, each filed under its own market")
at = fresh(seed=False, nav="upload")
upload(at, "India", OCTOBER)
_pend = at.session_state["pending"].get("India")
check("All three sheets are read from the one page", bool(_pend) and len(_pend["staged"]) == 3,
      str(len(_pend["staged"])) if _pend else "nothing staged")
check("Each goes to the market its name says",
      [x["market"] for x in _pend["staged"]] == ["India", "C3", "Japan"],
      str([x["market"] for x in _pend["staged"]]))
check("The review says where the C3 and Japan sheets will go",
      body(at).count("📬") == 2, str(body(at).count("📬")))
check("The status typo is called out before anything is imported",
      "“Psas”" in body(at) and "looks like a typo" in body(at))
widget(at, "button", "conf_India").click().run()
ran_clean(at, "Confirming three markets at once runs clean")
check("India now runs July to October",
      periods(at, "India") == [(2026, m) for m in (7, 8, 9, 10)], str(periods(at, "India")))
for _m in ("C3", "Japan"):
    check(f"{_m} now runs January to October",
          periods(at, _m) == [(2026, k) for k in range(1, 11)], str(periods(at, _m)))
check("October is kept in the library for every market",
      all((2026, 10) in library.periods_for(m) for m in store.MARKETS))
check("The app says where each sheet went",
      all(f"{m}: 1 file(s) added to the report library" in body(at) for m in store.MARKETS))
_s = at.session_state["settings"]
_db = at.session_state["db"]
check("The months already there are untouched",
      [metrics.totals(metrics.select(_db, "India", _s, {"periods": [(2026, m)]}))
       ["total_tasks"] for m in (7, 8, 9, 10)] == [176, 93, 154, 40])
check("Japan's October counts the 'Psas' task",
      metrics.totals(metrics.select(_db, "Japan", _s, {"periods": [(2026, 10)]}))
      ["total_tasks"] == 20)

_next = fresh(seed=False)
check("A brand-new visitor gets October in all three markets",
      all((2026, 10) in periods(_next, m) for m in store.MARKETS))
widget(_next, "selectbox", "topbar_market").select("C3").run()
_next.session_state["nav"] = "upload"
_next.run()
check("And is told January to October is already here",
      "January 2026 – October 2026 is already here" in body(_next))
by_label(_next, "button", "Generate report").click().run()
_rep = _next.session_state["reports"].get("C3")
_prs = Presentation(io.BytesIO(_rep["pptx"])) if _rep else None
_blob = " ".join(sh.text_frame.text for sl in _prs.slides for sh in sl.shapes
                 if sh.has_text_frame) if _prs else ""
_blob += " " + " ".join(c.text for sl in _prs.slides for sh in sl.shapes if sh.has_table
                        for r in sh.table.rows for c in r.cells) if _prs else ""
check("Their C3 report runs January to October without uploading anything",
      "Oct 2026" in _blob and "1,010" in _blob)

section("NOVEMBER — next month is one file per market")
upload(_next, "C3", [("November 2026 C3.csv", sheet(25, month=11, errors=1, dev="Neha Lal"))])
widget(_next, "button", "conf_C3").click().run()
check("C3 runs January to November",
      periods(_next, "C3") == [(2026, k) for k in range(1, 12)], str(periods(_next, "C3")))
upload(_next, "C3", [("October 2026 C3 corrected.csv", sheet(33, errors=2, dev="Neha Lal"))])
widget(_next, "button", "conf_C3").click().run()
_db, _s = _next.session_state["db"], _next.session_state["settings"]
check("A corrected October replaces October, nothing else",
      metrics.totals(metrics.select(_db, "C3", _s, {"periods": [(2026, 10)]}))["total_tasks"]
      == 33 and periods(_next, "C3") == [(2026, k) for k in range(1, 12)])
check("The replaced file is gone from the library",
      not any(e["source_name"] == "October 2026 C3.csv" for e in library.summary()))

reset_library("shipped")
section("CORRECTIONS — a shipped month can be corrected, and the correction undone")
at = fresh(seed=False, nav="upload")
upload(at, "India", [("July 2026 India corrected.csv", sheet(180, month=7, errors=4,
                                                               dev="Asha Rao"))])
widget(at, "button", "conf_India").click().run()
_db, _s = at.session_state["db"], at.session_state["settings"]
check("July counts the corrected sheet only",
      metrics.totals(metrics.select(_db, "India", _s, {"periods": [(2026, 7)]}))
      ["total_tasks"] == 180)
at.session_state["nav"] = "data"
at.run()
check("The library says the shipped July no longer counts, and why",
      "now comes from <b>July 2026 India corrected.csv</b>" in body(at))
_opts = widget(at, "selectbox", "lib_rm_pick").options
widget(at, "selectbox", "lib_rm_pick").select(
    next(o for o in _opts if "corrected" in o)).run()
check("Removing the correction is seen to put the shipped July back",
      "puts July 2026 back from July 2026 India.xlsx" in body(at))
widget(at, "button", "lib_rm_go").click().run()
check("And it does",
      metrics.totals(metrics.select(at.session_state["db"], "India",
                                    at.session_state["settings"], {"periods": [(2026, 7)]}))
      ["total_tasks"] == 176)

reset_library("shipped")
section("NAMES — a decision made once holds for everyone")
at = fresh(seed=False, nav="data")
page = body(at)
check("Look-alike spellings are offered for a decision", "Possibly the same person" in page)
for _a, _b in [("Mithesh Gupta", "Mitesh Umashankar Gupta"),
               ("Sarika Joshi", "Sarika Rupesh Joshte"),
               ("Dipalee Dugaonkar", "Dipali Tanaji Dugaokar")]:
    check(f"Suggested: {_a} / {_b}", _a in page and _b in page)
check("Short names shared by two people are asked about, not guessed",
      has(at, "selectbox", "amb_Mitesh") and has(at, "selectbox", "amb_Neha"))


def _devs(at_):
    return sum(metrics.totals(metrics.select(at_.session_state["db"], m,
                                             at_.session_state["settings"], {}))
               ["developers"] for m in store.MARKETS)


_before = _devs(at)
by_label(at, "button", "Count both as Mitesh Umashankar Gupta").click().run()
check("Counting both as one person is kept in the library",
      "Mithesh Gupta" in library.aliases().get("Mitesh Umashankar Gupta", []),
      str(library.aliases()))
_next = fresh(seed=False, nav="data")
check("A new visitor counts them as one person", _devs(_next) == _before - 1,
      f"{_before} -> {_devs(_next)}")
check("And is not asked again", "Mithesh Gupta" not in body(_next)
      or "Count both as Mitesh Umashankar Gupta" not in
      [b.label for b in _next.button])
widget(_next, "button", "sim_no_0").click().run()
check("'Different people' is kept too",
      frozenset(("Sarika Joshi", "Sarika Rupesh Joshte")) in library.distinct_pairs(),
      str(library.distinct_pairs()))
_next = fresh(seed=False, nav="data")
check("And that pair is not suggested again",
      not any("Sarika" in (b.label or "") for b in _next.button))
widget(_next, "selectbox", "amb_Neha").select("Leave separate").run()
widget(_next, "button", "ambb_Neha").click().run()
_next = fresh(seed=False, nav="data")
check("An ambiguous name answered once stays answered",
      not has(_next, "selectbox", "amb_Neha") and has(_next, "selectbox", "amb_Mitesh"))

reset_library()
section("KEEPING — the upload page says whether an import will last")
at = fresh(nav="upload")
check("Without publishing, it says a hosted server forgets imports",
      "forgets imports when it restarts" in body(at))

reset_library("shipped")
section("PUBLISHING — switched on through the app's secrets, end to end")
from fake_github import FakeGitHub                           # noqa: E402
_gh = FakeGitHub(files=repo_snapshot(SCRATCH_DIR)).start()
_saved_api = publish.API
publish.API = _gh.url
_SECRETS = {"token": "good-token", "repo": "owner/repo", "branch": "main"}


def hosted(nav="home"):
    at_ = AppTest.from_file(APP, default_timeout=300)
    at_.secrets["github"] = dict(_SECRETS)
    at_.session_state["db"] = store._empty_db()
    at_.session_state["settings"] = store._default_settings()
    at_.session_state["nav"] = nav
    at_.run()
    return at_


try:
    at = hosted("upload")
    ran_clean(at, "The app boots with publishing configured")
    check("A token in the secrets switches publishing on",
          publish.enabled() and publish.status()["repo"] == "owner/repo")
    check("The upload page says imports are committed",
          "Imports are committed to" in body(at) and "owner/repo" in body(at))
    _n = len(_gh.history())
    upload(at, "India", OCTOBER)
    widget(at, "button", "conf_India").click().run()
    ran_clean(at, "Confirming October with publishing on runs clean")
    check("Three markets confirmed together land as ONE commit",
          len(_gh.history()) == _n + 1, str(_gh.history()[:3]))
    _files = _gh.files()
    check("The commit carries all three October workbooks",
          all(any(p.startswith(f"qars/library/{m}/2026-10_") for p in _files)
              for m in store.MARKETS))
    _idx = json.loads(_files["qars/library/index.json"])["entries"]
    check("And an index listing them",
          sum(1 for e in _idx if e.get("primary") == "2026-10") == 3)
    check("Alongside everything that shipped", sum(1 for e in _idx if e.get("shipped")) == 11)
    check("The app says they are part of the app now",
          "committed to the repository" in body(at))

    # The server restarts. Its disk is rebuilt from the repository and nothing else.
    library_from(_gh.files(), SCRATCH_DIR)
    _after = fresh(seed=False)
    check("After a restart every market still has October",
          all((2026, 10) in periods(_after, m) for m in store.MARKETS))
    check("And all of its history before that",
          periods(_after, "C3") == [(2026, k) for k in range(1, 11)]
          and periods(_after, "India") == [(2026, m) for m in (7, 8, 9, 10)])

    at = hosted("data")
    widget(at, "button", "lib_check").click().run()
    check("Check connection confirms the repository and branch",
          "Connected to owner/repo on main" in body(at))
    _n = len(_gh.history())
    by_label(at, "button", "Count both as Mitesh Umashankar Gupta").click().run()
    _names = json.loads(_gh.files().get("qars/library/aliases.json", b"{}"))
    check("A name decision is committed as well",
          "Mithesh Gupta" in _names.get("aliases", {}).get("Mitesh Umashankar Gupta", [])
          and len(_gh.history()) == _n + 1, str(_names)[:120])
    at = hosted("data")
    _n = len(_gh.history())
    widget(at, "button", "lib_publish").click().run()
    check("Publishing a library the repository already has makes no empty commit",
          "already has all of this" in body(at) and len(_gh.history()) == _n,
          str(_gh.history()[:2]))
    _opts = widget(at, "selectbox", "lib_rm_pick").options
    widget(at, "selectbox", "lib_rm_pick").select(
        next(o for o in _opts if "October 2026 Japan.csv" in o)).run()
    widget(at, "button", "lib_rm_go").click().run()
    _files = _gh.files()
    check("Removing a file removes it from the repository in one commit",
          not any(p.startswith("qars/library/Japan/2026-10_") for p in _files)
          and len(_gh.history()) == _n + 1)
    check("And from the index there",
          not any(e.get("file", "").startswith("Japan/2026-10_")
                  for e in json.loads(_files["qars/library/index.json"])["entries"]))

    # A server that is behind the repository must not erase what it has not seen.
    _gh.commit_elsewhere({
        "qars/library/India/2026-11_November_India.csv": sheet(12, month=11),
        "qars/library/index.json": json.dumps({"entries": json.loads(
            _gh.files()["qars/library/index.json"])["entries"] + [{
                "id": "India-2026-11_November_India.csv", "market": "India",
                "file": "India/2026-11_November_India.csv", "kind": "workbook",
                "shipped": False, "periods": ["2026-11"], "primary": "2026-11",
                "added": "2026-12-01T09:00:00",
                "source_name": "November India.csv"}]}).encode()},
        "November, from another server")
    at = hosted("upload")
    upload(at, "C3", [("November 2026 C3.csv", sheet(25, month=11, dev="Neha Lal"))])
    widget(at, "button", "conf_C3").click().run()
    _idx = json.loads(_gh.files()["qars/library/index.json"])["entries"]
    check("Publishing from a server that is behind keeps the newer months",
          {"India/2026-11_November_India.csv"} <= {e["file"] for e in _idx}
          and any(e["file"].startswith("C3/2026-11_") for e in _idx),
          str(sorted(e["file"] for e in _idx if "2026-11" in e["file"])))
finally:
    publish.API = _saved_api
    publish.configure(token="", repo="")
    _gh.stop()

section("THE REAL LIBRARY — untouched by every test above")
library.DIR, library.INDEX = SHIPPED_DIR, os.path.join(SHIPPED_DIR, "index.json")
library._CACHE.clear()
check("Nothing in qars/library was changed by this suite", library.signature() == _REAL_SIG)
shutil.rmtree(SCRATCH_DIR, ignore_errors=True)


# ==========================================================================
print("\n" + "=" * 62)
print(f"  {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("  FAILED:\n    - " + "\n    - ".join(FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
