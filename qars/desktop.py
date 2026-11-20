"""
Where the desktop app keeps what it learns.

Run from a checkout or on a server, the report library is the folder inside the
package (`qars/library/`) and the working copy is `./data/`, both beside the
code. An installed desktop app cannot work like that: an update replaces its
program folder wholesale, so a month imported on that computer, or a name merge
decided there, would vanish with the next update.

So the desktop launcher (`desktop/run_app.py`, the only file that knows the app
is packaged) calls `prepare()` before the app starts. It gives the app a home
of its own, per Windows user and outside the program folder:

    %LOCALAPPDATA%\\QAReportStudio\\
        library\\    the report library: what shipped with the app, plus
                     every sheet imported on this computer
        data\\       the working copy: database.json, settings.json, backups

and points the app at it through QARS_LIBRARY_DIR and QARS_DATA_DIR, which
`qars.library` and `qars.store` read when they are imported.

The library the app was built with is the seed. The first run copies it in.
An update that ships a different library is merged in: new and changed
shipped files land, files the new build no longer ships go — while everything
imported on this computer, and every name decision made on it, stays exactly
as it was.

Standard library only, and nothing imported from the rest of `qars`: the
launcher calls this while its start-up window is on screen, and pandas has no
business slowing that down.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile

APP_FOLDER = "QAReportStudio"

# Inside the per-user library: what the last sync brought in, so the next one
# can tell a file the user got rid of from a file a new build added.
STATE_FILE = ".shipped.json"
INDEX = "index.json"
ALIASES = "aliases.json"


# ==========================================================================
# locations
# ==========================================================================
def _usable(folder):
    """True if `folder` exists (or can be made) and a file can be written in it."""
    try:
        os.makedirs(folder, exist_ok=True)
        fd, probe = tempfile.mkstemp(dir=folder, suffix=".probe")
        os.close(fd)
        os.remove(probe)
        return True
    except OSError:
        return False


def home(app_folder=APP_FOLDER):
    """
    The per-user folder the desktop app keeps everything in.

    %LOCALAPPDATA% on Windows: always local (never synced to OneDrive or a
    roaming profile, so it works offline), always writable by the user, and
    needing no administrator rights. QARS_HOME overrides it — to keep the
    history somewhere else, or to point a test at a scratch folder.
    """
    override = os.environ.get("QARS_HOME", "").strip()
    candidates = [override] if override else []
    for var in ("LOCALAPPDATA", "APPDATA", "XDG_DATA_HOME"):
        root = os.environ.get(var, "").strip()
        if root:
            candidates.append(os.path.join(root, app_folder))
    candidates.append(os.path.join(os.path.expanduser("~"), ".local", "share", app_folder))
    candidates.append(os.path.join(tempfile.gettempdir(), app_folder))
    for folder in candidates:
        if _usable(folder):
            return folder
    return candidates[-1]


# ==========================================================================
# small helpers
# ==========================================================================
def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _entries(path):
    """The entries of an index.json, or None when it is missing or unreadable."""
    data = _read_json(path)
    if isinstance(data, dict):
        data = data.get("entries")
    if not isinstance(data, list):
        return None
    return [e for e in data if isinstance(e, dict) and e.get("file")]


def _write_json(path, obj):
    """Atomic, like every other write in the library: a temp file, then replace."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _digest(path):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _safe_path(root, rel):
    """`rel` inside `root`, or None for a path that would step outside it."""
    dest = os.path.normpath(os.path.join(root, rel))
    if not dest.startswith(os.path.normpath(root) + os.sep):
        return None
    return dest


def _copy(src, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)


def _has_library_files(folder):
    """Anything in the folder that the library would count as a month?"""
    if os.path.exists(os.path.join(folder, INDEX)):
        return True
    try:
        for market in os.listdir(folder):
            mdir = os.path.join(folder, market)
            if os.path.isdir(mdir) and any(
                    not n.startswith(".") for n in os.listdir(mdir)):
                return True
    except OSError:
        pass
    return False


def fingerprint(bundled):
    """
    A cheap fingerprint of the library a build shipped: its index, plus the
    name and size of every file. Computed on every start, so it reads no file
    contents; a change of either is what makes a sync worth running.
    """
    h = hashlib.sha1()
    try:
        with open(os.path.join(bundled, INDEX), "rb") as fh:
            h.update(fh.read())
    except OSError:
        return None
    for root, _dirs, files in sorted(os.walk(bundled)):
        for name in sorted(files):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, bundled).replace(os.sep, "/")
            try:
                h.update(f"{rel}:{os.path.getsize(path)};".encode("utf-8"))
            except OSError:
                pass
    return h.hexdigest()


# ==========================================================================
# name decisions
# ==========================================================================
def _merge_aliases(bundled_path, user_path):
    """
    Add the name decisions a new build ships to the ones made on this computer.

    A decision made here always wins: a shipped merge is added only when its
    name, and every spelling in it, is not already decided here; pairs marked
    as two different people are added to the ones already marked.
    """
    theirs = _read_json(bundled_path) or {}
    mine = _read_json(user_path) or {}
    groups = {str(k): list(v) for k, v in (mine.get("aliases") or {}).items()
              if isinstance(v, list)}
    claimed = set(groups) | {str(x) for v in groups.values() for x in v}
    changed = False
    for canon, spellings in (theirs.get("aliases") or {}).items():
        if not isinstance(spellings, list):
            continue
        names = {str(canon)} | {str(x) for x in spellings}
        if names & claimed:
            continue
        groups[str(canon)] = sorted({str(x) for x in spellings})
        claimed |= names
        changed = True
    pairs = {tuple(sorted(str(x) for x in p)) for p in (mine.get("distinct") or [])
             if isinstance(p, list) and len(p) == 2}
    for p in theirs.get("distinct") or []:
        if isinstance(p, list) and len(p) == 2:
            key = tuple(sorted(str(x) for x in p))
            if key not in pairs:
                pairs.add(key)
                changed = True
    if changed:
        _write_json(user_path, {"aliases": {k: sorted(set(v)) for k, v in sorted(groups.items())},
                                "distinct": sorted(list(p) for p in pairs)})
    return changed


# ==========================================================================
# the sync
# ==========================================================================
def sync_library(bundled, target):
    """
    Bring the per-user library at `target` up to date with the library this
    build shipped at `bundled`. Returns a report of what it did:

        {"action": "seeded" | "merged" | "current" | "no-seed",
         "added": [...], "updated": [...], "removed": [...]}

    The rules, in the order they matter:

      * an empty target is a first run: the whole shipped library is copied;
      * a target already in step with this build is left alone (the common
        case — every start after the first);
      * otherwise the shipped part is merged. A shipped file that is new or
        changed lands; a shipped file the new build no longer has is removed,
        exactly as it was removed from the build. Anything imported on this
        computer is never touched — including an import that replaced a
        shipped file of the same name, and a shipped file that was replaced
        and then removed here, which is not brought back.
    """
    report = {"action": "current", "added": [], "updated": [], "removed": []}
    shipped_rows = _entries(os.path.join(bundled, INDEX))
    if shipped_rows is None:
        report["action"] = "no-seed"
        return report
    # Everything the build's library holds is what this build ships — the
    # original reports and sheets, and any month imported into the repository
    # since (by publishing, or by running the app from the checkout the build
    # was made from). On this computer they are all "shipped with the app".
    shipped = {}
    for row in shipped_rows:
        src = _safe_path(bundled, row["file"])
        if src and os.path.isfile(src):
            shipped[row["file"]] = dict(row, shipped=True)
    fp = fingerprint(bundled)
    os.makedirs(target, exist_ok=True)
    state_path = os.path.join(target, STATE_FILE)

    # ---------------------------------------------------------- first run
    if not _has_library_files(target):
        for rel in shipped:
            _copy(os.path.join(bundled, rel), _safe_path(target, rel))
            report["added"].append(rel)
        _write_json(os.path.join(target, INDEX), {"entries": list(shipped.values())})
        src_alias = os.path.join(bundled, ALIASES)
        if os.path.isfile(src_alias):
            _copy(src_alias, os.path.join(target, ALIASES))
        _write_json(state_path, {
            "fingerprint": fp,
            "files": {rel: _digest(os.path.join(target, rel)) for rel in shipped},
            "aliases": _digest(src_alias)})
        report["action"] = "seeded"
        return report

    state = _read_json(state_path) or {}
    if fp and state.get("fingerprint") == fp:
        return report

    # ---------------------------------------------------------- an update
    report["action"] = "merged"
    prev = state.get("files") or {}          # file -> digest when it last landed
    rows = _entries(os.path.join(target, INDEX))
    if rows is None:
        _repair_without_index(bundled, target, shipped, prev, report)
    else:
        by_file = {r["file"]: r for r in rows}
        for rel, row in shipped.items():
            src = os.path.join(bundled, rel)
            dest = _safe_path(target, rel)
            mine = by_file.get(rel)
            if mine is not None and not mine.get("shipped"):
                continue                # replaced on this computer: theirs to keep
            if mine is None and rel in prev:
                continue                # replaced, then removed on this computer
            if mine is None and os.path.exists(dest):
                continue                # a file of this name was put here by hand
            if mine is None:
                _copy(src, dest)
                report["added"].append(rel)
            elif not os.path.exists(dest) or _digest(dest) != _digest(src):
                _copy(src, dest)
                report["updated"].append(rel)
            elif mine != row:
                report["updated"].append(rel)
            by_file[rel] = dict(row)

        # A shipped file this build no longer carries was retired on purpose
        # (India's July and August sheets, say, once the issued report covered
        # them). It goes here too, so the history matches the build.
        for rel in list(by_file):
            if by_file[rel].get("shipped") and rel not in shipped:
                path = _safe_path(target, rel)
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                del by_file[rel]
                report["removed"].append(rel)

        # Kept in the order they were, new arrivals after them; the library
        # orders entries by itself, so this is only for a person reading it.
        order = [r["file"] for r in rows if r["file"] in by_file]
        order += [rel for rel in by_file if rel not in order]
        _write_json(os.path.join(target, INDEX), {"entries": [by_file[f] for f in order]})

    src_alias = os.path.join(bundled, ALIASES)
    alias_digest = _digest(src_alias)
    user_alias = os.path.join(target, ALIASES)
    if alias_digest and alias_digest != state.get("aliases"):
        if not os.path.exists(user_alias):
            _copy(src_alias, user_alias)
        else:
            _merge_aliases(src_alias, user_alias)

    _write_json(state_path, {
        "fingerprint": fp,
        "files": {rel: _digest(os.path.join(target, rel)) for rel in shipped
                  if os.path.exists(os.path.join(target, rel))},
        "aliases": alias_digest})
    return report


def _repair_without_index(bundled, target, shipped, prev, report):
    """
    An update over a library whose index.json is missing or unreadable.

    The library rebuilds its view from the folder in that case (the shipped
    manifest in qars/library.py plus a scan), so no index is written here —
    one listing only some files would hide the rest. Files are only touched
    when they are provably still the copy the last sync put there.
    """
    for rel in shipped:
        src = os.path.join(bundled, rel)
        dest = _safe_path(target, rel)
        if not os.path.exists(dest):
            if rel not in prev:          # new in this build
                _copy(src, dest)
                report["added"].append(rel)
        elif prev.get(rel) == _digest(dest) and _digest(dest) != _digest(src):
            _copy(src, dest)
            report["updated"].append(rel)
    for rel in set(prev) - set(shipped):
        dest = _safe_path(target, rel)
        if dest and os.path.exists(dest) and prev.get(rel) == _digest(dest):
            try:
                os.remove(dest)
                report["removed"].append(rel)
            except OSError:
                pass


# ==========================================================================
# the one call the launcher makes
# ==========================================================================
def prepare(bundled_library, root=None):
    """
    Give the app its per-user home and point it there. Returns (home, report).

    Must run before `qars.library` and `qars.store` are imported, because they
    read QARS_LIBRARY_DIR and QARS_DATA_DIR at import time. If the per-user
    folder cannot be used at all, nothing is redirected and the app keeps its
    library in the program folder, which still works until the next update.
    """
    root = root or home()
    lib = os.path.join(root, "library")
    data = os.path.join(root, "data")
    os.environ["QARS_DESKTOP"] = "1"
    os.environ["QARS_STORAGE"] = "disk"
    if not (_usable(lib) and _usable(data)):
        return root, {"action": "unwritable", "added": [], "updated": [], "removed": []}
    try:
        report = sync_library(bundled_library, lib)
    except OSError as exc:
        report = {"action": f"failed: {exc}", "added": [], "updated": [], "removed": []}
    os.environ["QARS_LIBRARY_DIR"] = lib
    os.environ["QARS_DATA_DIR"] = data
    return root, report


# ==========================================================================
# shutting down from inside the page
# ==========================================================================
# The launcher registers how to close its window and stop the server; the
# app's Shut down button asks for it. One process holds both — Streamlit runs
# the app in the launcher's own interpreter — so this module is the meeting
# point, and nothing has to travel through a file or a socket.
_SHUTDOWN = []


def on_shutdown(fn):
    """Called by the launcher with the function that ends the program."""
    _SHUTDOWN[:] = [fn]


def can_shut_down():
    return bool(_SHUTDOWN)


def shut_down():
    """End the program — window first, then server. Returns False if nobody can."""
    if not _SHUTDOWN:
        return False
    import threading
    threading.Thread(target=_SHUTDOWN[0], name="qars-shutdown", daemon=True).start()
    return True
