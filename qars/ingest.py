"""
Readers that turn the two kinds of input into stored records.

  Excel / CSV audit sheet  ->  task-level rows   (full detail, every filter works)
  Legacy PPT deck          ->  month-level blocks (totals only, for months already
                                                   reported before this tool existed)

Both readers are defensive: real sheets have blank spacer rows, headers that are
not on row 1, stray dates from the wrong year, and columns that appear in some
months but not others.

OBSERVATION CONVENTION
----------------------
Task rows are counted under the canonical rule (No Error and Observation are
disjoint; Error-Free = No Error + Observation).

Legacy decks used the OPPOSITE convention: observations were an overlay counted
*inside* the No Error figure, so a developer row read `0 error, 19 no-error,
3 observation, Grand Total 19`. Importing that as-is would inflate both the task
count and the score. `_normalise_observations` detects which convention a deck
used and converts it, so imported months keep exactly the totals they were
published with.
"""

from __future__ import annotations

import csv
import io
import os
import re
from datetime import date, datetime, timedelta

from . import normalize as nz

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_FULL = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]

_COLS = {
    "title": ["mail title", "task", "task name", "subject", "title", "mailer", "campaign"],
    "country": ["country", "market", "region"],
    "date": ["date", "audit date", "qa date", "review date"],
    "env": ["test environment", "environment", "env", "link type", "test env"],
    "dev": ["developer name", "developer", "dev name", "resource", "developer  name"],
    "qa": ["qa person in-charge", "qa person", "qa name", "audited by", "qa in-charge", "qa"],
    "status": ["status", "result", "qa status", "outcome"],
    "brand": ["brand"],
    "etype": ["error type", "defect type", "issue type", "error category", "defect category"],
    "sev": ["error severity", "severity", "priority"],
    "hours": ["hours", "hrs", "time spent", "effort"],
    "details": ["details", "description", "remarks", "issue", "observation details"],
    "comments": ["comments", "comment", "notes"],
}


class IngestError(Exception):
    """Raised with a message that is safe and useful to show a business user."""


# ==========================================================================
# reading a grid out of whatever was uploaded
# ==========================================================================
def _read_grid(data, filename):
    """
    Return (grid, sheet_name) for .xlsx / .xlsm / .xls / .csv / .tsv.

    Chooses the sheet that most looks like an audit log when a workbook has
    several.
    """
    ext = os.path.splitext(filename or "")[1].lower()

    if ext in (".csv", ".tsv", ".txt"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return [list(r) for r in csv.reader(io.StringIO(text), dialect)], os.path.basename(filename)

    if ext == ".xls":
        try:
            import xlrd
        except ImportError as exc:
            raise IngestError(
                "This is an old-format .xls file, which needs the `xlrd` package. "
                "Either run `pip install xlrd`, or open the file in Excel and save "
                "it as .xlsx — that works with no extra install."
            ) from exc
        try:
            book = xlrd.open_workbook(file_contents=data)
        except Exception as exc:                              # noqa: BLE001
            raise IngestError(f"The .xls file could not be opened: {exc}") from exc
        best, best_score = None, -1
        for sh in book.sheets():
            head = " ".join(str(sh.cell_value(r, c)).lower()
                            for r in range(min(sh.nrows, 12))
                            for c in range(sh.ncols))
            score = sum(3 for k in ("developer", "status") if k in head)
            if score > best_score:
                best, best_score = sh, score
        if best is None:
            raise IngestError("The workbook has no readable sheets.")
        grid = [[best.cell_value(r, c) for c in range(best.ncols)] for r in range(best.nrows)]
        return grid, best.name

    if ext in (".xlsx", ".xlsm", ""):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        except Exception as exc:                              # noqa: BLE001
            raise IngestError(
                "This file could not be opened as an Excel workbook. It may be "
                "corrupted, password protected, or actually a different format "
                f"with an .xlsx name. ({type(exc).__name__})"
            ) from exc
        best, best_score = None, -1
        for ws in wb.worksheets:
            try:
                head = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    head.append(row)
                    if i >= 12:
                        break
            except Exception:                                 # noqa: BLE001
                continue
            flat = " ".join(str(c).lower() for r in head for c in r if c is not None)
            score = sum(3 for k in ("developer", "status") if k in flat)
            score += sum(1 for k in ("error", "date", "brand", "severity") if k in flat)
            if score > best_score:
                best, best_score = ws, score
        if best is None:
            raise IngestError("The workbook has no readable sheets.")
        return [list(r) for r in best.iter_rows(values_only=True)], best.title

    raise IngestError(
        f"'{ext or 'this file'}' is not a supported format. "
        "Upload .xlsx, .xlsm, .xls or .csv."
    )


# ==========================================================================
# month detection
# ==========================================================================
_MONTH_TOKEN = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*[-_'’ ]?\s*(\d{2,4})?", re.I)


def detect_month(filename, sheet_name, date_votes):
    """
    Work out the reporting month from three independent signals and report any
    disagreement instead of silently picking one.

    Returns {"month": (y,m) or None, "sources": {...}, "conflict": bool}
    """
    signals = {}
    for label, text in (("Filename", filename or ""), ("Sheet name", sheet_name or "")):
        got = _month_from_text(text)
        if got:
            signals[label] = got
    if date_votes:
        signals["Date data"] = max(date_votes, key=date_votes.get)

    chosen = signals.get("Date data") or signals.get("Filename") or signals.get("Sheet name")
    conflict = len({v for v in signals.values()}) > 1
    return {"month": chosen, "sources": signals, "conflict": conflict}


def _month_from_text(text):
    if not text:
        return None
    t = str(text)
    m = _MONTH_TOKEN.search(t)
    year = None
    ym = re.search(r"\b(20\d{2})\b", t)
    if ym:
        year = int(ym.group(1))
    if m:
        mon = MONTH_ABBR.index(m.group(1).title()) + 1
        if m.group(2):
            y = int(m.group(2))
            year = y + 2000 if y < 100 else y
        if year:
            return (year, mon)
        return None
    # numeric forms: 2026-03, 03-2026, 2026_03
    m2 = re.search(r"\b(20\d{2})[-_/.](0?[1-9]|1[0-2])\b", t)
    if m2:
        return (int(m2.group(1)), int(m2.group(2)))
    m3 = re.search(r"\b(0?[1-9]|1[0-2])[-_/.](20\d{2})\b", t)
    if m3:
        return (int(m3.group(2)), int(m3.group(1)))
    return None


def month_label(ym):
    return f"{MONTH_FULL[ym[1] - 1]} {ym[0]}" if ym else "unknown"


# ==========================================================================
# EXCEL / CSV
# ==========================================================================
def read_excel(file_like, market, filename=None, force_month=None):
    """
    Parse an audit workbook into task rows.

    `force_month` = (year, month) overrides the detected period for every
    undated row and is recorded on each row, so the user can correct a
    misdetected month without editing the sheet.

    Returns (rows, report).
    """
    data = file_like.read() if hasattr(file_like, "read") else file_like
    filename = filename or getattr(file_like, "name", "uploaded file")
    if not data:
        raise IngestError("That file is empty — there is nothing to import.")

    grid, sheet = _read_grid(data, filename)
    if not grid:
        raise IngestError(f"Sheet '{sheet}' has no rows.")

    hdr_idx, colmap = _find_header(grid)
    if hdr_idx is None:
        raise IngestError(
            "No header row could be found. The sheet needs a row containing at least "
            "a developer column and a status column — for example 'Developer Name' "
            "and 'Status'. Check you have uploaded the raw audit log rather than a "
            "pivot or summary view."
        )
    if "status" not in colmap:
        raise IngestError("No 'Status' column was found. That column decides pass or "
                          "fail, so it is required.")
    if "dev" not in colmap:
        raise IngestError("No 'Developer Name' column was found.")

    rows, skipped_blank, skipped_bad, undated = [], 0, 0, 0
    year_votes, month_votes = {}, {}
    bad_examples = []

    for n, raw in enumerate(grid[hdr_idx + 1:], start=hdr_idx + 2):
        if not any(v is not None and str(v).strip() != "" for v in raw):
            skipped_blank += 1
            continue
        get = lambda k: _cell(raw, colmap.get(k))            # noqa: E731

        status = nz.norm_status(get("status"))
        dev_raw = get("dev")
        if status is None or not str(dev_raw or "").strip():
            skipped_bad += 1
            if len(bad_examples) < 3:
                bad_examples.append(f"row {n}")
            continue

        dt = _parse_date(get("date"))
        if dt is None:
            undated += 1
        else:
            year_votes[dt.year] = year_votes.get(dt.year, 0) + 1
            month_votes[(dt.year, dt.month)] = month_votes.get((dt.year, dt.month), 0) + 1

        rows.append({
            "_dt": dt,
            "title": _s(get("title")),
            "country": _s(get("country")),
            "env": nz.norm_env(get("env")),
            "dev_raw": _s(dev_raw),
            "qa_raw": _s(get("qa")),
            "status": status,
            "brand": _s(get("brand")),
            "category": nz.norm_category(get("etype")),
            "severity": nz.norm_severity(get("sev")) if status == nz.STATUS_ERR else None,
            "hours": _num(get("hours")),
            "details": _s(get("details"))[:400],
        })

    if not rows:
        raise IngestError(
            f"A header was found on row {hdr_idx + 1} of sheet '{sheet}', but no usable "
            "data rows followed it. Every row was blank or had a Status value that "
            "could not be recognised."
        )

    detection = detect_month(filename, sheet, month_votes)
    fallback = force_month or detection["month"] or (
        (max(year_votes, key=year_votes.get) if year_votes else datetime.now().year),
        datetime.now().month)

    dominant_year = max(year_votes, key=year_votes.get) if year_votes else fallback[0]
    outliers = []
    stamp = datetime.now().isoformat(timespec="seconds")

    final = []
    for r in rows:
        dt = r.pop("_dt")
        if dt is None:
            y, m, d = fallback[0], fallback[1], None
            week = None
            iso = None
        else:
            y, m, d = dt.year, dt.month, dt.day
            if force_month:
                y, m = force_month
            week = date(dt.year, dt.month, dt.day).isocalendar()[1]
            iso = f"{y:04d}-{m:02d}-{d:02d}"
            if dt.year != dominant_year:
                outliers.append(dt.isoformat())
        r.update({"year": y, "month": m, "day": d, "week": week, "date": iso,
                  "market": market,
                  # traceability, kept on every single row
                  "source_file": os.path.basename(filename),
                  "source_sheet": sheet,
                  "imported_at": stamp})
        final.append(r)

    report = {
        "file": os.path.basename(filename),
        "sheet": sheet,
        "header_row": hdr_idx + 1,
        "columns_found": sorted(colmap.keys()),
        "columns_missing": sorted(set(_COLS) - set(colmap)),
        "rows_kept": len(final),
        "skipped_blank": skipped_blank,
        "skipped_unreadable": skipped_bad,
        "skipped_examples": bad_examples,
        "undated": undated,
        "dominant_year": dominant_year,
        "date_outliers": sorted(set(outliers))[:10],
        "periods": sorted({f"{r['year']}-{r['month']:02d}" for r in final}),
        "month_detection": detection,
        "forced_month": force_month,
        "imported_at": stamp,
    }
    return final, report


def _find_header(grid, scan=25):
    best, best_map, best_hits = None, None, 0
    for i, row in enumerate(grid[:scan]):
        labels = {}
        for j, cell in enumerate(row):
            if cell is None:
                continue
            key = re.sub(r"\s+", " ", str(cell)).strip().lower()
            if not key:
                continue
            for field, names in _COLS.items():
                if field in labels:
                    continue
                if key in names or any(key == n or key.startswith(n) for n in names):
                    labels[field] = j
        if "dev" in labels and "status" in labels and len(labels) > best_hits:
            best, best_map, best_hits = i, labels, len(labels)
    return best, (best_map or {})


def _cell(row, idx):
    return row[idx] if idx is not None and idx < len(row) else None


def _s(v):
    if v is None:
        return ""
    s = str(v).replace("\xa0", " ").strip()
    return "" if s.lower() in {"nan", "none", "nat"} else s


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _parse_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y",
                "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%Y/%m/%d", "%d-%b-%y",
                "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:                                                      # bare Excel serial
        n = float(s)
        if 20000 < n < 60000:
            return (datetime(1899, 12, 30) + timedelta(days=n)).date()
    except ValueError:
        pass
    return None


# ==========================================================================
# LEGACY PPT
# ==========================================================================
_MONTH_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*'?(\d{2,4})?\b", re.I)


def read_pptx(file_like, market, filename=None, default_year=None):
    """
    Recover month-level figures from a deck issued before this tool existed.

    Reads the layouts used in the client's decks:
      'Quality Score for month of X <Mon> <Year>'   -> headline counts
      'Developer Report ...'                        -> per-developer split
      'Error Analysis Internal & External ...'      -> category x internal/external

    Anything unrecognised is ignored rather than guessed at.
    """
    from pptx import Presentation

    data = file_like.read() if hasattr(file_like, "read") else file_like
    filename = filename or getattr(file_like, "name", "uploaded deck")
    if not data:
        raise IngestError("That presentation is empty — there is nothing to import.")
    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as exc:                                  # noqa: BLE001
        raise IngestError(
            "This file could not be opened as a PowerPoint presentation. It may be "
            "corrupted, or a .ppt saved with a .pptx name — open it in PowerPoint "
            f"and re-save as .pptx. ({type(exc).__name__})"
        ) from exc

    default_year = default_year or _year_from_text(filename) or datetime.now().year
    blocks, unread = {}, []

    for sn, slide in enumerate(prs.slides, 1):
        texts, tables = [], []
        for shp in slide.shapes:
            if shp.has_table:
                tables.append(_table_grid(shp.table))
            elif shp.has_text_frame and shp.text_frame.text.strip():
                texts.append(shp.text_frame.text.strip())
        title = " ".join(texts)[:200]
        low = title.lower()

        # A consolidated slide names a RANGE of months ("Jan - Jun 2026").
        # Reading it as a monthly slide silently replaces that month's real
        # figures with the whole-period totals, which is exactly what made an
        # imported C3 deck report 27 developers instead of 15.
        if _spans_multiple_months(title):
            unread.append(f"slide {sn}: consolidated view '{title[:44]}' \u2014 skipped, "
                          "monthly slides are used instead")
            continue

        ym = _month_year(title, default_year)
        if ym is None or not tables:
            if tables:
                unread.append(f"slide {sn}: table found but no month in the title")
            continue

        blk = blocks.setdefault(ym, _blank_block(market, ym, filename))
        if "quality score for" in low:
            _apply_headline(blk, tables[0])
        elif "developer report" in low or "developer summary" in low:
            _apply_developers(blk, tables[0])
        elif "error analysis" in low or "defect category" in low:
            _apply_categories(blk, tables[0])
        else:
            unread.append(f"slide {sn}: '{title[:44]}'")

    out = []
    stamp = datetime.now().isoformat(timespec="seconds")
    for (y, m), blk in sorted(blocks.items()):
        if blk["stated_total"] == 0 and blk["developers"]:
            blk["error"] = sum(d["error"] for d in blk["developers"])
            blk["no_error"] = sum(d["no_error"] for d in blk["developers"])
            blk["observation"] = sum(d["observation"] for d in blk["developers"])
            blk["stated_total"] = blk["error"] + blk["no_error"]
        _normalise_observations(blk)
        if blk["error"] + blk["no_error"] + blk["observation"] > 0:
            blk["imported_at"] = stamp
            blk.pop("stated_total", None)
            out.append(blk)

    if not out:
        raise IngestError(
            "No monthly figures could be read from this deck. The importer looks for "
            "slide titles like 'Quality Score for month of C3 Jan 2026' with a table "
            "underneath. If your deck uses a different layout, import the Excel audit "
            "sheet instead."
        )
    return out, {"file": os.path.basename(filename),
                 "months": [f"{b['year']}-{b['month']:02d}" for b in out],
                 "slides": len(prs.slides), "unread": unread[:12],
                 "converted": [b["year"] for b in out if b.get("observation_convention")
                               == "overlay"]}


def _blank_block(market, ym, filename):
    y, m = ym
    return {"market": market, "year": y, "month": m, "source": "pptx",
            "source_file": os.path.basename(filename),
            "error": 0, "no_error": 0, "observation": 0, "stated_total": 0,
            "observation_convention": None,
            "developers": [], "categories": []}


def _normalise_observations(blk):
    """
    Convert a legacy deck's observation convention to the canonical one.

    Legacy decks counted observations INSIDE the no-error figure, so the stated
    Grand Total equalled Error + No Error. Under the canonical rule the three
    counts are disjoint, so the overlaid observations have to be lifted out of
    No Error — otherwise the same month would gain phantom tasks and a higher
    score than it was published with.
    """
    err, ne, ob = blk["error"], blk["no_error"], blk["observation"]
    stated = blk.get("stated_total") or 0

    if ob and stated and stated == err + ne:
        blk["observation_convention"] = "overlay"
        blk["no_error"] = max(ne - ob, 0)
    else:
        blk["observation_convention"] = "disjoint"

    for d in blk.get("developers", []):
        dob, dne = d.get("observation", 0), d.get("no_error", 0)
        if blk["observation_convention"] == "overlay" and dob:
            d["no_error"] = max(dne - dob, 0)


def _table_grid(tbl):
    return [[(c.text or "").replace("\xa0", " ").strip() for c in row.cells] for row in tbl.rows]


def _year_from_text(text):
    m = re.search(r"\b(20\d{2})\b", str(text or ""))
    return int(m.group(1)) if m else None


def _month_year(text, default_year):
    m = _MONTH_RE.search(text or "")
    if not m:
        return None
    mon = MONTH_ABBR.index(m.group(1).title()) + 1
    yr = m.group(2)
    if yr:
        yr = int(yr)
        yr += 2000 if yr < 100 else 0
    else:
        yr = _year_from_text(text) or default_year
    return (yr, mon)


def _apply_headline(blk, grid):
    flat = []
    for row in grid:
        flat.extend(row)
    for i, cell in enumerate(flat):
        key = cell.lower().strip()
        val = _int(flat[i + 1]) if i + 1 < len(flat) else None
        if val is None:
            continue
        if key.startswith("observation"):
            blk["observation"] = val
        elif key.startswith("no error") or key.startswith("error free") \
                or key.startswith("error-free"):
            blk["no_error"] = val
        elif key.startswith("error"):
            blk["error"] = val
        elif key.startswith("total task"):
            blk["stated_total"] = val
    if not blk["stated_total"]:
        blk["stated_total"] = blk["error"] + blk["no_error"]


def _apply_developers(blk, grid):
    if len(grid) < 2:
        return
    hdr = [c.lower() for c in grid[0]]
    ci = {}
    for j, h in enumerate(hdr):
        if "developer" in h or h == "name":
            ci["name"] = j
        elif "no error" in h or "error-free" in h or "error free" in h:
            ci["no_error"] = j
        elif "observation" in h:
            ci["observation"] = j
        elif h.startswith("error"):
            ci.setdefault("error", j)
    if "name" not in ci:
        return
    devs = []
    for row in grid[1:]:
        nm = row[ci["name"]] if ci["name"] < len(row) else ""
        if not nm or nm.lower().startswith(("grand total", "total")):
            continue
        devs.append({
            "name": nz.display_name(nm), "raw": nm,
            "error": _int(row[ci["error"]]) or 0 if "error" in ci and ci["error"] < len(row) else 0,
            "no_error": _int(row[ci["no_error"]]) or 0 if "no_error" in ci and ci["no_error"] < len(row) else 0,
            "observation": _int(row[ci["observation"]]) or 0 if "observation" in ci and ci["observation"] < len(row) else 0,
        })
    if devs:
        blk["developers"] = devs


def _apply_categories(blk, grid):
    if len(grid) < 2:
        return
    hdr = [c.lower() for c in grid[0]]
    ci = {}
    # "live" and "test" are checked before "internal"/"external" because real
    # decks contain the typo `Live Link (Internal)`. Keying off the word
    # "internal" alone would map both columns to internal and lose every
    # external defect.
    for j, h in enumerate(hdr):
        if "live link" in h or "external" in h:
            ci["external"] = j
        elif "test link" in h or "internal" in h:
            ci.setdefault("internal", j)
    if "external" not in ci and "internal" in ci:
        # Two columns, both labelled internal: the second one is the live link.
        internals = [j for j, h in enumerate(hdr) if "internal" in h or "link" in h]
        if len(internals) >= 2:
            ci["internal"], ci["external"] = internals[0], internals[1]
    cats = []
    for row in grid[1:]:
        nm = row[0] if row else ""
        if not nm or nm.lower().startswith(("total", "grand total")):
            continue
        it = _int(row[ci["internal"]]) if "internal" in ci and ci["internal"] < len(row) else 0
        ex = _int(row[ci["external"]]) if "external" in ci and ci["external"] < len(row) else 0
        if (it or 0) or (ex or 0):
            cats.append({"category": nz.norm_category(nm), "internal": it or 0, "external": ex or 0})
    if cats:
        blk["categories"] = cats


def _int(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("%", "")
    if not s:
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def _spans_multiple_months(title):
    """
    True when a slide title names a period rather than a single month.

    Matches "Jan - Jun 2026", "Jan \u2013 June 2026", "January to June" and the like.
    """
    found = []
    for m in _MONTH_RE.finditer(title or ""):
        mon = MONTH_ABBR.index(m.group(1).title()) + 1
        if mon not in found:
            found.append(mon)
    return len(found) > 1
