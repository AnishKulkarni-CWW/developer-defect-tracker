"""
Reports that ship with the application.

Some months were issued as PowerPoint before this tool existed, and the audit
workbooks behind them no longer exist. Rather than ask for a file nobody has,
those decks are part of the app: the January-June 2026 reports for C3 and
Japan live in `qars/baseline/` and are read straight into the database, so a
year-to-date report works from the first run and an uploaded workbook only ever
has to cover the months that come after them.

The decks are the source of truth, not a transcription of them — the same
reader that handled an uploaded deck parses these, so what the app shows is
what the deck published.

Task-level Excel always wins over a month recovered from a deck (see
`metrics.select`), so uploading a workbook for one of these months replaces the
deck figures for it rather than colliding with them.
"""

from __future__ import annotations

import copy
import os
from functools import lru_cache

from . import ingest

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline")

# market -> the deck shipped for it. A market absent from this map simply has
# no built-in history, which is the normal case.
DECKS = {
    "C3": "C3_Quality_Defect_Report_2026.pptx",
    "Japan": "Japan_Quality_Defect_Report_2026.pptx",
}

# Written onto every block this module produces. It is what makes a built-in
# month distinguishable from one the user imported, which the Data Manager
# needs in order to explain why it cannot be deleted.
SOURCE = "built-in"


def markets():
    return [m for m in DECKS if os.path.exists(os.path.join(DIR, DECKS[m]))]


def deck_path(market):
    name = DECKS.get(market)
    if not name:
        return None
    path = os.path.join(DIR, name)
    return path if os.path.exists(path) else None


@lru_cache(maxsize=8)
def _parse(market):
    """
    Read one shipped deck. Cached, because the file never changes while the
    process is alive and parsing it on every script run would be pure waste.

    A deck that cannot be read is not fatal: the app still works, it just has
    no built-in history for that market.
    """
    path = deck_path(market)
    if not path:
        return ()
    try:
        with open(path, "rb") as fh:
            blocks, _report = ingest.read_pptx(fh, market, filename=os.path.basename(path))
    except Exception:                                         # noqa: BLE001
        return ()
    for b in blocks:
        b["source"] = "pptx"
        b["origin"] = SOURCE
        b["source_file"] = os.path.basename(path)
    return tuple(blocks)


def blocks_for(market):
    """Fresh copies, so a caller mutating a block cannot poison the cache."""
    return [copy.deepcopy(b) for b in _parse(market)]


def periods_for(market):
    return {(b["year"], b["month"]) for b in _parse(market)}


def is_baseline(block):
    return block.get("origin") == SOURCE


def seed(db):
    """
    Put any missing built-in month back into `db`.

    Called on every run rather than once at creation: these months are part of
    the application, so clearing the data or restoring an older export must not
    leave a market with a hole in its history. A month the user has since
    uploaded a workbook for is left alone — that data is richer, and
    `metrics.select` already prefers it.

    Returns {market: months_added} for the markets that actually changed.
    """
    added = {}
    for market in markets():
        if market not in db.get("monthly", {}):
            continue
        have = {(b.get("year"), b.get("month")) for b in db["monthly"][market]}
        missing = [b for b in blocks_for(market) if (b["year"], b["month"]) not in have]
        if missing:
            db["monthly"][market].extend(missing)
            added[market] = len(missing)
    return added


def summary():
    """One line per market for the places that explain where the data came from."""
    out = []
    for market in markets():
        blocks = _parse(market)
        if not blocks:
            continue
        months = sorted((b["year"], b["month"]) for b in blocks)
        out.append({
            "market": market,
            "file": DECKS[market],
            "months": len(blocks),
            "first": months[0],
            "last": months[-1],
        })
    return out
