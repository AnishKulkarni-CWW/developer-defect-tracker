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

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
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


# What ships with the app, exactly as index.json records it. The index stays
# the source of truth; this is only for when it is missing or unreadable — a
# bad merge, a hand edit gone wrong — so that neither the history nor the
# corrections made when these files were embedded are lost with it. The test
# suite checks the two agree.
#   (market, file in the library, name it was uploaded as, forced month)
SHIPPED = (
    ("C3", "C3_Quality_Defect_Report_2026.pptx", "C3_Quality_Defect_Report_2026.pptx",
     None),
    ("Japan", "Japan_Quality_Defect_Report_2026.pptx",
     "Japan_Quality_Defect_Report_2026.pptx", None),
    ("India", "2026-07_July_2026_India.xlsx", "July 2026 India.xlsx", None),
    ("India", "2026-08_August_2026_India.xlsx", "August 2026 India.xlsx", None),
    ("India", "2026-09_September_2026_India.xlsx", "September 2026 India.xlsx", None),
    ("C3", "2026-07_July_2026_C3.xlsx", "July 2026 C3.xlsx", None),
    ("C3", "2026-08_August_2026_C3.xlsx", "August 2026 C3.xlsx", None),
    # Two rows are typed 1975; the sheet is September's.
    ("C3", "2026-09_September_2026_C3.xlsx", "September 2026 C3.xlsx", (2026, 9)),
    # Three re-test rows are dated August; the sheet is July's.
    ("Japan", "2026-07_July_2026_Japan.xlsx", "July 2026 Japan.xlsx", (2026, 7)),
    ("Japan", "2026-08_August_2026_Japan.xlsx", "August 2026 Japan.xlsx", None),
    ("Japan", "2026-09_September_2026_Japan.xlsx", "September 2026 Japan.xlsx", None),
)


def _default_index():
    """
    The files that ship with the app, described the way an import would be.

    Used when there is no readable index.json, so the vendored history is
    never lost to a damaged manifest. Order is preserved through `added`,
    which is what decides ownership between files.
    """
    out = []
    for n, (market, name, source, force) in enumerate(SHIPPED):
        rel = f"{market}/{name}"
        if not os.path.exists(os.path.join(DIR, rel)):
            continue
        row = {"id": _slug(f"{market}-{name}"), "market": market, "file": rel,
               "kind": "deck" if name.lower().endswith(DECK_EXT) else "workbook",
               "shipped": True, "periods": [],
               "added": f"2026-09-17T00:00:00.{n:03d}", "source_name": source}
        if force:
            row["force_month"] = [force[0], force[1]]
        out.append(row)
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

    # A file dropped into the folder by hand still counts — and with no index
    # at all, so does every file imported since the app shipped. Those were
    # necessarily added after everything that shipped, so they are ordered
    # after it: a correction of a shipped month still takes the month over.
    later = ""
    if rows is None:
        rows = _default_index()
        later = "2026-09-17T00:00:01"
    known = {r.get("file") for r in rows if isinstance(r, dict)}
    rows = rows + [dict(r, added=later) for r in _scan() if r["file"] not in known]

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
_NOTES = {}


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
    notes = {}
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
            rows, rep = ingest.read_excel(data, market,
                                          filename=entry.get("source_name")
                                          or os.path.basename(path))
            if force:
                _force_month(rows, int(force[0]), int(force[1]))
            for r in rows:
                r[TAG] = entry["id"]
                r["source_file"] = entry.get("source_name") or os.path.basename(path)
            out = ("tasks", rows)
            notes = {"uncounted": rep.get("uncounted_tasks") or [],
                     "typos": rep.get("status_typos") or {}}
    except Exception:                                         # noqa: BLE001
        # One unreadable file must not take the whole library down with it.
        out = (None, [])
        notes = {"unreadable": True}

    _CACHE[entry["id"]] = (key, out)
    _NOTES[entry["id"]] = notes
    return out


def reading_notes(entry):
    """
    What reading a kept file had to leave out or assume.

    Task rows it could not count (no status, no developer) and status typos it
    read as the status they were meant to be. A file embedded in the library
    never passes through the import review, so this is where those findings
    stay visible.
    """
    parse(entry)
    return _NOTES.get(entry["id"], {})


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


def primary_period(entry):
    """
    The month a file is *for*.

    A reviewer's forced month when there is one; otherwise the month holding
    most of its rows. An October sheet with three rows typed as September is
    still the October sheet — and treating it as a September sheet is exactly
    how one month's file used to delete another's.
    """
    forced = entry.get("force_month")
    if forced:
        return (int(forced[0]), int(forced[1]))
    kind, payload = parse(entry)
    if kind != "tasks" or not payload:
        per = periods_of(entry)
        return per[-1] if per else None
    counts = Counter((r["year"], r["month"]) for r in payload)
    return max(counts, key=lambda p: (counts[p], p))


def _chronological(rows):
    """Oldest first, by when each file entered the library."""
    return sorted(rows, key=lambda e: (e.get("added") or "", e["file"]))


def ownership(market=None, exclude=()):
    """
    {(market, (year, month)): entry_id} — which workbook supplies each month.

    The rule that keeps every month counted exactly once:

      1. a month comes from the newest file that is *for* that month;
      2. a month no file is for comes from the newest file with rows in it.

    So a corrected re-upload takes over its month, a stray row never steals
    a month from the sheet that owns it, and a multi-month workbook still
    supplies the months nobody else covers. Decks are not part of this:
    they hold month summaries, and metrics already prefers task rows to them.
    """
    books = _chronological([e for e in entries() if e["kind"] == "workbook"
                            and (market is None or e["market"] == market)
                            and e["id"] not in exclude])
    fallback, primary = {}, {}
    for e in books:                       # oldest first: later writes are newer
        for p in periods_of(e):
            fallback[(e["market"], p)] = e["id"]
        p = primary_period(e)
        if p:
            primary[(e["market"], p)] = e["id"]
    owner = dict(fallback)
    owner.update(primary)
    return owner


def months_supplied(entry_id, owner=None):
    """The months one entry actually supplies once ownership is decided."""
    owner = ownership() if owner is None else owner
    return sorted(p for (_m, p), eid in owner.items() if eid == entry_id)


def signature():
    """
    A fingerprint of the library's contents.

    Stored on the working database, so a session can tell that the library
    changed underneath it — a `git pull` brought new months, a pack was
    restored, a file was removed on another machine — and rebuild instead of
    keeping rows from a file that no longer supplies them.
    """
    parts = []
    for e in entries():
        path = os.path.join(DIR, e["file"])
        parts.append([e["id"], e.get("added", ""), e["file"], _stamp(path),
                      e.get("force_month")])
    parts.append(["aliases", aliases(), sorted(sorted(p) for p in distinct_pairs())])
    return hashlib.sha1(json.dumps(parts, default=str).encode()).hexdigest()


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
    owner = ownership()
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
            # A month this session imported on its own (the library could not
            # take the file) wins for this session: adding the library's copy
            # as well would count the month twice.
            local = {(r.get("year"), r.get("month")) for r in db["tasks"][market]
                     if not r.get(TAG)}
            mine = [r for r in payload
                    if owner.get((market, (r["year"], r["month"]))) == e["id"]
                    and (r["year"], r["month"]) not in local]
            if not mine:
                continue
            db["tasks"][market].extend(mine)
            months = len({(r["year"], r["month"]) for r in mine})
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

    if force_month:
        main = (int(force_month[0]), int(force_month[1]))
    elif probe["kind"] == "workbook":
        counts = Counter((r["year"], r["month"]) for r in rows)
        main = max(counts, key=lambda p: (counts[p], p))
    else:
        main = periods[-1]
    # Named for the month it is FOR, so the folder reads in reporting order.
    stem = f"{main[0]:04d}-{main[1]:02d}_{_slug(filename)}"
    rel = f"{market}/{stem}"
    path = os.path.join(DIR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    keep = [e for e in entries() if e["file"] != rel]
    with open(path, "wb") as fh:
        fh.write(data)

    entry = {"id": _slug(f"{market}-{stem}"), "market": market, "file": rel,
             "kind": probe["kind"], "shipped": False,
             "periods": [f"{y:04d}-{m:02d}" for y, m in periods],
             "primary": f"{main[0]:04d}-{main[1]:02d}",
             "added": _now_after(keep),
             "source_name": filename}
    if force_month:
        entry["force_month"] = [int(force_month[0]), int(force_month[1])]
    keep.append(entry)
    _write_index(keep)
    _CACHE.clear()

    # Housekeeping, never data loss: a file is removed only when it no longer
    # supplies a single month. One that still owns any month stays, whatever
    # else it overlaps — and a file that shipped with the app is never removed.
    owned = set(ownership(market).values())
    replaced = [e for e in entries() if e["market"] == market
                and e["kind"] == "workbook" and not e.get("shipped")
                and e["id"] != entry["id"] and e["id"] not in owned]
    if replaced:
        for e in replaced:
            try:
                os.remove(os.path.join(DIR, e["file"]))
            except OSError:
                pass
        gone = {e["id"] for e in replaced}
        _write_index([e for e in entries() if e["id"] not in gone])
        _CACHE.clear()
    return entry, replaced


def _now_after(rows):
    """
    An `added` stamp strictly later than every existing one.

    Ownership is decided by which file is newest, so two imports in the same
    second — three markets uploaded back to back — must still be ordered.
    """
    now = datetime.now().isoformat(timespec="seconds")
    latest = max((e.get("added") or "" for e in rows), default="")
    if now > latest:
        return now
    base = latest.split(".")[0]
    tail = int(latest.split(".")[1]) + 1 if "." in latest else 1
    return f"{base}.{tail:03d}"


def superseded_by(entry_id, owner=None):
    """
    For an entry that no longer supplies everything it holds: who took over.

    Returns {(year, month): taking_over_entry_id} for the months it has but
    does not supply, so the library page can say "replaced by …" rather than
    leave someone wondering why a file is listed but not counted.
    """
    e = next((x for x in entries() if x["id"] == entry_id), None)
    if not e or e["kind"] != "workbook":
        return {}
    owner = ownership() if owner is None else owner
    out = {}
    for p in periods_of(e):
        who = owner.get((e["market"], p))
        if who and who != entry_id:
            out[p] = who
    return out


def removal_effect(entry_id):
    """
    What removing one entry would do: (months_lost, months_restored).

    `months_restored` maps a month to the file that supplies it again once
    this one is gone — an earlier upload, or a file that shipped with the app
    — so undoing a corrected re-upload is seen to bring the original back.
    """
    e = next((x for x in entries() if x["id"] == entry_id), None)
    if not e:
        return [], {}
    if e["kind"] == "deck":
        return periods_of(e), {}
    before = months_supplied(entry_id)
    after = ownership(e["market"], exclude=(entry_id,))
    names = {x["id"]: x for x in entries()}
    decks = set()
    for x in entries():
        if x["market"] == e["market"] and x["kind"] == "deck" and x["id"] != entry_id:
            decks.update(periods_of(x))
    lost, restored = [], {}
    for p in before:
        who = after.get((e["market"], p))
        if who:
            restored[p] = names[who].get("source_name") or names[who]["file"]
        elif p in decks:
            restored[p] = "the issued report"
        else:
            lost.append(p)
    return lost, restored


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
# name decisions
#
# Merging two spellings of one person is a judgement someone made, and it is
# as much part of the record as the months themselves: lose it and the same
# person is counted twice in every report until somebody notices again. So it
# lives here, next to the files, rather than in per-session settings that a
# hosted server forgets on every refresh.
# ==========================================================================
def _aliases_path():
    return os.path.join(DIR, "aliases.json")


def _read_names_file():
    try:
        with open(_aliases_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def aliases():
    """{canonical name: [spellings]} — the merges someone decided by hand."""
    data = _read_names_file()
    groups = data.get("aliases", {})
    if not isinstance(groups, dict):
        return {}
    return {str(k): sorted({str(x) for x in v})
            for k, v in groups.items() if isinstance(v, list)}


def distinct_pairs():
    """Pairs someone confirmed are two different people. Never suggested again."""
    out = set()
    for pair in _read_names_file().get("distinct", []) or []:
        if isinstance(pair, list) and len(pair) == 2:
            out.add(frozenset(str(x) for x in pair))
    return out


def set_distinct(a, b):
    if not writable():
        raise LibraryError("This installation cannot write to its library folder.")
    pairs = distinct_pairs() | {frozenset((a, b))}
    _write_aliases(aliases(), pairs)
    return pairs


def _write_aliases(groups, pairs=None):
    pairs = distinct_pairs() if pairs is None else pairs
    os.makedirs(DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"aliases": {k: sorted(set(v)) for k, v in sorted(groups.items())},
                       "distinct": sorted(sorted(p) for p in pairs if len(p) == 2)},
                      fh, ensure_ascii=False, indent=1)
        os.replace(tmp, _aliases_path())
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def set_alias(canonical, spellings):
    """Record that every one of `spellings` is `canonical`. Returns the groups."""
    if not writable():
        raise LibraryError("This installation cannot write to its library folder.")
    groups = aliases()
    # A spelling belongs to one person: take it out of any other group first,
    # or a later decision could never undo an earlier one.
    want = {str(x) for x in spellings} - {canonical}
    for k in list(groups):
        if k != canonical:
            groups[k] = [x for x in groups[k] if x not in want and x != canonical]
            if not groups[k]:
                groups.pop(k)
    groups[canonical] = sorted(set(groups.get(canonical, [])) | want)
    _write_aliases(groups)
    return groups


def remove_alias(canonical):
    """Forget a hand-made merge. Returns True when there was one to forget."""
    groups = aliases()
    if canonical not in groups:
        return False
    if not writable():
        raise LibraryError("This installation cannot write to its library folder.")
    groups.pop(canonical)
    _write_aliases(groups)
    return True


def aliases_bytes():
    try:
        with open(_aliases_path(), "rb") as fh:
            return fh.read()
    except OSError:
        return json.dumps({"aliases": {}, "distinct": []}, indent=1).encode("utf-8")


# ==========================================================================
# describing
# ==========================================================================
def markets():
    return sorted({e["market"] for e in entries()})


def summary():
    """One row per entry, for the pages that explain where a figure came from."""
    out = []
    owner = ownership()
    for e in entries():
        per = periods_of(e)
        used = per if e["kind"] == "deck" else months_supplied(e["id"], owner)
        main = primary_period(e)
        out.append({"id": e["id"], "market": e["market"], "kind": e["kind"],
                    "used": used, "primary": main,
                    "superseded": superseded_by(e["id"], owner),
                    "notes": reading_notes(e),
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
    """Every month this market has in the library — the months it supplies."""
    out = set()
    owner = ownership(market)
    for e in entries():
        if e["market"] != market:
            continue
        if e["kind"] == "deck":
            out.update(periods_of(e))
        else:
            out.update(months_supplied(e["id"], owner))
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


def merged_index_bytes(remote, removed=()):
    """
    This library's index, combined with the copy in the repository.

    What this library holds wins. An entry only the repository has — added by
    a newer commit this server has not redeployed with yet — is kept, unless
    its file is one this change removes. `removed` holds library-relative
    paths ("C3/2026-10_x.xlsx"). An unreadable repository copy counts as
    empty: this library's own index is always complete for what it holds.
    """
    mine = entries()
    known = {e["file"] for e in mine}
    gone = set(removed)
    theirs = []
    try:
        data = json.loads(remote) if remote else {}
        theirs = data.get("entries", []) if isinstance(data, dict) else data
    except (ValueError, TypeError):
        theirs = []
    extra = [e for e in theirs if isinstance(e, dict) and e.get("file")
             and e["file"] not in known and e["file"] not in gone]
    return json.dumps({"entries": mine + extra}, ensure_ascii=False,
                      indent=1).encode("utf-8")


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
        z.writestr("aliases.json", aliases_bytes())
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
