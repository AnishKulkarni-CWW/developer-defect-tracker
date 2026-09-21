"""
The report library — every month this app knows, kept as the file it came from.

The problem this solves: a report covering January to September is built from
nine months of history, but nobody wants to upload nine files every month. So
the app keeps them. Each audit workbook that is imported is written into
`qars/library/`, next to the PowerPoint reports that were issued before this
tool existed, and every month in that folder is loaded at start-up. Upload
July, and next month you upload only August.

Files rather than a database, for three reasons:

  * they are the originals, so a month can always be re-read, re-checked or
    handed to someone else;
  * they live in the repository, which is what makes them survive a hosted
    server restarting — see `qars/publish.py`;
  * every visitor to a running app reads the same folder, so one person's
    upload is everyone's history without any shared-database machinery.

`index.json` is the manifest: which file covers which market and months, how
it was read, and whether it shipped with the app. It is the source of truth;
the folder scan is only a fallback for a damaged or missing index.

Nothing here imports Streamlit — this module is the storage layer, and it is
exercised directly by the tests.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime

from . import ingest

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library")
INDEX = os.path.join(DIR, "index.json")

WORKBOOK_EXT = (".xlsx", ".xlsm", ".xls", ".csv")
DECK_EXT = (".pptx",)

# Written onto every row and every month this module produces, so a rebuild
# can tell library-backed data from whatever the current session added on its
# own and replace only the former.
TAG = "lib"


# ==========================================================================
# index
# ==========================================================================
def _slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")[:90] or "file"


def _default_index():
    """
    The decks that ship with the app, described the way an import would be.

    Used when there is no index.json — a fresh checkout, or one damaged badly
    enough to be unreadable — so the vendored reports are never lost to a
    missing manifest.
    """
    out = []
    for market, name in (("C3", "C3_Quality_Defect_Report_2026.pptx"),
                         ("Japan", "Japan_Quality_Defect_Report_2026.pptx")):
        rel = f"{market}/{name}"
        if os.path.exists(os.path.join(DIR, rel)):
            out.append({"id": _slug(f"{market}-{name}"), "market": market, "file": rel,
                        "kind": "deck", "shipped": True, "periods": [],
                        "added": "", "source_name": name})
    return out


def _scan():
    """Whatever is actually in the folder, for when the index disagrees."""
    out = []
    if not os.path.isdir(DIR):
        return out
    for market in sorted(os.listdir(DIR)):
        mdir = os.path.join(DIR, market)
        if not os.path.isdir(mdir):
            continue
        for name in sorted(os.listdir(mdir)):
            ext = os.path.splitext(name)[1].lower()
            if ext not in WORKBOOK_EXT + DECK_EXT:
                continue
            out.append({"id": _slug(f"{market}-{name}"), "market": market,
                        "file": f"{market}/{name}",
                        "kind": "deck" if ext in DECK_EXT else "workbook",
                        "shipped": False, "periods": [], "added": "",
                        "source_name": name})
    return out


def entries():
    """
    Every library entry, oldest first.

    Falls back to a folder scan when the index is missing or unreadable, and
    drops any entry whose file has gone — a manifest pointing at nothing is
    worse than no manifest.
    """
    rows = None
    try:
        with open(INDEX, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data = data.get("entries")
        if isinstance(data, list):
            rows = data
    except (OSError, json.JSONDecodeError, ValueError):
        rows = None

    if rows is None:
        rows = _default_index() or _scan()
    else:
        # A file dropped into the folder by hand still counts.
        known = {r.get("file") for r in rows}
        rows = rows + [r for r in _scan() if r["file"] not in known]

    alive = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("file"):
            continue
        if not os.path.exists(os.path.join(DIR, r["file"])):
            continue
        r.setdefault("id", _slug(f"{r.get('market', '')}-{os.path.basename(r['file'])}"))
        r.setdefault("kind", "deck" if r["file"].lower().endswith(DECK_EXT) else "workbook")
        r.setdefault("shipped", False)
        r.setdefault("periods", [])
        r.setdefault("added", "")
        r.setdefault("source_name", os.path.basename(r["file"]))
        alive.append(r)
    alive.sort(key=lambda r: (not r.get("shipped"), r.get("added") or "",
                              r.get("periods") or [], r["file"]))
    return alive


def _write_index(rows):
    os.makedirs(DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"entries": rows}, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, INDEX)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def writable():
    """Can this installation actually keep what is imported?"""
    try:
        os.makedirs(DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=DIR, suffix=".probe")
        os.close(fd)
        os.remove(tmp)
        return True
    except OSError:
        return False


# ==========================================================================
# reading
# ==========================================================================
_CACHE = {}


def _stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def parse(entry):
    """
    Read one entry into ('monthly', blocks) or ('tasks', rows).

    Cached on the file's own mtime and size: the file does not change while
    the process lives, except when an import writes a new one, and then the
    stamp changes and the cache misses exactly as it should.
    """
    path = os.path.join(DIR, entry["file"])
    key = (path, _stamp(path), tuple(entry.get("force_month") or ()))
    hit = _CACHE.get(entry["id"])
    if hit and hit[0] == key:
        return hit[1]

    market = entry["market"]
    force = entry.get("force_month")
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        if entry["kind"] == "deck":
            blocks, _rep = ingest.read_pptx(data, market,
                                            filename=os.path.basename(path))
            for b in blocks:
                b["source"] = "pptx"
                b[TAG] = entry["id"]
                b["shipped"] = bool(entry.get("shipped"))
                b["source_file"] = entry["source_name"]
            out = ("monthly", blocks)
        else:
            rows, _rep = ingest.read_excel(data, market,
                                           filename=entry.get("source_name")
                                           or os.path.basename(path))
            if force:
                _force_month(rows, int(force[0]), int(force[1]))
            for r in rows:
                r[TAG] = entry["id"]
                r["source_file"] = entry.get("source_name") or os.path.basename(path)
            out = ("tasks", rows)
    except Exception:                                         # noqa: BLE001
        # One unreadable file must not take the whole library down with it.
        out = (None, [])

    _CACHE[entry["id"]] = (key, out)
    return out


def _force_month(rows, year, month):
    """Re-file every row under one period — the reviewer's correction, kept."""
    for r in rows:
        r["year"], r["month"] = year, month
        if r.get("date"):
            r["date"] = f"{year:04d}-{month:02d}-{r['date'][-2:]}"


def periods_of(entry):
    kind, payload = parse(entry)
    if kind == "monthly":
        return sorted({(b["year"], b["month"]) for b in payload})
    if kind == "tasks":
        return sorted({(r["year"], r["month"]) for r in payload})
    return []


# ==========================================================================
# seeding
# ==========================================================================
def seed(db):
    """
    Put every library month into `db` that is not already there.

    Called on every run rather than once: the library is the app's permanent
    record, so clearing the working data or restoring an older export must not
    leave a market with a hole in its history.

    Returns {market: months_added} for the markets that changed.
    """
    added = {}
    for e in entries():
        market = e["market"]
        if market not in db.get("monthly", {}) or market not in db.get("tasks", {}):
            continue
        kind, payload = parse(e)
        if not payload:
            continue
        if kind == "monthly":
            if any(b.get(TAG) == e["id"] for b in db["monthly"][market]):
                continue
            # A month the user has since uploaded a workbook for keeps the
            # workbook: task rows are richer, and metrics already prefers them.
            present = {(b.get("year"), b.get("month")) for b in db["monthly"][market]}
            fresh = [b for b in payload if (b["year"], b["month"]) not in present]
            db["monthly"][market].extend(fresh)
            if fresh:
                added[market] = added.get(market, 0) + len(fresh)
        else:
            if any(r.get(TAG) == e["id"] for r in db["tasks"][market]):
                continue
            db["tasks"][market].extend(payload)
            months = len({(r["year"], r["month"]) for r in payload})
            added[market] = added.get(market, 0) + months
    return added


def resync(db):
    """
    Rebuild the library-backed part of `db` from the folder.

    Everything this module put there is dropped and re-seeded; anything the
    session added on its own is untouched. Used after an import or a removal,
    so one code path decides what the library means and the rest of the app
    never has to reason about it.
    """
    for market in list(db.get("tasks", {})):
        db["tasks"][market] = [r for r in db["tasks"][market] if not r.get(TAG)]
    for market in list(db.get("monthly", {})):
        db["monthly"][market] = [b for b in db["monthly"][market] if not b.get(TAG)]
    _CACHE.clear()
    return seed(db)


# ==========================================================================
# writing
# ==========================================================================
class LibraryError(Exception):
    """Raised when a file cannot be kept — always with something to act on."""


def add(market, filename, data, force_month=None):
    """
    Keep an imported workbook, and return (entry, replaced_entries).

    The file is parsed before anything is written: a workbook the app cannot
    read must never reach the library, or every future start-up inherits the
    problem. A month already covered by an earlier entry replaces it, so
    re-importing a corrected sheet does exactly what the person expects.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in WORKBOOK_EXT + DECK_EXT:
        raise LibraryError(f"{filename} is not a file the library can keep.")
    if not writable():
        raise LibraryError("This installation cannot write to its library folder.")

    probe = {"id": "probe", "market": market, "file": "", "kind":
             "deck" if ext in DECK_EXT else "workbook",
             "source_name": filename, "force_month": force_month}
    try:
        if probe["kind"] == "deck":
            blocks, _ = ingest.read_pptx(data, market, filename=filename)
            periods = sorted({(b["year"], b["month"]) for b in blocks})
        else:
            rows, _ = ingest.read_excel(data, market, filename=filename)
            if force_month:
                _force_month(rows, int(force_month[0]), int(force_month[1]))
            periods = sorted({(r["year"], r["month"]) for r in rows})
    except ingest.IngestError as exc:
        raise LibraryError(str(exc)) from exc
    if not periods:
        raise LibraryError(f"{filename} has no usable rows, so there is nothing to keep.")

    stem = f"{periods[0][0]:04d}-{periods[0][1]:02d}_{_slug(filename)}"
    rel = f"{market}/{stem}"
    path = os.path.join(DIR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    rows_idx = entries()
    covered = set(periods)
    replaced = [e for e in rows_idx
                if e["market"] == market and not e.get("shipped")
                and e["file"] != rel and set(periods_of(e)) <= covered]
    keep = [e for e in rows_idx if e not in replaced and e["file"] != rel]

    with open(path, "wb") as fh:
        fh.write(data)
    for e in replaced:
        try:
            os.remove(os.path.join(DIR, e["file"]))
        except OSError:
            pass

    entry = {"id": _slug(f"{market}-{stem}"), "market": market, "file": rel,
             "kind": probe["kind"], "shipped": False,
             "periods": [f"{y:04d}-{m:02d}" for y, m in periods],
             "added": datetime.now().isoformat(timespec="seconds"),
             "source_name": filename}
    if force_month:
        entry["force_month"] = [int(force_month[0]), int(force_month[1])]
    keep.append(entry)
    _write_index(keep)
    _CACHE.clear()
    return entry, replaced


def remove(entry_id):
    """Drop an added entry. Files that shipped with the app are not removable."""
    rows = entries()
    target = next((e for e in rows if e["id"] == entry_id), None)
    if target is None:
        raise LibraryError("That entry is no longer in the library.")
    if target.get("shipped"):
        raise LibraryError("That report ships with the app and cannot be removed here.")
    if not writable():
        raise LibraryError("This installation cannot write to its library folder.")
    try:
        os.remove(os.path.join(DIR, target["file"]))
    except OSError:
        pass
    _write_index([e for e in rows if e["id"] != entry_id])
    _CACHE.clear()
    return target


def entry_for_period(market, year, month):
    """Which library file, if any, is responsible for one month of one market."""
    for e in entries():
        if e["market"] == market and (year, month) in periods_of(e):
            return e
    return None


# ==========================================================================
# describing
# ==========================================================================
def markets():
    return sorted({e["market"] for e in entries()})


def summary():
    """One row per entry, for the pages that explain where a figure came from."""
    out = []
    for e in entries():
        per = periods_of(e)
        out.append({"id": e["id"], "market": e["market"], "kind": e["kind"],
                    "shipped": bool(e.get("shipped")),
                    "file": os.path.basename(e["file"]),
                    "source_name": e.get("source_name") or os.path.basename(e["file"]),
                    "added": e.get("added", ""), "months": len(per),
                    "first": per[0] if per else None, "last": per[-1] if per else None,
                    "periods": per,
                    "bytes": os.path.getsize(os.path.join(DIR, e["file"]))
                    if os.path.exists(os.path.join(DIR, e["file"])) else 0})
    return out


def periods_for(market):
    """Every month this market has in the library."""
    out = set()
    for e in entries():
        if e["market"] == market:
            out.update(periods_of(e))
    return out


def shipped_periods_for(market):
    out = set()
    for e in entries():
        if e["market"] == market and e.get("shipped"):
            out.update(periods_of(e))
    return out


def is_library(record):
    return bool(record.get(TAG))


def is_shipped(record):
    return bool(record.get("shipped")) and bool(record.get(TAG))


def file_bytes(entry_id):
    """The original file, for handing back to someone who needs to keep it."""
    e = next((x for x in entries() if x["id"] == entry_id), None)
    if not e:
        return None, None
    path = os.path.join(DIR, e["file"])
    try:
        with open(path, "rb") as fh:
            return e, fh.read()
    except OSError:
        return e, None


def index_bytes():
    try:
        with open(INDEX, "rb") as fh:
            return fh.read()
    except OSError:
        return json.dumps({"entries": entries()}, indent=1).encode("utf-8")


def export_pack():
    """
    The whole library as one zip.

    The manual route to permanence: download this, unpack it over
    `qars/library/` in the repository, commit, and every future visitor has the
    same history whatever the server did in between.
    """
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        rows = entries()
        z.writestr("index.json", json.dumps({"entries": rows}, indent=1))
        for e in rows:
            path = os.path.join(DIR, e["file"])
            if os.path.exists(path):
                z.write(path, e["file"])
    return buf.getvalue()


def restore_pack(data):
    """Unpack an exported library over this one. Returns how many files landed."""
    import io
    import zipfile
    if not writable():
        raise LibraryError("This installation cannot write to its library folder.")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise LibraryError("That file is not a library export.") from exc
    names = [n for n in z.namelist() if not n.endswith("/")]
    if "index.json" not in names:
        raise LibraryError("That zip has no index.json, so it is not a library export.")
    written = 0
    for name in names:
        # Never let a crafted archive write outside the library folder.
        dest = os.path.normpath(os.path.join(DIR, name))
        if not dest.startswith(os.path.normpath(DIR) + os.sep):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with z.open(name) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        written += 1
    _CACHE.clear()
    return written
