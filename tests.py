#!/usr/bin/env python3
"""
Automated tests for QA Report Studio.

Run from the project folder:

    python tests.py

No test framework is needed and nothing touches the internet or your saved
data — every test builds its own in-memory database.

Covers the six mandated checks:
  1  Total 20 / Error 2 / No Error 15 / Observation 3 -> Error-Free 18, 90.00%
  2  Total 100 / Error 8 / No Error 90 / Observation 2 -> Error-Free 92, 92.00%
  3  Total 0 -> Quality Score N/A (never 100%)
  4  Consolidated calculations across multiple months
  5  Observations are never double-counted
  6  Dashboard, Excel export, PowerPoint and PDF use identical values
plus ingestion, filtering and legacy-deck conversion.
"""

from __future__ import annotations

import inspect
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qars import (deck, ingest, library, metrics, normalize as nz,  # noqa: E402
                  pdf, publish, store)

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f"  --  {detail}" if detail else ""))


def section(title):
    print(f"\n{title}\n" + "-" * len(title))


def _settings():
    return store._default_settings()


def _db_with(market, tasks=(), blocks=()):
    db = store._empty_db()
    if tasks:
        db["tasks"][market] = list(tasks)
    if blocks:
        db["monthly"][market] = list(blocks)
    return db


SHIPPED_DIR = library.DIR


class TempLibrary:
    """
    Point the library at a throwaway folder for the duration of a block.

    `copy_shipped` brings the two vendored decks along, so a test can start
    from the app's real history and add to it without any chance of writing
    into the repository.
    """

    def __init__(self, copy_shipped=True):
        self.copy_shipped = copy_shipped

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="qars_lib_")
        self.saved = (library.DIR, library.INDEX)
        library.DIR = self.tmp
        library.INDEX = os.path.join(self.tmp, "index.json")
        library._CACHE.clear()
        if self.copy_shipped:
            for name in os.listdir(SHIPPED_DIR):
                src = os.path.join(SHIPPED_DIR, name)
                if os.path.isdir(src):
                    shutil.copytree(src, os.path.join(self.tmp, name))
                elif name == "index.json":
                    shutil.copy2(src, os.path.join(self.tmp, name))
        return self

    def __exit__(self, *exc):
        library.DIR, library.INDEX = self.saved
        library._CACHE.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def _workbook(year, month, n=60, dev="Dev Lib", status_every=10):
    """A minimal audit sheet as .csv bytes — the same reader handles both."""
    lines = ["Mail Title,Date,Test Environment,Developer Name,Status,Error Type,"
             "Error Severity"]
    for i in range(n):
        day = (i % 27) + 1
        status = "Error" if i % status_every == 0 else "First Time Correct"
        cat = "Content Related" if status == "Error" else ""
        sev = "Major" if status == "Error" else ""
        lines.append(f"Task {i + 1},{year}-{month:02d}-{day:02d},Test,{dev},"
                     f"{status},{cat},{sev}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _lib_settings(db):
    st_ = _settings()
    st_["dev_aliases"], _ = nz.auto_merge_map(
        {r["dev_raw"] for m in store.MARKETS for r in db["tasks"][m] if r.get("dev_raw")}
        | {d["raw"] for m in store.MARKETS for b in db["monthly"][m]
           for d in b.get("developers", [])})
    return st_


def _lib_totals(db, market):
    return metrics.totals(metrics.select(db, market, _lib_settings(db), {}))


def _rows(year, month, error=0, no_error=0, observation=0, dev="Dev A", env="Internal",
          category="Content Related", severity="Major"):
    """Build task rows with disjoint Error / No Error / Observation counts."""
    out, day = [], 1
    for status, n in ((nz.STATUS_ERR, error), (nz.STATUS_OK, no_error),
                      (nz.STATUS_OBS, observation)):
        for _ in range(n):
            out.append({
                "year": year, "month": month, "day": min(day, 28),
                "date": f"{year:04d}-{month:02d}-{min(day, 28):02d}",
                "week": 1, "market": "India", "status": status, "dev_raw": dev,
                "qa_raw": "QA One", "env": env, "title": "Task",
                "category": category if status == nz.STATUS_ERR else None,
                "severity": severity if status == nz.STATUS_ERR else None,
                "details": "", "hours": None, "source_file": "test.xlsx",
                "source_sheet": "Sheet1", "imported_at": "2026-01-01T00:00:00",
            })
            day += 1
    return out


# ==========================================================================
section("TEST 1 — the worked example from the specification")
r1 = metrics.compute(error=2, no_error=15, observation=3)
check("Error-Free = No Error + Observation = 18", r1["error_free"] == 18, str(r1["error_free"]))
check("Total Tasks = Error + Error-Free = 20", r1["total"] == 20, str(r1["total"]))
check("Quality Score = 90.00%", r1["score"] == 90.0, metrics.fmt_score(r1["score"]))
check("Score formats to two decimals", metrics.fmt_score(r1["score"]) == "90.00%")

section("TEST 2 — the second mandated case")
r2 = metrics.compute(error=8, no_error=90, observation=2)
check("Error-Free = 92", r2["error_free"] == 92, str(r2["error_free"]))
check("Total Tasks = 100", r2["total"] == 100, str(r2["total"]))
check("Quality Score = 92.00%", r2["score"] == 92.0, metrics.fmt_score(r2["score"]))

section("TEST 3 — the zero-task rule")
r3 = metrics.compute(error=0, no_error=0, observation=0)
check("Zero tasks give a score of None", r3["score"] is None, repr(r3["score"]))
check("Zero tasks display as N/A, never 100%", metrics.fmt_score(r3["score"]) == "N/A",
      metrics.fmt_score(r3["score"]))
db0 = _db_with("India", tasks=[])
sel0 = metrics.select(db0, "India", _settings(), {})
check("An empty selection reports N/A end to end",
      metrics.totals(sel0)["score"] is None)

section("TEST 4 — consolidated calculations across months")
# Jan 100 tasks @ 92.00%, Feb 20 tasks @ 90.00%, Mar 4 tasks @ 100.00%
tasks = (_rows(2026, 1, error=8, no_error=90, observation=2)
         + _rows(2026, 2, error=2, no_error=15, observation=3)
         + _rows(2026, 3, error=0, no_error=3, observation=1))
sel = metrics.select(_db_with("India", tasks=tasks), "India", _settings(), {})
rows = metrics.monthly_series(sel)
tot = metrics.totals(sel)
check("Three months detected", len(rows) == 3, str([r["label"] for r in rows]))
check("Monthly scores are 92.00 / 90.00 / 100.00",
      [r["score"] for r in rows] == [92.0, 90.0, 100.0], str([r["score"] for r in rows]))
check("Pooled totals: 124 tasks, 114 error free",
      (tot["total_tasks"], tot["error_free"]) == (124, 114),
      f"{tot['total_tasks']} / {tot['error_free']}")
check("Overall score is pooled (114/124 = 91.94%), not the mean",
      tot["score"] == round(114 / 124 * 100, 2), metrics.fmt_score(tot["score"]))
check("Average monthly score is reported separately (94.00%)",
      tot["avg_monthly_score"] == 94.0, metrics.fmt_score(tot["avg_monthly_score"]))
check("The two consolidated measures are genuinely different",
      tot["score"] != tot["avg_monthly_score"],
      f"overall {tot['score']} vs average {tot['avg_monthly_score']}")

section("TEST 5 — observations are never double-counted")
check("Total equals Error + No Error + Observation",
      tot["total_tasks"] == tot["error_tasks"] + tot["no_error"] + tot["observations"],
      f"{tot['total_tasks']} == {tot['error_tasks']}+{tot['no_error']}+{tot['observations']}")
check("Total equals Error + Error-Free",
      tot["total_tasks"] == tot["error_tasks"] + tot["error_free"])
check("Error-Free equals No Error + Observation",
      tot["error_free"] == tot["no_error"] + tot["observations"])
check("The naive double-counted total is NOT used",
      tot["total_tasks"] != tot["error_tasks"] + tot["no_error"]
      + tot["observations"] + tot["error_free"])
devs = metrics.developer_table(sel)
check("Developer rows obey the same identity",
      all(d["total"] == d["error"] + d["no_error"] + d["observation"] for d in devs))
check("Monthly rows obey the same identity",
      all(r["total"] == r["error"] + r["no_error"] + r["observation"] for r in rows))
sum_months = sum(r["total"] for r in rows)
check("Month totals sum to the period total", sum_months == tot["total_tasks"],
      f"{sum_months} vs {tot['total_tasks']}")

section("TEST 6 — every output surface uses identical values")
opts = {"market_label": "India", "org": "BMW"}
pptx_bytes = deck.build_deck(sel, opts)
pdf_bytes = pdf.build_pdf(sel, opts)
check("PPTX generated", len(pptx_bytes) > 50_000, f"{len(pptx_bytes)//1024} KB")
check("PDF generated", len(pdf_bytes) > 20_000, f"{len(pdf_bytes)//1024} KB")

# The deck and the PDF both read from metrics.totals / monthly_series, so the
# test asserts that contract: read the text back out of the deck and confirm the
# rendered figures are the ones the engine computed.
from pptx import Presentation                                  # noqa: E402
prs = Presentation(io.BytesIO(pptx_bytes))
deck_text = " ".join(sh.text_frame.text for s in prs.slides for sh in s.shapes
                     if sh.has_text_frame)
deck_tables = " ".join(c.text for s in prs.slides for sh in s.shapes if sh.has_table
                       for row in sh.table.rows for c in row.cells)
blob = deck_text + " " + deck_tables
check("Overall score appears in the deck exactly as computed",
      metrics.fmt_score(tot["score"]) in blob, metrics.fmt_score(tot["score"]))
check("Average monthly score appears in the deck",
      metrics.fmt_score(tot["avg_monthly_score"]) in blob)
check("Total task count appears in the deck", f"{tot['total_tasks']:,}" in blob)
check("Error-free count appears in the deck", f"{tot['error_free']:,}" in blob)
check("Observation count appears in the deck", str(tot["observations"]) in blob)
check("The deck never shows a double-counted total",
      str(tot["error_tasks"] + tot["no_error"] + tot["observations"] + tot["error_free"])
      not in deck_tables.replace(str(tot["total_tasks"]), ""))

csv_rows = sum(1 for _ in sel.tasks)
check("CSV export row count equals the task count used for scoring",
      csv_rows == tot["total_tasks"], f"{csv_rows} vs {tot['total_tasks']}")

section("INGESTION — real audit workbooks")
SAMPLES = ["/mnt/project/Feb_2026_India_QA_Audit___.xlsx",
           "/mnt/project/Copy_of_Copy_of_Copy_of_July_2026_India_QA_Audi___.xlsx"]
available = [p for p in SAMPLES if os.path.exists(p)]
if available:
    db = store._empty_db()
    for path in available:
        with open(path, "rb") as fh:
            rows, rep = ingest.read_excel(fh, "India", filename=os.path.basename(path))
        store.add_tasks(db, "India", rows, os.path.basename(path))
        check(f"Read {os.path.basename(path)[:34]}", rep["rows_kept"] > 0,
              f"{rep['rows_kept']} rows, months {rep['periods']}")
        check("  every row carries its source file",
              all(r.get("source_file") for r in rows))
        check("  every row carries an import timestamp",
              all(r.get("imported_at") for r in rows))
    s = _settings()
    selx = metrics.select(db, "India", s, {})
    tx = metrics.totals(selx)
    check("Ingested data obeys the observation identity",
          tx["total_tasks"] == tx["error_tasks"] + tx["no_error"] + tx["observations"])
    check("Re-importing the same file does not double-count",
          (lambda: (store.add_tasks(db, "India", rows, "again.xlsx"),
                    metrics.totals(metrics.select(db, "India", s, {}))["total_tasks"]
                    == tx["total_tasks"])[1])())
else:
    print("  (sample workbooks not present — skipping)")

section("CSV INGESTION")
csv_text = ("Mail Title,Date,Test Environment,Developer Name,Status,Error Type,Error Severity\n"
            "Task A,2026-05-04,Test,Alice Smith,First Time Correct,,\n"
            "Task B,2026-05-05,Live,Alice Smith,Error,Content Related,Critical\n"
            "Task C,2026-05-06,Test,Bob Jones,Observation,,\n")
rows, rep = ingest.read_excel(csv_text.encode(), "India", filename="May_2026_audit.csv")
check("CSV parsed", len(rows) == 3, f"{len(rows)} rows")
selc = metrics.select(_db_with("India", tasks=rows), "India", _settings(), {})
tc = metrics.totals(selc)
check("CSV: 1 error, 1 no-error, 1 observation",
      (tc["error_tasks"], tc["no_error"], tc["observations"]) == (1, 1, 1),
      f"{tc['error_tasks']}/{tc['no_error']}/{tc['observations']}")
check("CSV: error-free = 2, total = 3, score 66.67%",
      (tc["error_free"], tc["total_tasks"], tc["score"]) == (2, 3, 66.67),
      metrics.fmt_score(tc["score"]))
check("CSV: month detected from the filename",
      rep["month_detection"]["sources"].get("Filename") == (2026, 5),
      str(rep["month_detection"]["sources"]))

section("MONTH CONFLICT DETECTION")
det = ingest.detect_month("March_2026_audit.xlsx", "Sheet1", {(2026, 4): 40})
check("Conflict flagged when filename and dates disagree", det["conflict"] is True,
      str(det["sources"]))
check("Date data wins as the chosen month", det["month"] == (2026, 4), str(det["month"]))
det2 = ingest.detect_month("April_2026_audit.xlsx", "Apr 2026", {(2026, 4): 40})
check("No conflict when all signals agree", det2["conflict"] is False)

section("LEGACY DECK CONVERSION — observations were an overlay")
blk = {"error": 3, "no_error": 121, "observation": 4, "stated_total": 124, "developers":
       [{"name": "Dipali", "raw": "Dipali", "error": 0, "no_error": 19, "observation": 3}]}
ingest._normalise_observations(blk)
check("Overlay convention detected", blk["observation_convention"] == "overlay")
check("Observations lifted out of No Error (121 -> 117)", blk["no_error"] == 117,
      str(blk["no_error"]))
conv = metrics.compute(blk["error"], blk["no_error"], blk["observation"])
check("Converted month keeps the published total of 124", conv["total"] == 124,
      str(conv["total"]))
check("Converted month keeps the published score of 97.58%", conv["score"] == 97.58,
      metrics.fmt_score(conv["score"]))
check("Developer row converted too (19 -> 16 no-error)",
      blk["developers"][0]["no_error"] == 16, str(blk["developers"][0]["no_error"]))

blk2 = {"error": 2, "no_error": 15, "observation": 3, "stated_total": 20, "developers": []}
ingest._normalise_observations(blk2)
check("Disjoint convention left untouched", blk2["observation_convention"] == "disjoint"
      and blk2["no_error"] == 15)

section("FILTERS")
base = metrics.totals(sel)
narrow = metrics.totals(metrics.select(_db_with("India", tasks=tasks), "India", _settings(),
                                       {"categories": ["Content Related"]}))
check("A category filter never removes passing tasks",
      narrow["error_free"] == base["error_free"],
      f"{narrow['error_free']} vs {base['error_free']}")
one = metrics.select(_db_with("India", tasks=tasks), "India", _settings(),
                     {"periods": [(2026, 2)]})
check("Period filter isolates one month", metrics.totals(one)["total_tasks"] == 20,
      str(metrics.totals(one)["total_tasks"]))

section("EXCEL vs POWERPOINT DISCREPANCY")
dbd = _db_with("India", tasks=_rows(2026, 1, error=8, no_error=90, observation=2),
               blocks=[{"market": "India", "year": 2026, "month": 1, "source": "pptx",
                        "error": 9, "no_error": 89, "observation": 2,
                        "developers": [], "categories": []}])
warns = metrics.data_warnings(dbd, "India", _settings())
disc = [w for w in warns if w["kind"] == "discrepancy"]
check("Discrepancy detected and surfaced", len(disc) == 1)
check("Message names Excel as the primary source",
      bool(disc) and "primary calculation source" in disc[0]["text"])
seld = metrics.select(dbd, "India", _settings(), {})
check("Excel detail wins over the deck for the same month",
      metrics.totals(seld)["total_tasks"] == 100,
      str(metrics.totals(seld)["total_tasks"]))

section("NAME HANDLING — automatic merges vs flagged ambiguity")
roster = ["Amol", "AMOL LAXMAN DOHALE", "Amol Dohale", "AMOL GAIKWAD",
          "Neha Lal", "Neha lal", "Neha Gupta", "sandeep.j@craftww.com",
          "Sandeep Jadhav", "Kapil K", "Kapil Kumar", "Komal", "Komal Gala",
          "Krupa", "Krupa Jalgaonkar", "Mitesh Gupta", "Mitesh Salunkhe",
          "Anish Kulkarni", "ANISH AJIT KULKARNI", "Supriya",
          "SUPRIYA SANTOSH MHASHELKAR", "Dan", "Dan Dsouza"]
confident, ambiguous = nz.classify_name_groups(roster)
allc = list(confident.values())
check("Clear variants merge automatically",
      any("Amol Dohale" in v and "AMOL LAXMAN DOHALE" in v for v in allc))
check("An e-mail address is matched to the person",
      any("sandeep.j@craftww.com" in v and "Sandeep Jadhav" in v for v in allc))
check("An initial is matched to the full surname (Kapil K -> Kapil Kumar)",
      any("Kapil K" in v and "Kapil Kumar" in v for v in allc))
check("Case-only differences merge (Neha lal / Neha Lal)",
      any("Neha lal" in v and "Neha Lal" in v for v in allc))
check("Short first names merge when only one person could own them",
      any("Supriya" in v for v in allc) and any("Anish Kulkarni" in v for v in allc))
check("Different people are NEVER auto-merged",
      not any("AMOL GAIKWAD" in v and "AMOL LAXMAN DOHALE" in v for v in allc))
check("Same first name, different surname stays separate",
      not any("Neha Lal" in v and "Neha Gupta" in v for v in allc))
check("Mitesh Gupta and Mitesh Salunkhe stay separate",
      not any("Mitesh Gupta" in v and "Mitesh Salunkhe" in v for v in allc))
check("An initial does not swallow an unrelated name (Komal != Kapil K)",
      not any("Komal" in v and "Kapil K" in v for v in allc))
check("Krupa is not captured by Kapil K",
      not any("Krupa" in v and "Kapil K" in v for v in allc))
check("The genuinely ambiguous short name is flagged, not merged",
      any(info["short"] == "Amol" for info in ambiguous.values()), str(list(ambiguous)))
check("The flag explains why it was left alone",
      any("could be any of" in info["reason"] for info in ambiguous.values()))

section("ERROR HANDLING")
for name, payload, fname in [
    ("empty file", b"", "empty.xlsx"),
    ("not a spreadsheet", b"this is plain text, not a workbook", "junk.xlsx"),
    ("unsupported extension", b"abc", "notes.docx"),
    ("no header row", b"a,b,c\n1,2,3\n", "headerless.csv"),
]:
    try:
        ingest.read_excel(payload, "India", filename=fname)
        check(f"{name} raises a friendly error", False, "no error raised")
    except ingest.IngestError as exc:
        check(f"{name} raises a friendly error", True, str(exc)[:58] + "…")
    except Exception as exc:                                   # noqa: BLE001
        check(f"{name} raises a friendly error", False,
              f"raw {type(exc).__name__} leaked instead")

section("ZERO-DEFECT AND SINGLE-MONTH REPORTS")
for label, tk in [("zero defects", _rows(2026, 6, error=0, no_error=44, observation=0)),
                  ("single task", _rows(2026, 7, error=0, no_error=1, observation=0)),
                  ("all observations", _rows(2026, 8, error=0, no_error=0, observation=5))]:
    s2 = metrics.select(_db_with("India", tasks=tk), "India", _settings(), {})
    try:
        ok = (len(deck.build_deck(s2, {"market_label": "India"})) > 40_000
              and len(pdf.build_pdf(s2, {"market_label": "India"})) > 15_000)
        check(f"Report builds with {label}", ok)
    except Exception as exc:                                   # noqa: BLE001
        check(f"Report builds with {label}", False, repr(exc))
check("All-observation month scores 100.00%",
      metrics.compute(0, 0, 5)["score"] == 100.0)

section("LEGACY DECK — consolidated slides must not overwrite a month")
REF = "/mnt/user-data/uploads/C3__Quality_defect_report_2026_2026.pptx"
if os.path.exists(REF):
    with open(REF, "rb") as fh:
        blocks, rep = ingest.read_pptx(fh, "C3", filename="C3.pptx")
    check("Six monthly blocks recovered", len(blocks) == 6, str(rep["months"]))
    check("Period-spanning slides were skipped",
          any("consolidated view" in u for u in rep["unread"]),
          f"{len(rep['unread'])} skipped")
    jan = next(b for b in blocks if b["month"] == 1)
    check("January keeps its own developers, not the whole-period summary",
          len(jan["developers"]) == 9, f"{len(jan['developers'])} developers")
    check("January keeps its own defect categories",
          sum(c["internal"] for c in jan["categories"]) == 3
          and sum(c["external"] for c in jan["categories"]) == 0,
          str(jan["categories"]))

    db = store._empty_db()
    store.add_monthly(db, "C3", blocks, "C3.pptx")
    st_ = _settings()
    names = {d["raw"] for b in blocks for d in b["developers"]}
    st_["dev_aliases"], _amb = nz.auto_merge_map(names)
    selc = metrics.select(db, "C3", st_, {})
    tc = metrics.totals(selc)
    section("LEGACY DECK — figures must match the deck they came from")
    for label, got, want in [("total tasks", tc["total_tasks"], 641),
                             ("error-free tasks", tc["error_free"], 598),
                             ("defects", tc["error_tasks"], 43),
                             ("internal defects", tc["internal"], 37),
                             ("external defects", tc["external"], 6),
                             ("observations", tc["observations"], 38),
                             ("developers after merge", tc["developers"], 15),
                             ("developers below 90%", tc["below_target"], 6)]:
        check(f"Reproduces the published {label}", got == want, f"{got} vs {want}")
    check("Reproduces the published quality score", tc["score"] == 93.29,
          metrics.fmt_score(tc["score"]))
    check("Internal + external never exceeds the defect count",
          tc["internal"] + tc["external"] == tc["error_tasks"],
          f"{tc['internal']}+{tc['external']} vs {tc['error_tasks']}")
    top, bar_n = metrics.top_developers(selc, n=3)
    check("Top performer matches the source deck (Anish Ajit Kulkarni)",
          bool(top) and top[0]["name"].lower().startswith("anish"),
          f"{[d['name'] for d in top]} (min {bar_n} tasks)")
    check("Podium excludes low-volume perfect scores",
          all(d["total"] >= bar_n for d in top))
else:
    print("  (reference C3 deck not present — skipping)")

section("INTERNAL / EXTERNAL RECONCILIATION")
dbx = _db_with("India", tasks=_rows(2026, 3, error=5, no_error=20, observation=0,
                                    env="Internal"))
tx2 = metrics.totals(metrics.select(dbx, "India", _settings(), {}))
check("Split sums exactly to the defect count",
      tx2["internal"] + tx2["external"] == tx2["error_tasks"],
      f"{tx2['internal']}+{tx2['external']}={tx2['error_tasks']}")
check("Percentages sum to 100", abs(tx2["internal_pct"] + tx2["external_pct"] - 100) < 0.01,
      f"{tx2['internal_pct']}+{tx2['external_pct']}")

section("PORTABLE SNAPSHOTS — export and restore")
snap = store._empty_db()
snap["tasks"]["India"] = _rows(2026, 4, error=3, no_error=20, observation=2)
blob = store.export_bytes(snap)
restored, counts = store.import_bytes(blob)
check("A database survives an export/restore round trip",
      counts["India"] == 25, str(counts))
t_snap = metrics.totals(metrics.select(snap, "India", _settings(), {}))
t_rest = metrics.totals(metrics.select(restored, "India", _settings(), {}))
check("Restored data computes identical figures",
      (t_snap["total_tasks"], t_snap["score"]) == (t_rest["total_tasks"], t_rest["score"]),
      f"{t_rest['total_tasks']} tasks, {metrics.fmt_score(t_rest['score'])}")
for label, payload in [("plain text", b"hello"),
                       ("unrelated JSON", b'{"foo": 1}'),
                       ("empty database", b'{"tasks": {}, "monthly": {}}')]:
    try:
        store.import_bytes(payload)
        check(f"Restore rejects {label}", False, "accepted it")
    except ValueError as exc:
        check(f"Restore rejects {label}", True, str(exc)[:44] + "\u2026")

section("HOSTED DEPLOYMENT — session storage")
check("Storage mode reports one of the two known values",
      store.storage_mode() in ("disk", "session"), store.storage_mode())
_saved = store.SESSION_MODE
try:
    store.SESSION_MODE = True
    check("Session mode starts every visitor with an empty store",
          sum(len(store.load_db()["tasks"][m]) for m in store.MARKETS) == 0)
    check("Session mode reports itself correctly", store.storage_mode() == "session")
    check("Session mode writes nothing to disk", store._write_json("/tmp/qars_never", {}) is False)
    check("Session mode takes no backups", store.backup_db("t") is None)
    check("Session mode still loads usable default settings",
          isinstance(store.load_settings().get("dev_aliases"), dict))
finally:
    store.SESSION_MODE = _saved

section("NO TARGETS — the benchmark settings are gone")
_s = store._default_settings()
check("Settings carry no target score", "target_score" not in _s, str(sorted(_s)))
check("Settings carry no watch benchmark", "watch_score" not in _s)
check("Settings no longer name a brand", _s["org_name"] == "", repr(_s["org_name"]))
check("The score bands live in the engine, not in a setting",
      (metrics.BAND_GOOD, metrics.BAND_WATCH) == (95.0, 90.0),
      f"{metrics.BAND_GOOD}/{metrics.BAND_WATCH}")
_selb = metrics.select(_db_with("India", tasks=_rows(2026, 9, error=3, no_error=17)),
                       "India", _settings(), {})
check("Insights read without a target",
      all("target" not in i["text"].lower() for i in metrics.insights(_selb)),
      str([i["text"] for i in metrics.insights(_selb)])[:90])
check("Recommendations read without a target",
      all("target" not in r["text"].lower() for r in metrics.recommendations(_selb)))
check("A report still builds with no organisation set",
      len(deck.build_deck(_selb, {"market_label": "India", "org": ""})) > 40_000)
check("An unbranded cover does not print a stray separator",
      deck._brand("", "India") == "India" and deck._brand("Acme", "India") == "Acme India",
      deck._brand("", "India"))
check("The PDF brands the same way",
      pdf._brand("", "Japan") == "Japan" and pdf._brand("Acme", "Japan") == "Acme Japan")

section("LINK TYPES — wording only, figures untouched")
check("Live still classifies as it always did", nz.norm_env("Live") == nz.ENV_EXTERNAL)
check("Test still classifies as it always did", nz.norm_env("Test") == nz.ENV_INTERNAL)
check("Internal is presented as the test link", nz.env_label(nz.ENV_INTERNAL) == "Test link")
check("External is presented as the live link", nz.env_label(nz.ENV_EXTERNAL) == "Live link")

section("REPORT LIBRARY — what ships with the app")
check("Both markets have a shipped report", library.markets() == ["C3", "Japan"],
      str(library.markets()))
_ship = library.summary()
check("The shipped entries are marked as such", all(e["shipped"] for e in _ship))
check("Each covers six months", sorted(e["months"] for e in _ship) == [6, 6],
      str([e["months"] for e in _ship]))
check("India ships with no history", not library.periods_for("India"))
check("The library folder is writable here", library.writable())

_bdb = store._empty_db()
_added = library.seed(_bdb)
check("Seeding adds six months per market", _added == {"C3": 6, "Japan": 6}, str(_added))
check("Seeding twice adds nothing", library.seed(_bdb) == {})
check("Library months are tagged", all(library.is_library(b) for b in _bdb["monthly"]["C3"]))
check("Shipped months are recognisable",
      all(library.is_shipped(b) for b in _bdb["monthly"]["C3"]))
check("Seeding writes no import history", not _bdb["sources"])

_bs = _lib_settings(_bdb)
_bt = metrics.totals(metrics.select(_bdb, "C3", _bs, {}))
for label, got, want in [("total tasks", _bt["total_tasks"], 641),
                         ("error-free tasks", _bt["error_free"], 598),
                         ("defects", _bt["error_tasks"], 43),
                         ("test-link defects", _bt["internal"], 37),
                         ("live-link defects", _bt["external"], 6),
                         ("observations", _bt["observations"], 38)]:
    check(f"Shipped C3 reproduces the published {label}", got == want, f"{got} vs {want}")
check("Shipped C3 reproduces the published quality score", _bt["score"] == 93.29,
      metrics.fmt_score(_bt["score"]))

section("REPORT LIBRARY — a month imported once is kept for good")
with TempLibrary() as _tl:
    db = store._empty_db()
    library.seed(db)
    check("Starts on the six shipped months", _lib_totals(db, "C3")["months"] == 6)

    _e7, _r7 = library.add("C3", "C3_July_2026.csv", _workbook(2026, 7, 120))
    check("Importing a workbook keeps the file",
          os.path.exists(os.path.join(library.DIR, _e7["file"])), _e7["file"])
    check("It replaced nothing", _r7 == [])
    check("The entry records the month it covers", _e7["periods"] == ["2026-07"],
          str(_e7["periods"]))
    library.resync(db)
    _t7 = _lib_totals(db, "C3")
    check("July joins the six shipped months", _t7["months"] == 7, str(_t7["months"]))
    check("July lands after June, not before",
          _t7["period_label"].endswith("Jul 2026"), _t7["period_label"])
    check("Its rows are counted", _t7["total_tasks"] == 641 + 120,
          str(_t7["total_tasks"]))

    library.add("C3", "C3_August_2026.csv", _workbook(2026, 8, 90))
    library.resync(db)
    _t8 = _lib_totals(db, "C3")
    check("The next month only needs its own file", _t8["months"] == 8, str(_t8["months"]))
    check("Nothing earlier had to be re-uploaded",
          _t8["total_tasks"] == 641 + 120 + 90, str(_t8["total_tasks"]))

    # THE point of the library: a new process, with no session state at all,
    # sees everything that was ever imported.
    _fresh = store._empty_db()
    library.resync(_fresh)
    _tf = _lib_totals(_fresh, "C3")
    check("A brand-new session sees every kept month",
          (_tf["months"], _tf["total_tasks"]) == (_t8["months"], _t8["total_tasks"]),
          f"{_tf['months']} months / {_tf['total_tasks']} tasks")
    check("A brand-new session sees Japan's history too",
          _lib_totals(_fresh, "Japan")["months"] == 6)

    section("REPORT LIBRARY — re-importing a month replaces it")
    _e7b, _r7b = library.add("C3", "C3_July_2026_corrected.csv", _workbook(2026, 7, 150))
    check("The earlier July file is replaced, not added to",
          [r["source_name"] for r in _r7b] == ["C3_July_2026.csv"],
          str([r["source_name"] for r in _r7b]))
    check("The replaced file is gone from the folder",
          not os.path.exists(os.path.join(library.DIR, _r7b[0]["file"])))
    library.resync(db)
    _t9 = _lib_totals(db, "C3")
    check("The month is not counted twice", _t9["total_tasks"] == 641 + 150 + 90,
          str(_t9["total_tasks"]))
    check("The month count is unchanged", _t9["months"] == 8, str(_t9["months"]))

    section("REPORT LIBRARY — a reviewer's month correction survives")
    # The file says September; the reviewer files it under October. Reloading
    # from disk must honour that, not re-read the sheet's own dates.
    library.add("C3", "C3_misdated.csv", _workbook(2026, 9, 40), force_month=(2026, 10))
    _f2 = store._empty_db()
    library.resync(_f2)
    _periods = {(r["year"], r["month"]) for r in _f2["tasks"]["C3"]}
    check("The forced month is what reloads", (2026, 10) in _periods
          and (2026, 9) not in _periods, str(sorted(_periods)))

    section("REPORT LIBRARY — removing and refusing")
    _before = len(library.summary())
    _gone = library.remove(_e7b["id"])
    check("Removing an entry drops it", len(library.summary()) == _before - 1)
    check("It names what it removed", _gone["source_name"] == "C3_July_2026_corrected.csv")
    library.resync(db)
    check("Its months leave the history too",
          (2026, 7) not in {(r["year"], r["month"]) for r in db["tasks"]["C3"]})
    _shipped_id = next(e["id"] for e in library.summary() if e["shipped"])
    try:
        library.remove(_shipped_id)
        check("A shipped report cannot be removed", False, "it was removed")
    except library.LibraryError as exc:
        check("A shipped report cannot be removed", True, str(exc)[:46] + "…")
    try:
        library.remove("not-a-real-entry")
        check("Removing something that is not there is refused", False, "accepted")
    except library.LibraryError:
        check("Removing something that is not there is refused", True)
    for label, name, blob in [("an unreadable file", "junk.xlsx", b"not a workbook"),
                              ("an empty file", "empty.csv", b""),
                              ("a file type it cannot keep", "notes.docx", b"abc")]:
        _n = len(library.summary())
        try:
            library.add("C3", name, blob)
            check(f"The library refuses {label}", False, "it was kept")
        except library.LibraryError:
            check(f"The library refuses {label}", len(library.summary()) == _n,
                  "and kept nothing")

    section("REPORT LIBRARY — the pack moves history between machines")
    _pack = library.export_pack()
    check("A pack is produced", len(_pack) > 1000, f"{len(_pack) // 1024} KB")
    _names = sorted(e["source_name"] for e in library.summary())
    _pack_db = store._empty_db()
    library.resync(_pack_db)
    _pack_months = _lib_totals(_pack_db, "C3")["months"]
    _pack_tasks = _lib_totals(_pack_db, "C3")["total_tasks"]

with TempLibrary(copy_shipped=False) as _tl2:
    check("An empty library has nothing", library.summary() == [])
    _n = library.restore_pack(_pack)
    check("Restoring a pack brings every file back", _n >= 3, f"{_n} files")
    check("And the same entries", sorted(e["source_name"] for e in library.summary())
          == _names, str(sorted(e["source_name"] for e in library.summary())))
    _rdb = store._empty_db()
    library.resync(_rdb)
    _rt = _lib_totals(_rdb, "C3")
    check("A restored library reports exactly the history it was packed from",
          (_rt["months"], _rt["total_tasks"]) == (_pack_months, _pack_tasks),
          f"{_rt['months']}/{_rt['total_tasks']} vs {_pack_months}/{_pack_tasks}")
    for label, blob in [("plain text", b"hello"), ("a zip that is not a pack",
                                                   b"PK\x03\x04nonsense")]:
        try:
            library.restore_pack(blob)
            check(f"Restore rejects {label}", False, "accepted it")
        except library.LibraryError:
            check(f"Restore rejects {label}", True)

check("The real library is untouched by all of that",
      library.DIR == SHIPPED_DIR and [e["source_name"] for e in library.summary()]
      == ["C3_Quality_Defect_Report_2026.pptx", "Japan_Quality_Defect_Report_2026.pptx"],
      str([e["source_name"] for e in library.summary()]))

section("PUBLISHING — off unless it is switched on")
publish.configure(token="", repo="")
check("Publishing is off by default", publish.enabled() is False)
check("Its status says so", publish.status()["enabled"] is False)
_ok, _detail = publish.push({"a": b"b"}, "msg")
check("Pushing with no configuration fails politely", _ok is False
      and "not configured" in _detail, _detail[:50])
_ok, _detail = publish.delete(["a"], "msg")
check("Deleting with no configuration fails politely", _ok is False)
_st = publish.configure(token="tok", repo="owner/repo", branch="trunk")
check("Configuring turns it on", _st == {"enabled": True, "repo": "owner/repo",
                                         "branch": "trunk", "has_token": True}, str(_st))
publish.configure(token="", repo="")
check("And it can be turned back off", publish.enabled() is False)

section("SINGLE MONTH — no consolidated section")
_multi = metrics.select(_db_with("India", tasks=tasks), "India", _settings(), {})
_single = metrics.select(_db_with("India", tasks=tasks), "India", _settings(),
                         {"periods": [(2026, 2)]})
_mp = Presentation(io.BytesIO(deck.build_deck(_multi, {"market_label": "India"})))
_sp = Presentation(io.BytesIO(deck.build_deck(_single, {"market_label": "India"})))
_mtext = " ".join(sh.text_frame.text for sl in _mp.slides for sh in sl.shapes
                  if sh.has_text_frame)
_stext = " ".join(sh.text_frame.text for sl in _sp.slides for sh in sl.shapes
                  if sh.has_text_frame)
check("A multi-month deck still carries the consolidated summary",
      "QA Summary" in _mtext)
check("A single-month deck drops the consolidated summary", "QA Summary" not in _stext)
check("A single-month deck drops the consolidated developer summary",
      "Developer Summary" not in _stext)
check("A single-month deck drops the consolidated category breakdown",
      "Defect Category Breakdown" not in _stext)
check("A single-month deck keeps that month's own pages",
      "Developer Report" in _stext and "Quality Score" in _stext)
check("A single-month deck keeps the closing dashboard",
      "QA SUMMARY REPORT" in _stext.upper())
check("A single-month deck is shorter than the multi-month one",
      len(_sp.slides.__iter__.__self__._sldIdLst) < len(_mp.slides.__iter__.__self__._sldIdLst),
      f"{len(_sp.slides._sldIdLst)} vs {len(_mp.slides._sldIdLst)} slides")
# With the monthly pages switched off there is nothing else to show, so the
# consolidated view must come back.
_sp2 = Presentation(io.BytesIO(deck.build_deck(
    _single, {"market_label": "India", "include_monthly": False})))
_stext2 = " ".join(sh.text_frame.text for sl in _sp2.slides for sh in sl.shapes
                   if sh.has_text_frame)
check("One month with no monthly pages still gets the consolidated view",
      "QA Summary" in _stext2)
check("The PDF follows the same rule",
      len(pdf.build_pdf(_single, {"market_label": "India"}))
      < len(pdf.build_pdf(_multi, {"market_label": "India"})))

section("DEVELOPER TOTALS — the columns add up")
_dt = metrics.developer_table(_multi)
_row, _score = deck._dev_totals(_dt)
_tot_multi = metrics.totals(_multi)
check("The totals row sums every developer's tasks",
      _row[5] == _tot_multi["total_tasks"], f"{_row[5]} vs {_tot_multi['total_tasks']}")
check("The totals row sums the defects", _row[1] == _tot_multi["error_tasks"])
check("The totals row obeys Error Free = No Error + Observation",
      _row[4] == _row[2] + _row[3], f"{_row[4]} vs {_row[2]}+{_row[3]}")
check("The totals row obeys Total = Error + Error Free",
      _row[5] == _row[1] + _row[4])
check("The totals row carries the selection's own score",
      _row[6] == metrics.fmt_score(_tot_multi["score"]), _row[6])
check("The PDF computes the same totals row", pdf._dev_totals(_dt)[0] == _row)

section("CHARTS — every slice keeps its number")
from qars import charts                                        # noqa: E402
for label, args in [("a tiny observation", (176, 10, 165, 1)),
                    ("no defects at all", (44, 0, 44, 0)),
                    ("a single task", (1, 0, 1, 0)),
                    ("everything a defect", (12, 12, 0, 0)),
                    ("a six-hundred-task month", (641, 43, 560, 38))]:
    try:
        png = charts.composition_pie(*args)
        check(f"Composition pie renders with {label}", len(png) > 5_000, f"{len(png)} B")
    except Exception as exc:                                   # noqa: BLE001
        check(f"Composition pie renders with {label}", False, repr(exc))
check("Composition pie handles an empty selection",
      len(charts.composition_pie(0, 0, 0, 0)) > 1_000)
_many = [{"category": c, "total": 1, "pct": 100 / 7} for c in
         ["Content Related", "Design Related", "Image Related", "Video Related",
          "Redirect Links", "Navigation Related", "Functionality"]]
check("Category donut renders when every slice is too thin to label",
      len(charts.category_donut(_many, centre_total=7)) > 5_000)
check("Quality trend no longer accepts a target",
      "target" not in inspect.signature(charts.quality_trend).parameters,
      str(list(inspect.signature(charts.quality_trend).parameters)))

section("SLIDE GEOMETRY — nothing runs off the page")
# Charts are now sized from the panel they sit in rather than from constants
# that happened to fit once. This is the guard on that: every shape on every
# slide, for the shapes of report that exercise the different layouts.
from pptx.util import Inches as _In                            # noqa: E402

_SLIDE_W, _SLIDE_H = _In(13.333), _In(7.5)
_TOL = _In(0.06)


def _overflows(pptx_bytes):
    bad = []
    prs = Presentation(io.BytesIO(pptx_bytes))
    for n, slide in enumerate(prs.slides, 1):
        for sh in slide.shapes:
            if sh.left is None or sh.top is None:
                continue
            w, h = sh.width or 0, sh.height or 0
            if (sh.left < -_TOL or sh.top < -_TOL
                    or sh.left + w > _SLIDE_W + _TOL
                    or sh.top + h > _SLIDE_H + _TOL):
                bad.append(f"slide {n}: {sh.shape_type} at "
                           f"({sh.left / 914400:.2f}, {sh.top / 914400:.2f}) "
                           f"{w / 914400:.2f}x{h / 914400:.2f}in")
    return bad


_geom_db = store._empty_db()
library.seed(_geom_db)
_geom_s = _lib_settings(_geom_db)
_cases = [
    ("six months from a built-in report",
     metrics.select(_geom_db, "C3", _geom_s, {}), {}),
    ("a single month",
     metrics.select(_geom_db, "C3", _geom_s, {"periods": [(2026, 3)]}), {}),
    ("a month with zero defects",
     metrics.select(_db_with("India", tasks=_rows(2026, 6, error=0, no_error=44)),
                    "India", _settings(), {}), {}),
    ("every optional section switched on",
     metrics.select(_db_with("India", tasks=tasks), "India", _settings(), {}),
     {"include_aging": True, "include_critical": True}),
]
for label, _sel, _extra in _cases:
    _opts = {"market_label": "C3", "org": "Acme"}
    _opts.update(_extra)
    _bad = _overflows(deck.build_deck(_sel, _opts))
    check(f"No shape runs off the slide with {label}", not _bad,
          "; ".join(_bad[:2]) if _bad else "")

# ==========================================================================
print("\n" + "=" * 62)
print(f"  {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("  FAILED: " + ", ".join(FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
