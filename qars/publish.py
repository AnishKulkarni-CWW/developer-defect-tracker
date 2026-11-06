"""
Writing the report library back to the repository it was deployed from.

Why this exists: on a hosted server (Streamlit Community Cloud and friends) the
container's filesystem is temporary. An imported workbook written into
`qars/library/` is immediately shared with everyone using the running app —
they all read the same folder — but it is gone the moment the server restarts
or redeploys, because the container is rebuilt from the repository.

The repository is therefore the only place a month can live permanently. This
module commits library files there, which also triggers the redeploy that
makes them part of the app for good.

Every change is ONE commit, built through the Git Data API (blobs → tree →
commit → move the branch). The obvious alternative, the contents API, takes
one file per call: an import would land as two commits, and a redeploy
triggered by the first would start a container holding a workbook its index
did not yet describe. One commit cannot be half there.

It is **off unless configured**, and the app says so plainly rather than
pretending an upload was kept. Configure it in `.streamlit/secrets.toml`:

    [github]
    token  = "github_pat_..."   # fine-grained token, Contents: read and write
    repo   = "owner/repository"
    branch = "main"             # the branch the app is deployed from

or with the environment variables QARS_GITHUB_TOKEN / QARS_GITHUB_REPO /
QARS_GITHUB_BRANCH.

This is the one part of the product that talks to the network, and only when
someone has deliberately switched it on.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request

API = "https://api.github.com"
TIMEOUT = 25
RETRIES = 3

_CONFIG = {"token": "", "repo": "", "branch": "main"}


def configure(token=None, repo=None, branch=None):
    """
    Point the publisher at a repository.

    Values passed in win; anything left out falls back to the environment, so
    a local run can export variables and behave exactly like the hosted app.
    Called once per run by the app, which is the only layer that knows about
    Streamlit's secrets.
    """
    _CONFIG["token"] = (token or os.environ.get("QARS_GITHUB_TOKEN") or "").strip()
    _CONFIG["repo"] = (repo or os.environ.get("QARS_GITHUB_REPO") or "").strip().strip("/")
    _CONFIG["branch"] = (branch or os.environ.get("QARS_GITHUB_BRANCH")
                         or "main").strip() or "main"
    return status()


def enabled():
    return bool(_CONFIG["token"] and _CONFIG["repo"])


def status():
    """What the UI needs to tell someone whether their upload will survive."""
    return {"enabled": enabled(), "repo": _CONFIG["repo"], "branch": _CONFIG["branch"],
            "has_token": bool(_CONFIG["token"])}


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------
def _api(method, path, payload=None):
    url = f"{API}/repos/{_CONFIG['repo']}/{path.lstrip('/')}" if path else \
        f"{API}/repos/{_CONFIG['repo']}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_CONFIG['token']}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "qa-report-studio")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = resp.read()
    return json.loads(body) if body else {}


def _explain(exc):
    if isinstance(exc, urllib.error.HTTPError):
        detail = ""
        try:
            detail = json.loads(exc.read() or b"{}").get("message", "")
        except Exception:                                     # noqa: BLE001
            pass
        if exc.code == 401:
            return ("GitHub did not accept the token — it may be mistyped, expired or "
                    "revoked. Create a new one and update the secret.")
        if exc.code == 403:
            return (f"GitHub refused the token ({detail or 'forbidden'}). It needs "
                    f"Contents: read and write on {_CONFIG['repo']}.")
        if exc.code == 404:
            return (f"GitHub could not find {_CONFIG['repo']} on branch "
                    f"{_CONFIG['branch']} — or the token cannot see it. Check the "
                    "repository name, the branch, and the token's repository access.")
        if exc.code in (409, 422):
            return ("The branch moved while publishing and the retry did not settle. "
                    "Nothing was lost on this server; publish again in a moment.")
        return f"GitHub returned {exc.code}. {detail}".strip()
    if isinstance(exc, urllib.error.URLError):
        return f"Could not reach GitHub: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def _blob_sha(data):
    """The id git gives these bytes — lets an unchanged file be skipped."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# --------------------------------------------------------------------------
# public
# --------------------------------------------------------------------------
def check():
    """
    Prove the configuration works before anything depends on it.

    Reads the repository and the branch, then proves the token can write by
    storing one small object that no commit points at. That changes nothing
    anyone can see — no branch moves, no file appears — but it is the only
    honest test: the repository's own `permissions` describe the account, and
    a fine-grained token can still be read-only. Returns (ok, detail).
    """
    if not enabled():
        return False, "Publishing to GitHub is not configured."
    read_only = (f"The token can read {_CONFIG['repo']} but not write to it. "
                 "Give it Contents: read and write.")
    try:
        repo = _api("GET", "")
        _api("GET", f"git/ref/heads/{_CONFIG['branch']}")
    except Exception as exc:                                  # noqa: BLE001
        return False, _explain(exc)
    perms = repo.get("permissions") or {}
    if perms and not perms.get("push"):
        return False, read_only
    try:
        _api("POST", "git/blobs",
             {"content": base64.b64encode(b"QA Report Studio connection check").decode(),
              "encoding": "base64"})
    except urllib.error.HTTPError as exc:
        return False, read_only if exc.code in (403, 404) else _explain(exc)
    except Exception as exc:                                  # noqa: BLE001
        return False, _explain(exc)
    return True, (f"Connected to {_CONFIG['repo']} on {_CONFIG['branch']}. Imports will "
                  "be committed there and become part of the app.")


def _read_blob(sha):
    """The bytes of one file in the repository, or None when it has none."""
    if not sha:
        return None
    blob = _api("GET", f"git/blobs/{sha}")
    return base64.b64decode(blob.get("content") or b"")


def commit(files, deletions=(), message="Update the QA report library", merge=None):
    """
    Write `files` ({repo path: bytes}) and remove `deletions`, as one commit.

    `merge` is {repo path: fn(bytes_in_repository_or_None) -> bytes} for a file
    that has to be combined with the repository's own copy rather than written
    over it — the library index, which a newer commit may have added to since
    this server last read it. It runs again on every retry, so it always
    merges with the newest copy.

    Unchanged files are skipped and an empty change makes no commit at all, so
    publishing twice is harmless. If someone else moved the branch in the
    meantime, the commit is rebuilt on top of theirs and retried.

    Returns (ok, detail).
    """
    if not enabled():
        return False, "Publishing to GitHub is not configured."
    branch = _CONFIG["branch"]
    last = None
    for _attempt in range(RETRIES):
        try:
            head = _api("GET", f"git/ref/heads/{branch}")["object"]["sha"]
            base_tree = _api("GET", f"git/commits/{head}")["tree"]["sha"]
            listing = _api("GET", f"git/trees/{base_tree}?recursive=1").get("tree", [])
            current = {t["path"]: t.get("sha") for t in listing if t.get("type") == "blob"}

            want = dict(files)
            for path, fn in (merge or {}).items():
                want[path] = fn(_read_blob(current.get(path)))

            changes, written, removed = [], [], []
            for path, data in want.items():
                if current.get(path) == _blob_sha(data):
                    continue                              # already exactly this
                blob = _api("POST", "git/blobs",
                            {"content": base64.b64encode(data).decode("ascii"),
                             "encoding": "base64"})["sha"]
                changes.append({"path": path, "mode": "100644", "type": "blob",
                                "sha": blob})
                written.append(os.path.basename(path))
            for path in deletions:
                if path in current and path not in want:
                    changes.append({"path": path, "mode": "100644", "type": "blob",
                                    "sha": None})
                    removed.append(os.path.basename(path))
            if not changes:
                return True, f"{_CONFIG['repo']}@{branch} already has all of this."

            tree = _api("POST", "git/trees", {"base_tree": base_tree,
                                              "tree": changes})["sha"]
            new = _api("POST", "git/commits", {"message": message, "tree": tree,
                                               "parents": [head]})["sha"]
            _api("PATCH", f"git/refs/heads/{branch}", {"sha": new, "force": False})
            where = f"{_CONFIG['repo']}@{branch}"
            if written and removed:
                return True, (f"Committed {', '.join(written)} and removed "
                              f"{', '.join(removed)} on {where}.")
            if removed:
                return True, f"Removed {', '.join(removed)} from {where}."
            return True, f"Committed {', '.join(written)} to {where}."
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (409, 422):                    # branch moved: rebuild
                continue
            return False, _explain(exc)
        except Exception as exc:                              # noqa: BLE001
            return False, _explain(exc)
    return False, _explain(last)


# Kept for callers written against the one-file-at-a-time interface.
def push(files, message, merge=None):
    return commit(files, (), message, merge)


def delete(paths, message, merge=None):
    return commit({}, paths, message, merge)
