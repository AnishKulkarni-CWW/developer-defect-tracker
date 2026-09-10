"""
JSON-file persistence. This *is* the database — no server, no engine, no
connection string. Two files under ./data:

  database.json  - every audited task row plus every imported monthly block
  settings.json  - developer alias map, benchmarks, report defaults

Writes are atomic (temp file + os.replace) so a crash mid-save cannot leave a
half-written database behind.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime

MARKETS = ["India", "C3", "Japan"]

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(APP_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "database.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")

SCHEMA_VERSION = 3

# --------------------------------------------------------------------------
# Where the data actually lives
#
# On a normal machine the JSON files under ./data ARE the database. On a hosted
# server (Streamlit Community Cloud and friends) that model breaks in two ways
# that matter for client data:
#
#   * the filesystem is wiped every time the app reboots, so "saved" work
#     silently disappears;
#   * every visitor shares one container, so one person's upload would be
#     visible to the next, and one person's "Clear all data" would wipe
#     everyone's.
#
# So on a hosted server the store runs in SESSION mode: nothing is written to
# disk, and each browser session keeps its own copy in memory. Work is kept via
# the Export / Restore database buttons instead.
# --------------------------------------------------------------------------
def _detect_session_mode():
    override = os.environ.get("QARS_STORAGE", "").strip().lower()
    if override in ("session", "memory"):
        return True
    if override in ("disk", "file"):
        return False
    # Streamlit Community Cloud checks the repo out under /mount/src.
    if APP_DIR.startswith("/mount/src") or os.environ.get("QARS_CLOUD") == "1":
        return True
    return False


SESSION_MODE = _detect_session_mode()


def storage_mode():
    """'session' (nothing persisted) or 'disk' (./data is the database)."""
    return "session" if SESSION_MODE else "disk"


def _fall_back_to_session(exc):
    """A read-only or full disk should degrade, not crash the app."""
    global SESSION_MODE
    SESSION_MODE = True
    return exc


def _empty_db():
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "schema_version": SCHEMA_VERSION,
        "created": now,
        "updated": now,
        "tasks": {m: [] for m in MARKETS},      # task-level rows from Excel/CSV
        "monthly": {m: [] for m in MARKETS},    # month blocks recovered from decks
        "sources": [],                          # import history — never auto-cleared
    }


def _default_settings():
    return {
        "schema_version": SCHEMA_VERSION,
        "dev_aliases": {},          # canonical name -> [raw spellings]
        "target_score": 95.0,
        "watch_score": 90.0,
        "org_name": "BMW",
        "prepared_by": "",
    }


# --------------------------------------------------------------------------
def _ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _writable():
    if SESSION_MODE:
        return False
    try:
        _ensure_dirs()
        return True
    except OSError as exc:
        _fall_back_to_session(exc)
        return False


def _read_json(path, fallback):
    if not _writable():
        return fallback()
    if not os.path.exists(path):
        obj = fallback()
        _write_json(path, obj)
        return obj
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        # Never hard-fail on a damaged file: park it and start clean.
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            shutil.copy2(path, os.path.join(BACKUP_DIR, f"corrupt_{stamp}_{os.path.basename(path)}"))
        except OSError:
            pass
        obj = fallback()
        _write_json(path, obj)
        return obj


def _write_json(path, obj):
    if not _writable():
        return False
    try:
        fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    except OSError as exc:
        _fall_back_to_session(exc)
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        _fall_back_to_session(exc)
        return False
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# --------------------------------------------------------------------------
def load_db():
    db = _read_json(DB_PATH, _empty_db)
    for key in ("tasks", "monthly"):
        db.setdefault(key, {})
        for m in MARKETS:
            db[key].setdefault(m, [])
    db.setdefault("sources", [])
    return db


def save_db(db):
    db["updated"] = datetime.now().isoformat(timespec="seconds")
    _write_json(DB_PATH, db)


def load_settings():
    s = _read_json(SETTINGS_PATH, _default_settings)
    for k, v in _default_settings().items():
        s.setdefault(k, v)
    # `observations_in_denominator` existed before the observation rule was
    # fixed. The rule is now mandatory and not configurable, so drop the key.
    s.pop("observations_in_denominator", None)
    return s


def save_settings(s):
    _write_json(SETTINGS_PATH, s)


def backup_db(tag="manual"):
    if not _writable():
        return None
    if not os.path.exists(DB_PATH):
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"database_{tag}_{stamp}.json")
    shutil.copy2(DB_PATH, dest)
    _prune_backups()
    return dest


def _prune_backups(keep=20):
    try:
        files = sorted((os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR)
                        if f.endswith(".json")), key=os.path.getmtime, reverse=True)
        for old in files[keep:]:
            os.remove(old)
    except OSError:
        pass


# --------------------------------------------------------------------------
# mutations
# --------------------------------------------------------------------------
def add_tasks(db, market, rows, source_name, replace_period=True):
    """
    Insert task rows for one market.

    `replace_period=True` removes existing rows for the (year, month) keys in
    `rows` first, so re-uploading a corrected sheet is idempotent instead of
    doubling every count.
    """
    existing = db["tasks"].get(market, [])
    periods = {(r["year"], r["month"]) for r in rows}
    removed = 0
    if replace_period and periods:
        keep = []
        for r in existing:
            if (r.get("year"), r.get("month")) in periods:
                removed += 1
            else:
                keep.append(r)
        existing = keep
    existing.extend(rows)
    db["tasks"][market] = existing
    _log_source(db, market, "excel", source_name, len(rows), removed, periods)
    return removed


def add_monthly(db, market, blocks, source_name):
    existing = db["monthly"].get(market, [])
    periods = {(b["year"], b["month"]) for b in blocks}
    keep = [b for b in existing if (b.get("year"), b.get("month")) not in periods]
    removed = len(existing) - len(keep)
    keep.extend(blocks)
    db["monthly"][market] = keep
    _log_source(db, market, "pptx", source_name, len(blocks), removed, periods)
    return removed


def _log_source(db, market, kind, name, count, replaced, periods):
    db.setdefault("sources", []).append({
        "market": market, "kind": kind, "name": name, "rows": count,
        "replaced": replaced,
        "periods": sorted(f"{y}-{m:02d}" for y, m in periods),
        "at": datetime.now().isoformat(timespec="seconds"),
    })


def delete_period(db, market, year, month):
    before = len(db["tasks"].get(market, [])) + len(db["monthly"].get(market, []))
    db["tasks"][market] = [r for r in db["tasks"].get(market, [])
                           if not (r.get("year") == year and r.get("month") == month)]
    db["monthly"][market] = [b for b in db["monthly"].get(market, [])
                             if not (b.get("year") == year and b.get("month") == month)]
    after = len(db["tasks"][market]) + len(db["monthly"][market])
    _log_source(db, market, "delete", f"{year}-{month:02d}", before - after, before - after,
                {(year, month)})
    return before - after


def clear_market(db, market):
    n = len(db["tasks"].get(market, [])) + len(db["monthly"].get(market, []))
    db["tasks"][market] = []
    db["monthly"][market] = []
    _log_source(db, market, "clear", "market cleared", n, n, set())
    return n


def clear_all_data(db):
    """
    Reset every market for a fresh upload.

    The import history in `sources` is deliberately preserved — it is the audit
    trail of what was loaded and when, and wiping it would destroy the record of
    work that was genuinely done. A `clear` entry is appended so the reset
    itself is part of that trail.
    """
    n = sum(len(db["tasks"].get(m, [])) + len(db["monthly"].get(m, [])) for m in MARKETS)
    for m in MARKETS:
        db["tasks"][m] = []
        db["monthly"][m] = []
    db.setdefault("sources", []).append({
        "market": "ALL", "kind": "clear", "name": "Clear all data",
        "rows": n, "replaced": n, "periods": [],
        "at": datetime.now().isoformat(timespec="seconds"),
    })
    return n


def clear_history(db):
    """Separate action — only ever called when the user explicitly asks."""
    n = len(db.get("sources", []))
    db["sources"] = []
    return n


# --------------------------------------------------------------------------
# portable snapshots — the way work is kept when nothing is written to disk
# --------------------------------------------------------------------------
def export_bytes(db):
    """The whole database as a downloadable JSON file."""
    return json.dumps(db, ensure_ascii=False, indent=1).encode("utf-8")


def import_bytes(payload):
    """
    Restore a database exported earlier.

    Validated rather than trusted: a stray JSON file dropped into the uploader
    should produce a clear message, not a half-loaded store that fails later
    with a KeyError somewhere deep in the metrics.
    """
    try:
        obj = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("That file is not readable JSON. Upload a file produced "
                         "by the Export database button.") from exc
    if not isinstance(obj, dict) or "tasks" not in obj or "monthly" not in obj:
        raise ValueError("That JSON file is not a QA Report Studio database. "
                         "Upload a file produced by the Export database button.")

    clean = _empty_db()
    for key in ("tasks", "monthly"):
        section = obj.get(key) or {}
        if not isinstance(section, dict):
            raise ValueError(f"The '{key}' section of that file is malformed.")
        for market in MARKETS:
            rows = section.get(market) or []
            clean[key][market] = list(rows) if isinstance(rows, list) else []
    src = obj.get("sources")
    clean["sources"] = list(src) if isinstance(src, list) else []
    clean["created"] = obj.get("created", clean["created"])

    counts = {m: len(clean["tasks"][m]) + len(clean["monthly"][m]) for m in MARKETS}
    if not sum(counts.values()):
        raise ValueError("That database is empty — there is nothing to restore.")
    return clean, counts
