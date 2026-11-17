#!/usr/bin/env python3
"""
Build everything the Omni agent needs, from the report library.

    python agent/build_pack.py

The agent is a language model configured with text and files; it cannot run
this app's code. So the app's knowledge is handed to it as files:

    agent/pack/
      1_agent_fields/      the text to paste into each Agent Builder section
      2_attachments/       the files to upload under Attachments
          QA_History.txt       every month already reported - the agent's memory
          Developer_Names.txt  how each developer is written, and open questions
          Rulebook.txt         the rules in full, with worked examples
          Report_Layout.txt    the report layout, with a complete worked example
      3_for_you_only/      NOT for the agent
          Test_Answers.txt     the right answers, to check the agent against
          QA_History.xlsx      the same history as a spreadsheet, for people
          sample_reports/      this app's own reports, in the white report theme
      SETUP_GUIDE.html     the step-by-step procedure, with the texts ready to copy
      SETUP_GUIDE.md       the same procedure as plain text
      Developer_Defect_Tracker_Agent_Pack.zip   all of the above

Every figure is produced by the same metrics functions as the app's own
reports, so the history the agent starts from is exact. Run it again whenever
the library gains a month, and replace the agent's attachments.

The pack holds developer names and scores, so it is not committed: agent/pack/
is in .gitignore.
"""

from __future__ import annotations

import os
import shutil
import sys
import warnings
import zipfile

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from qars import (deck, ingest, library, metrics, normalize as nz,  # noqa: E402
                  pdf, store)

PACK = os.path.join(HERE, "pack")
FS = metrics.fmt_score
RULE_LINE = ("Error Free = No Error + Observation  |  Total Tasks = Error + Error Free  |  "
             "Quality Score = Error Free / Total Tasks")


# ==========================================================================
# loading - exactly as the app builds a new session
# ==========================================================================
def load():
    db = store._empty_db()
    library.resync(db)
    names = set()
    for m in store.MARKETS:
        names |= {r["dev_raw"] for r in db["tasks"][m] if r.get("dev_raw")}
        names |= {d["raw"] for b in db["monthly"][m] for d in b.get("developers", [])
                  if d.get("raw")}
    settings = store._default_settings()
    merged, ambiguous = nz.auto_merge_map(names)
    # Decisions made by hand outrank anything worked out here - as in the app.
    for canon, spellings in library.aliases().items():
        merged[canon] = sorted(set(merged.pop(canon, [])) | set(spellings))
    settings["dev_aliases"] = merged
    return db, settings, sorted(names), ambiguous


def band(score):
    if score is None:
        return "No data"
    if score >= metrics.BAND_GOOD:
        return "On target"
    if score >= metrics.BAND_WATCH:
        return "Watch"
    return "Below benchmark"


def ym(period):
    return f"{period[0]:04d}-{period[1]:02d}"


def month_name(period):
    return f"{metrics.MONTH_FULL[period[1] - 1]} {period[0]}"


def period_text(label):
    """'Jul – Sep 2026' with a plain hyphen, so it survives any text box."""
    return label.replace("–", "-")


# ==========================================================================
# what reading each month's sheet had to leave out or assume
# ==========================================================================
def month_notes(market, period):
    """Plain sentences about one market-month's source, for 'Data notes'."""
    owner = library.ownership(market).get((market, period))
    if not owner:
        return [f"{month_name(period)}: figures taken from the report issued for that "
                "period, not from an audit sheet."]
    entry = next(e for e in library.entries() if e["id"] == owner)
    notes = library.reading_notes(entry)
    out = []
    for u in notes.get("uncounted") or []:
        title = f' "{u["title"]}"' if u.get("title") else ""
        out.append(f"{month_name(period)}: row {u['row']}{title} not counted - {u['why']}.")
    for raw, typo in (notes.get("typos") or {}).items():
        rows = ", ".join(str(n) for n in typo["rows"])
        out.append(f'{month_name(period)}: status "{raw}" in row {rows} read as '
                   f'{typo["as"]} (a typo).')
    if entry.get("force_month"):
        try:
            _e, data = library.file_bytes(entry["id"])
            rows, _rep = ingest.read_excel(data, market, filename=entry["source_name"])
            other = sorted({(r["year"], r["month"]) for r in rows} - {period})
            moved = sum(1 for r in rows if (r["year"], r["month"]) != period)
            if moved:
                was = ", ".join(month_name(p) for p in other)
                out.append(f"{month_name(period)}: {moved} row(s) dated {was} filed under "
                           f"{month_name(period)}, the month the sheet is for.")
        except Exception:                                     # noqa: BLE001
            pass
    return out


# ==========================================================================
# QA_History.txt - the agent's memory
# ==========================================================================
HISTORY_HEAD = """QA HISTORY - Developer Defect Tracker
Every month already reported, for each market. One fact per line.

HOW TO READ THIS FILE
  MONTH lines   one per market and month: that month's totals.
  DEV lines     one per developer in that market and month.
  CAT lines     one per defect category in that market and month, split by link type.

  Every line carries its market and its month (written YEAR-MONTH, so 2026-07 is July 2026).
  error_free = no_error + observation.   total = error + error_free.
  score = error_free / total x 100.
  test_link and live_link are the month's defects (Error rows) by where QA found them.
  source=sheet means the month was counted from its audit sheet.
  source=issued-report means the figures were taken from a report issued before this tool.
  critical is the number of that month's defects logged at Critical severity. It is only
  known for months counted from a sheet.

HOW TO USE IT
  One month:       read that month's lines.
  Several months:  add up error, no_error and observation over the months, then calculate.
                   Never add up or average the score column.
  A developer:     add up that developer's DEV lines over the months asked for.
  The developers' totals for a month add up to the month's total.

HOW IT GROWS
  When a new month is counted, its lines are added at the end of that market's section.
  A corrected sheet for a month already here replaces that month's lines.
"""


def history_text(db, s):
    out, problems = [HISTORY_HEAD], []
    for market in store.MARKETS:
        periods = sorted(metrics.available_periods(db, market))
        if not periods:
            continue
        out.append("=" * 70)
        out.append(f"{market.upper()}   {month_name(periods[0])} to {month_name(periods[-1])}"
                   f"   ({len(periods)} months)")
        out.append("=" * 70)
        for p in periods:
            out.append("")
            out.extend(month_lines(db, s, market, p, problems))
        out.append("")
    return "\n".join(out) + "\n", problems


def month_lines(db, s, market, p, problems=None):
    sel = metrics.select(db, market, s, {"periods": [p]})
    t = metrics.totals(sel)
    row = metrics.monthly_series(sel)[0]
    src = "sheet" if row["source"] == "detail" else "issued-report"
    lines = [f"MONTH | {market} | {ym(p)} | total={t['total_tasks']} | error={t['error_tasks']} "
             f"| no_error={t['no_error']} | observation={t['observations']} "
             f"| error_free={t['error_free']} | test_link={t['internal']} "
             f"| live_link={t['external']} | score={FS(t['score'])} | source={src}"
             + (f" | critical={t['critical']}" if src == "sheet" else "")]
    devs = metrics.developer_table(sel)
    for d in sorted(devs, key=lambda d: d["name"]):
        lines.append(f"DEV | {market} | {ym(p)} | {d['name']} | error={d['error']} "
                     f"| no_error={d['no_error']} | observation={d['observation']} "
                     f"| error_free={d['error_free']} | total={d['total']} "
                     f"| score={FS(d['score'])}")
    cats = metrics.category_table(sel)
    for c in cats:
        lines.append(f"CAT | {market} | {ym(p)} | {c['category']} | test_link={c['internal']} "
                     f"| live_link={c['external']} | total={c['total']}")
    if problems is not None:
        if sum(d["total"] for d in devs) != t["total_tasks"]:
            problems.append(f"{market} {ym(p)}: developers add to "
                            f"{sum(d['total'] for d in devs)}, month total {t['total_tasks']}")
        if cats and sum(c["total"] for c in cats) != t["error_tasks"]:
            problems.append(f"{market} {ym(p)}: categories add to "
                            f"{sum(c['total'] for c in cats)}, defects {t['error_tasks']}")
    return lines


# ==========================================================================
# Developer_Names.txt
# ==========================================================================
# Words that show a "developer" cell holds a label rather than a person.
_NOT_A_PERSON = {"all", "team", "market", "dev", "devs", "developers", "everyone",
                 "unknown", "tbd", "na"}


def names_text(db, s, raw_names, ambiguous):
    lookup = nz.build_alias_lookup(s["dev_aliases"])
    grouped, where = {}, {}
    for raw in raw_names:
        grouped.setdefault(nz.resolve_name(raw, lookup), []).append(raw)
    for m in store.MARKETS:
        seen = {r["dev_raw"] for r in db["tasks"][m] if r.get("dev_raw")}
        seen |= {d["raw"] for b in db["monthly"][m] for d in b.get("developers", [])
                 if d.get("raw")}
        for raw in seen:
            where.setdefault(nz.resolve_name(raw, lookup), set()).add(m)

    out = ["DEVELOPER NAMES - Developer Defect Tracker",
           "How each developer is written in every report, and the spellings that mean the",
           "same person. A name on a NAME line is settled: use it, and do not ask about it again.",
           "",
           "NAME lines   NAME | name to print | markets | other spellings seen in the sheets",
           "ASK lines    a question nobody has answered yet. Until it is answered, each spelling",
           "             in it stays its own person, exactly as the NAME lines have it.",
           "",
           "-" * 70, "SETTLED NAMES", "-" * 70]
    for canon in sorted(grouped):
        others = sorted({x for x in grouped[canon] if x != canon})
        markets = ", ".join(m for m in store.MARKETS if m in where.get(canon, ()))
        out.append(f"NAME | {canon} | {markets} | "
                   + ("; ".join(others) if others else "-"))

    decided = library.aliases()
    distinct = library.distinct_pairs()
    asks = []
    for _label, info in sorted(ambiguous.items()):
        here = nz.resolve_name(info["short"], lookup)
        rivals = {nz.resolve_name(r, lookup) for r in info["rivals"]}
        if here in rivals or nz.display_name(info["short"]) in decided:
            continue
        asks.append(f'ASK | "{nz.display_name(info["short"])}" could be '
                    + " or ".join(sorted(rivals)) + ". Which one - or is it someone else?")
    for a, b, score in nz.similar_people(grouped.keys()):
        if frozenset((a, b)) in distinct:
            continue
        asks.append(f'ASK | "{a}" and "{b}" look like one person ({int(score * 100)}% alike). '
                    "Same person, or two people?")
    for canon in sorted(grouped):
        if set(nz.name_key(canon).split()) & _NOT_A_PERSON:
            markets = ", ".join(m for m in store.MARKETS if m in where.get(canon, ()))
            asks.append(f'ASK | "{canon}" is written as a developer in a {markets} sheet but '
                        "does not look like one person's name. Whose tasks are these?")
    out += ["", "-" * 70, "OPEN QUESTIONS", "-" * 70]
    out += asks or ["(none - every name is settled)"]
    out += ["",
            "When a question is answered, the answer goes in this file: move the spellings onto",
            "one NAME line (same person) or leave two NAME lines and delete the ASK line (two people)."]
    return "\n".join(out) + "\n", asks


# ==========================================================================
# the report, as text - the layout the agent is asked to reproduce
# ==========================================================================
def table(headers, rows, bold_last=False):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" if i == 0 else ":---:" for i in range(len(headers))) + "|"]
    for n, row in enumerate(rows):
        cells = [str(c) for c in row]
        if bold_last and n == len(rows) - 1:
            cells = [f"**{c}**" for c in cells]
        out.append("| " + " | ".join(cells) + " |")
    return out


def dev_rows(devs):
    rows = [(d["name"], d["error"], d["no_error"], d["observation"], d["error_free"],
             d["total"], FS(d["score"])) for d in devs]
    total, _score = deck._dev_totals(devs)
    return rows + [total]


DEV_HEAD = ["Developer Name", "Error", "No Error", "Observation", "Error Free",
            "Total Tasks", "Quality Score"]


def month_section(sel, r, n=None):
    period = (r["year"], r["month"])
    label = month_name(period)
    out = [f"## {n}. {label}" if n else f"## {label}", "",
           "### Quality Score", ""]
    out += table(["Measure", "Value"],
                 [("Error", f"{r['error']:,}"), ("No Error", f"{r['no_error']:,}"),
                  ("Observation", f"{r['observation']:,}"),
                  ("Error-Free Tasks", f"{r['error_free']:,}"),
                  ("Total Tasks", f"{r['total']:,}"),
                  ("Quality Score", f"{FS(r['score'])} ({band(r['score'])})")])
    devs = metrics.developer_table(sel, month=period)
    out += ["", "### Developer Report", ""]
    out += table(DEV_HEAD, dev_rows(devs), bold_last=True) if devs else \
        ["No developer detail is held for this month."]
    out += ["", RULE_LINE]
    cats = metrics.category_table(sel, month=period)
    out += ["", "### Defect Analysis", ""]
    if cats:
        ti = sum(c["internal"] for c in cats)
        te = sum(c["external"] for c in cats)
        out += table(["Error Type", "Test Link", "Live Link", "Total", "% of Total"],
                     [(c["category"], c["internal"], c["external"], c["total"],
                       f"{c['pct']:.2f}%") for c in cats]
                     + [("Total", ti, te, ti + te, "100.00%")], bold_last=True)
        out += ["", f"{ti} defect(s) on test links, found before the page went live. "
                    f"{te} on live links, found by QA after the page went live."]
    else:
        out += ["Zero defects this month."]
    return out + [""]


def report_text(db, s, market, periods):
    sel = metrics.select(db, market, s, {"periods": periods})
    tot = metrics.totals(sel)
    rows = metrics.monthly_series(sel)
    period = period_text(tot["period_label"])
    out = [f"# {market} - Quality Assurance Report",
           f"Period: {period}   |   {tot['months']} month(s)", ""]
    out += table(["Tasks Audited", "Quality Score", "Total Defects", "Developers"],
                 [(f"{tot['total_tasks']:,}", f"{FS(tot['score'])} ({band(tot['score'])})",
                   f"{tot['error_tasks']:,}", tot["developers"])])
    out.append("")

    for i, r in enumerate(rows, 1):
        out += month_section(sel, r, i if len(rows) > 1 else None)

    if len(rows) > 1:
        out += [f"## Consolidated Summary - {period}", "", "### QA Summary", ""]
        out += table(["KPI", "Value"], [
            ("Total Tasks Audited", f"{tot['total_tasks']:,}"),
            ("Error Tasks (defects)", f"{tot['error_tasks']:,}"),
            ("No Error Tasks", f"{tot['no_error']:,}"),
            ("Observations", f"{tot['observations']:,}"),
            ("Error-Free Tasks", f"{tot['error_free']:,}"),
            ("Defects on Test Links", f"{tot['internal']} ({tot['internal_pct']:.2f}%)"),
            ("Defects on Live Links", f"{tot['external']} ({tot['external_pct']:.2f}%)"),
            ("Developers Audited", tot["developers"]),
            ("Developers Below 90%", tot["below_target"]),
            ("Months Covered", tot["months"]),
            ("Overall Quality Score", FS(tot["score"])),
            ("Average Monthly Score", FS(tot["avg_monthly_score"]))])
        out.append("")
        out += table(["Month", "Tasks", "Defects", "Error Free", "Score"],
                     [(r["label"], r["total"], r["error"], r["error_free"], FS(r["score"]))
                      for r in rows]
                     + [("Total", tot["total_tasks"], tot["error_tasks"], tot["error_free"],
                         FS(tot["score"]))], bold_last=True)
        devs = metrics.developer_table(sel)
        out += ["", "### Developer Summary", ""]
        out += table(DEV_HEAD, dev_rows(devs), bold_last=True)
        out += ["", RULE_LINE]
        cats = metrics.category_table(sel)
        out += ["", "### Defect Category Breakdown", ""]
        if cats:
            ti = sum(c["internal"] for c in cats)
            te = sum(c["external"] for c in cats)
            out += table(["Defect Category", "Test Link", "Live Link", "Total Defects",
                          "% of Total"],
                         [(c["category"], c["internal"], c["external"], c["total"],
                           f"{c['pct']:.2f}%") for c in cats]
                         + [("Total", ti, te, ti + te, "100.00%")], bold_last=True)
        else:
            out += ["Zero defects across this period."]
        out += ["", "### Key QA Recommendations", ""]
        for n, rec in enumerate(metrics.recommendations(sel), 1):
            out.append(f"{n}. **{rec['title']}** - {rec['text']}")
        out.append("")

    out += [f"## Dashboard - {period}", ""]
    out += table(["Total Tasks Audited", "Error Free Tasks", "Observations (in error free)",
                  "Total Defects", "Test Link Defects", "Live Link Defects",
                  "Developers Audited", "Overall Quality Score"],
                 [(f"{tot['total_tasks']:,}", f"{tot['error_free']:,}",
                   f"{tot['observations']:,}", f"{tot['error_tasks']:,}",
                   f"{tot['internal']} ({tot['internal_pct']:.2f}%)",
                   f"{tot['external']} ({tot['external_pct']:.2f}%)",
                   tot["developers"], FS(tot["score"]))])
    scored = [r for r in rows if r["score"] is not None]
    if scored:
        best = max(scored, key=lambda r: r["score"])
        worst = min(scored, key=lambda r: r["score"])
        out.append("")
        out += table(["Highest month", "Lowest month", "Overall", "Average monthly"],
                     [(f"{best['label']} {FS(best['score'])}",
                       f"{worst['label']} {FS(worst['score'])}",
                       FS(tot["score"]), FS(tot["avg_monthly_score"]))])
    top, bar = metrics.top_developers(sel, n=3)
    if top:
        out += ["", f"**Top performers** (ranked on score, minimum {bar} audited tasks to "
                    "qualify)", ""]
        out += table(["Rank", "Developer", "Tasks", "Error Free", "Quality Score"],
                     [(i, d["name"], d["total"], d["error_free"], FS(d["score"]))
                      for i, d in enumerate(top, 1)])
    ins = metrics.insights(sel)
    if ins:
        out += ["", "**Key insights**", ""]
        out += [f"- {i['value']} {i['text']}" for i in ins]

    out += ["", "## Data notes", ""]
    notes = []
    for r in rows:
        notes += month_notes(market, (r["year"], r["month"]))
    out += [f"- {n}" for n in notes] or ["- Every row of every sheet was counted; "
                                          "nothing was left out or assumed."]
    return "\n".join(out) + "\n"


def import_check_text(db, s, market, period):
    """The reply to one uploaded sheet: the check, the month, the history lines."""
    owner = library.ownership(market).get((market, period))
    entry = next(e for e in library.entries() if e["id"] == owner)
    notes = library.reading_notes(entry)
    sel = metrics.select(db, market, s, {"periods": [period]})
    r = metrics.monthly_series(sel)[0]
    unc = notes.get("uncounted") or []
    out = [f"# Import check - {entry['source_name']}", "",
           f"- Market: {market} (from the file name)",
           f"- Month: {month_name(period)} (from the dates in the sheet)",
           f"- Tasks counted: {r['total']}",
           f"- Reconciliation: Error {r['error']} + No Error {r['no_error']} + Observation "
           f"{r['observation']} = {r['total']}"]
    out.append("- Not counted: " + ("none" if not unc else ""))
    for u in unc:
        title = f' "{u["title"]}"' if u.get("title") else ""
        out.append(f"    - row {u['row']}{title} - {u['why']}")
    typos = notes.get("typos") or {}
    out.append("- Typos corrected: " + ("none" if not typos else "; ".join(
        f'"{raw}" in row {", ".join(str(n) for n in t["rows"])} read as {t["as"]}'
        for raw, t in typos.items())))
    moved = [n for n in month_notes(market, period) if "filed under" in n]
    out.append("- Dates moved: " + ("none" if not moved else moved[0].split(": ", 1)[1]))
    out.append("- Names to confirm: none")
    out.append("")
    out += month_section(sel, r)
    out += ["## History update", "",
            f"Add these lines to the end of the {market.upper()} section of QA_History.txt, "
            "then upload the file again under the agent's Attachments:", "", "```"]
    out += month_lines(db, s, market, period)
    out += ["```", "",
            f"Would you like the full {market} report for the period to date?"]
    return "\n".join(out) + "\n"


LAYOUT_HEAD = """REPORT LAYOUT - Developer Defect Tracker
The exact layout of every report, shown with complete worked examples built from real
months. Reproduce the sections, their order, the column headings and the number formats
exactly. Only the figures change.

RULES OF THE LAYOUT
  - Two or more months: title block, each month's three tables in order, the Consolidated
    Summary, the Dashboard, Data notes.               -> EXAMPLE 1
  - One month: title block, that month's three tables, the Dashboard, Data notes.
    No Consolidated Summary - with one month it would repeat the month.   -> EXAMPLE 2
  - The reply to an uploaded sheet: the import check, the month's three tables, the
    History update lines.                             -> EXAMPLE 3
  - Developers are listed lowest score first. Categories are listed largest first.
  - Every table of developers or categories ends with a bold Total row.
  - Scores have two decimals. A month with no tasks shows N/A.

"""


def layout_text(db, s):
    market = "India" if metrics.available_periods(db, "India") else store.MARKETS[0]
    periods = sorted(metrics.available_periods(db, market))[-3:]
    out = [LAYOUT_HEAD,
           "=" * 78, f"EXAMPLE 1 - a report for several months ({market}, "
           f"{month_name(periods[0])} to {month_name(periods[-1])})", "=" * 78, "",
           report_text(db, s, market, periods),
           "=" * 78, f"EXAMPLE 2 - a report for one month ({market}, "
           f"{month_name(periods[-1])})", "=" * 78, "",
           report_text(db, s, market, periods[-1:]),
           "=" * 78, f"EXAMPLE 3 - the reply to an uploaded sheet ({market}, "
           f"{month_name(periods[-1])})", "=" * 78, "",
           import_check_text(db, s, market, periods[-1])]
    return "\n".join(out)


# ==========================================================================
# Test_Answers.txt - for the person, never for the agent
# ==========================================================================
def answers_text(db, s):
    out = ["TEST ANSWERS - keep this file to yourself. Do NOT upload it to the agent.",
           "",
           "These are the right answers, worked out by the reporting tool from the same sheets.",
           "Give the agent the test, then compare its reply with what is written here.",
           "A count that differs by even one task means the agent did not read every row.",
           ""]
    n = 0
    sheet_tests = []
    owner = library.ownership()
    for e in library.entries():
        if e["kind"] != "workbook":
            continue
        for p in library.months_supplied(e["id"], owner):
            sheet_tests.append((e, p))
    out += ["=" * 78,
            "PART 1 - COUNTING A SHEET  (do this BEFORE you upload QA_History.txt, or the",
            "         agent can simply read the answer from it instead of counting)",
            "=" * 78, "",
            'For each sheet: attach it in the chat and type  "Count this sheet."', ""]
    for e, p in sheet_tests:
        n += 1
        market = e["market"]
        sel = metrics.select(db, market, s, {"periods": [p]})
        r = metrics.monthly_series(sel)[0]
        t = metrics.totals(sel)
        out += ["-" * 78, f"TEST {n}   attach: {e['source_name']}", "-" * 78,
                f"  Market {market}, month {month_name(p)}",
                f"  Tasks counted {r['total']}   =   Error {r['error']} + No Error "
                f"{r['no_error']} + Observation {r['observation']}",
                f"  Error Free {r['error_free']}     Quality Score {FS(r['score'])}",
                f"  Defects: {t['internal']} on test links, {t['external']} on live links"]
        special = month_notes(market, p)
        out += ["  The agent must also report:"] + [f"    - {x.split(': ', 1)[1]}"
                                                   for x in special] if special else \
            ["  Nothing unusual in this sheet: no row left out, no typo, no date moved."]
        out += ["", "  Developer table it should show:", ""]
        out += ["  " + ln for ln in table(DEV_HEAD, dev_rows(
            metrics.developer_table(sel, month=p)), bold_last=True)]
        out.append("")

    out += ["=" * 78,
            "PART 2 - REPORTING FROM THE HISTORY  (do this AFTER you upload the four attachments)",
            "=" * 78, ""]
    for market in store.MARKETS:
        periods = sorted(metrics.available_periods(db, market))
        if not periods:
            continue
        n += 1
        sel = metrics.select(db, market, s, {})
        tot = metrics.totals(sel)
        rows = metrics.monthly_series(sel)
        out += ["-" * 78,
                f'TEST {n}   type: "Give me the {market} report for {month_name(periods[0])} '
                f'to {month_name(periods[-1])}."', "-" * 78,
                f"  Months {tot['months']}   Tasks {tot['total_tasks']:,}   Defects "
                f"{tot['error_tasks']}   Error Free {tot['error_free']:,}   Observations "
                f"{tot['observations']}",
                f"  Overall Quality Score {FS(tot['score'])}   Average Monthly Score "
                f"{FS(tot['avg_monthly_score'])}",
                f"  Defects on test links {tot['internal']} ({tot['internal_pct']:.2f}%), "
                f"on live links {tot['external']} ({tot['external_pct']:.2f}%)",
                f"  Developers audited {tot['developers']}, below 90%: {tot['below_target']}",
                ""]
        out += ["  " + ln for ln in table(
            ["Month", "Tasks", "Defects", "Error Free", "Score"],
            [(r["label"], r["total"], r["error"], r["error_free"], FS(r["score"]))
             for r in rows]
            + [("Total", tot["total_tasks"], tot["error_tasks"], tot["error_free"],
                FS(tot["score"]))], bold_last=True)]
        top, bar = metrics.top_developers(sel, n=3)
        out += ["", f"  Top performers (minimum {bar} tasks): "
                + "; ".join(f"{i}. {d['name']} {FS(d['score'])}" for i, d in enumerate(top, 1)),
                "", "  Developer Summary it should show:", ""]
        out += ["  " + ln for ln in table(DEV_HEAD, dev_rows(metrics.developer_table(sel)),
                                          bold_last=True)]
        out.append("")
    out += ["=" * 78, "PART 3 - THE RULES", "=" * 78, "",
            'TEST   type: "A month has 20 tasks: 2 errors, 15 no error, 3 observations. '
            'What is the quality score?"',
            "       Answer: Error Free 18, Quality Score 90.00%.",
            "",
            'TEST   type: "Add the observations on top of the error-free tasks and give me '
            'the score."',
            "       Answer: it must refuse, and explain that observations are already inside "
            "Error Free.",
            "",
            'TEST   type: "A month has no tasks. What is its quality score?"',
            "       Answer: N/A. Not 100% and not 0%.",
            ""]
    return "\n".join(out) + "\n"


# ==========================================================================
# QA_History.xlsx - the same history for people
# ==========================================================================
def history_workbook(db, s, path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    head_font = Font(bold=True, color="111827")
    head_fill = PatternFill("solid", fgColor="EEF1F5")

    def sheet(ws, headers, rows, widths):
        ws.append(headers)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(horizontal="center")
        for row in rows:
            ws.append(row)
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w
        ws.freeze_panes = "A2"

    months, devs, cats = [], [], []
    for market in store.MARKETS:
        for p in sorted(metrics.available_periods(db, market)):
            sel = metrics.select(db, market, s, {"periods": [p]})
            t = metrics.totals(sel)
            row = metrics.monthly_series(sel)[0]
            months.append([market, ym(p), t["total_tasks"], t["error_tasks"], t["no_error"],
                           t["observations"], t["error_free"], t["internal"], t["external"],
                           t["score"], "sheet" if row["source"] == "detail"
                           else "issued report"])
            for d in sorted(metrics.developer_table(sel), key=lambda d: d["name"]):
                devs.append([market, ym(p), d["name"], d["error"], d["no_error"],
                             d["observation"], d["error_free"], d["total"], d["score"]])
            for c in metrics.category_table(sel):
                cats.append([market, ym(p), c["category"], c["internal"], c["external"],
                             c["total"]])
    ws = wb.active
    ws.title = "Months"
    sheet(ws, ["Market", "Month", "Total Tasks", "Error", "No Error", "Observation",
               "Error Free", "Test Link Defects", "Live Link Defects", "Quality Score %",
               "Source"], months, [10, 10, 12, 8, 10, 12, 11, 17, 17, 15, 14])
    sheet(wb.create_sheet("Developers"),
          ["Market", "Month", "Developer", "Error", "No Error", "Observation", "Error Free",
           "Total Tasks", "Quality Score %"], devs, [10, 10, 32, 8, 10, 12, 11, 12, 15])
    sheet(wb.create_sheet("Categories"),
          ["Market", "Month", "Defect Category", "Test Link", "Live Link", "Total"],
          cats, [10, 10, 26, 10, 10, 8])
    wb.save(path)


# ==========================================================================
# ==========================================================================
# SETUP_GUIDE.html - the procedure as one page, with the texts ready to copy
# ==========================================================================
import html as _html                                          # noqa: E402
import re                                                     # noqa: E402

GUIDE_CSS = """
:root{--ink:#111827;--text:#1F2937;--muted:#6B7280;--line:#D5DAE3;--fill:#EEF1F5;
      --soft:#F7F9FB;--accent:#1F3A5F;}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--text);
     font:16px/1.6 "Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif}
main{max-width:880px;margin:0 auto;padding:40px 24px 80px}
h1{font-size:30px;line-height:1.2;color:var(--ink);margin:0 0 8px}
h2{font-size:21px;color:var(--ink);margin:44px 0 10px;padding-top:18px;
   border-top:1px solid var(--line)}
h2::before{content:"";display:block;width:64px;height:3px;background:var(--accent);
           margin:-20px 0 16px}
h3{font-size:17px;color:var(--ink);margin:26px 0 6px}
p{margin:10px 0} a{color:var(--accent)}
code{font:13.5px/1.5 Consolas,"SF Mono",Menlo,monospace;background:var(--fill);
     padding:1px 5px;border-radius:4px}
pre{background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:14px 16px;
    overflow-x:auto;font:13px/1.55 Consolas,"SF Mono",Menlo,monospace}
pre code{background:none;padding:0}
.tablewrap{overflow-x:auto;margin:14px 0}
table{border-collapse:collapse;width:100%;font-size:14.5px}
th{background:var(--fill);color:var(--ink);text-align:left;padding:9px 11px;
   border-bottom:1px solid var(--line)}
td{padding:9px 11px;border-bottom:1px solid var(--line);vertical-align:top}
ul,ol{padding-left:24px} li{margin:6px 0}
hr{display:none}
.field{border:1px solid var(--line);border-radius:10px;margin:14px 0;overflow:hidden}
.field header{display:flex;gap:12px;align-items:center;justify-content:space-between;
              padding:11px 14px;background:var(--fill)}
.field header b{color:var(--ink)} .field header span{color:var(--muted);font-size:13.5px}
.field textarea{display:block;width:100%;height:190px;border:0;border-top:1px solid var(--line);
                padding:12px 14px;resize:vertical;color:var(--text);background:#fff;
                font:12.5px/1.5 Consolas,"SF Mono",Menlo,monospace}
button{font:600 14px/1 inherit;color:#fff;background:var(--accent);border:0;border-radius:7px;
       padding:9px 14px;cursor:pointer;white-space:nowrap}
button:focus-visible,textarea:focus-visible{outline:3px solid #9DB4D3;outline-offset:2px}
button.done{background:#1E7F4F}
@media print{button{display:none}.field textarea{height:auto}}
"""

GUIDE_JS = """
function copyField(id, btn){
  var t = document.getElementById(id);
  function ok(){ var was = btn.textContent; btn.textContent = 'Copied'; btn.className = 'done';
                 setTimeout(function(){ btn.textContent = was; btn.className = ''; }, 1600); }
  function old(){ t.focus(); t.select(); try { document.execCommand('copy'); ok(); } catch(e) {} }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(t.value).then(ok, old);
  } else { old(); }
}
"""


def _inline(text):
    text = _html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)


def md_to_html(md):
    """The small part of Markdown this guide uses - no dependency needed."""
    lines, out, i = md.split("\n"), [], 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            body = _html.escape("\n".join(lines[i + 1:j]), quote=False)
            out.append(f"<pre><code>{body}</code></pre>")
            i = j + 1
        elif re.match(r"#{1,3} ", ln):
            n = len(ln) - len(ln.lstrip("#"))
            out.append(f"<h{n}>{_inline(ln[n + 1:])}</h{n}>")
            i += 1
        elif ln.strip() == "---":
            i += 1
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], rows[2:]
            out.append('<div class="tablewrap"><table><tr>'
                       + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r)
                                 + "</tr>" for r in body) + "</table></div>")
        elif re.match(r"(\d+\.|-) ", ln):
            tag = "ol" if ln[0].isdigit() else "ul"
            items = []
            while i < len(lines) and (re.match(r"(\d+\.|-) ", lines[i])
                                      or (lines[i].startswith("  ") and items)):
                if re.match(r"(\d+\.|-) ", lines[i]):
                    items.append(lines[i].split(" ", 1)[1])
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(x)}</li>" for x in items)
                       + f"</{tag}>")
        elif ln.strip().startswith("<!--"):
            out.append(ln.strip())
            i += 1
        elif not ln.strip():
            i += 1
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(
                    r"(#{1,3} |\||```|(\d+\.|-) |---$|<!--)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


FIELDS = [("Description", "1_description.txt", "Step 1 - paste into the Description box"),
          ("Instructions", "2_instructions.txt", "Step 2 - paste all of it"),
          ("Expected Output", "3_expected_output.txt", "Step 3 - paste all of it"),
          ("Goals", "4_goals.txt", "Step 4 - paste all of it"),
          ("Tools", "5_tools.txt", "Step 6 - what to tick; nothing to paste")]


def guide_html(md):
    boxes = ['<h3>The text for each section</h3>',
             "<p>Press Copy, then paste into the matching section of Agent Builder.</p>"]
    for n, (label, name, hint) in enumerate(FIELDS, 1):
        with open(os.path.join(HERE, name), encoding="utf-8") as fh:
            text = fh.read()
        if name == "1_description.txt":           # only the paragraph is pasted
            text = text.split("DESCRIPTION\n", 1)[1].strip()
        boxes.append(
            f'<div class="field"><header><div><b>{label}</b> <span>{hint}</span></div>'
            f'<button type="button" onclick="copyField(\'f{n}\', this)">Copy</button></header>'
            f'<textarea id="f{n}" readonly aria-label="{label} text">'
            f'{_html.escape(text, quote=False)}</textarea></div>')
    body = md_to_html(md).replace("<!-- FIELD_BOXES -->", "\n".join(boxes))
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            "<title>Agent Setup Guide</title>"
            f"<style>{GUIDE_CSS}</style></head><body><main>\n{body}\n</main>"
            f"<script>{GUIDE_JS}</script></body></html>\n")


_PLAIN = {"\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"',
          "\u201d": '"', "\u2022": "|", "\u00f7": "/", "\u2026": "...", "\u00a0": " "}


def plain(text):
    """Typographic characters swapped for plain ones: an agent's attachment has
    to survive whatever converts it, and a lost dash changes 'Jul - Sep'."""
    for a, b in _PLAIN.items():
        text = text.replace(a, b)
    return text


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(plain(text))


def main():
    samples = "--no-samples" not in sys.argv
    db, s, raw_names, ambiguous = load()

    shutil.rmtree(PACK, ignore_errors=True)
    fields = os.path.join(PACK, "1_agent_fields")
    attach = os.path.join(PACK, "2_attachments")
    mine = os.path.join(PACK, "3_for_you_only")
    for d in (fields, attach, mine):
        os.makedirs(d)

    for name in ("1_description.txt", "2_instructions.txt", "3_expected_output.txt",
                 "4_goals.txt", "5_tools.txt"):
        shutil.copy2(os.path.join(HERE, name), os.path.join(fields, name))
    shutil.copy2(os.path.join(HERE, "Rulebook.txt"), os.path.join(attach, "Rulebook.txt"))
    with open(os.path.join(HERE, "README.md"), encoding="utf-8") as fh:
        guide = fh.read()
    write(os.path.join(PACK, "SETUP_GUIDE.md"), guide)
    with open(os.path.join(PACK, "SETUP_GUIDE.html"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(guide_html(guide))

    history, problems = history_text(db, s)
    write(os.path.join(attach, "QA_History.txt"), history)
    names, asks = names_text(db, s, raw_names, ambiguous)
    write(os.path.join(attach, "Developer_Names.txt"), names)
    write(os.path.join(attach, "Report_Layout.txt"), layout_text(db, s))
    write(os.path.join(mine, "Test_Answers.txt"), answers_text(db, s))
    history_workbook(db, s, os.path.join(mine, "QA_History.xlsx"))

    if samples:
        out = os.path.join(mine, "sample_reports")
        os.makedirs(out)
        for market in store.MARKETS:
            if not metrics.available_periods(db, market):
                continue
            sel = metrics.select(db, market, s, {})
            label = period_text(metrics.totals(sel)["period_label"]).replace(" - ", "-")
            opts = {"market_label": market}
            base = os.path.join(out, f"{market} QA Report {label}")
            with open(base + ".pptx", "wb") as fh:
                fh.write(deck.build_deck(sel, opts))
            with open(base + ".pdf", "wb") as fh:
                fh.write(pdf.build_pdf(sel, opts))

    zpath = os.path.join(PACK, "Developer_Defect_Tracker_Agent_Pack.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(PACK):
            for name in sorted(files):
                full = os.path.join(root, name)
                if full != zpath:
                    z.write(full, os.path.relpath(full, PACK))

    print(f"Agent pack written to {PACK}")
    for market in store.MARKETS:
        per = sorted(metrics.available_periods(db, market))
        if per:
            t = metrics.totals(metrics.select(db, market, s, {}))
            print(f"  {market:<6} {month_name(per[0])} to {month_name(per[-1])}: "
                  f"{t['total_tasks']:,} tasks, {FS(t['score'])}")
    print(f"  {len(asks)} name question(s) still open - see Developer_Names.txt")
    for p in problems:
        print(f"  CHECK: {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
