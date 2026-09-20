"""
Writing the library back to the repository it was deployed from.

Why this exists: on a hosted server (Streamlit Community Cloud and friends) the
container's filesystem is temporary. An imported workbook written into
`qars/library/` is immediately shared with everyone using the running app —
they all read the same folder — but it is gone the moment the server restarts
or redeploys, because the container is rebuilt from the repository.

The repository is therefore the only place a month can live permanently. This
module commits the library files there through the GitHub contents API, which
also triggers the redeploy that makes them part of the app for good.

It is **off unless configured**, and the app says so plainly rather than
pretending an upload was kept. Configure it in `.streamlit/secrets.toml`:

    [github]
    token  = "ghp_..."          # a fine-grained token with Contents: write
    repo   = "owner/repository"
    branch = "main"             # optional, defaults to main

or with the environment variables QARS_GITHUB_TOKEN / QARS_GITHUB_REPO /
QARS_GITHUB_BRANCH.

This is the one part of the product that talks to the network, and only when
someone has deliberately switched it on.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

API = "https://api.github.com"
TIMEOUT = 25

_CONFIG = {"token": "", "repo": "", "branch": "main"}


def configure(token=None, repo=None, branch=None):
    """
    Point the publisher at a repository.

    Values passed in win; anything left out falls back to the environment, so
    a local run can export two variables and behave exactly like the hosted
    app. Called once per run by the app, which is the only layer that knows
    about Streamlit's secrets.
    """
    _CONFIG["token"] = (token or os.environ.get("QARS_GITHUB_TOKEN") or "").strip()
    _CONFIG["repo"] = (repo or os.environ.get("QARS_GITHUB_REPO") or "").strip()
    _CONFIG["branch"] = (branch or os.environ.get("QARS_GITHUB_BRANCH")
                         or "main").strip() or "main"
    return status()


def enabled():
    return bool(_CONFIG["token"] and _CONFIG["repo"])


def status():
    """What the UI needs to tell someone whether their upload will survive."""
    return {"enabled": enabled(), "repo": _CONFIG["repo"], "branch": _CONFIG["branch"],
            "has_token": bool(_CONFIG["token"])}


def _request(method, path, payload=None):
    url = f"{API}/repos/{_CONFIG['repo']}/contents/{path.lstrip('/')}"
    if method == "GET":
        url += f"?ref={_CONFIG['branch']}"
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


def _sha(path):
    """The blob currently at `path`, or None. GitHub needs it to replace one."""
    try:
        got = _request("GET", path)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return got.get("sha") if isinstance(got, dict) else None


def _explain(exc):
    if isinstance(exc, urllib.error.HTTPError):
        detail = ""
        try:
            detail = json.loads(exc.read() or b"{}").get("message", "")
        except Exception:                                     # noqa: BLE001
            pass
        if exc.code in (401, 403):
            return ("GitHub refused the token (%s). It needs Contents: write on %s."
                    % (detail or exc.code, _CONFIG["repo"]))
        if exc.code == 404:
            return (f"GitHub could not find {_CONFIG['repo']} on branch "
                    f"{_CONFIG['branch']}. Check the repository name and branch.")
        if exc.code == 409:
            return ("The branch moved while publishing. Try again — the library "
                    "on this server is unchanged.")
        return f"GitHub returned {exc.code}. {detail}".strip()
    if isinstance(exc, urllib.error.URLError):
        return f"Could not reach GitHub: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def push(files, message):
    """
    Commit `files` ({repo path: bytes}) one at a time.

    The contents API takes one file per call, which is fine here: an import
    writes the workbook and the index, never a hundred files. Each is reported
    separately so a partial success says exactly what landed.

    Returns (ok, detail).
    """
    if not enabled():
        return False, "Publishing to GitHub is not configured."
    done = []
    for path, blob in files.items():
        try:
            payload = {"message": message, "branch": _CONFIG["branch"],
                       "content": base64.b64encode(blob).decode("ascii")}
            sha = _sha(path)
            if sha:
                payload["sha"] = sha
            _request("PUT", path, payload)
            done.append(os.path.basename(path))
        except Exception as exc:                              # noqa: BLE001
            got = f" Committed first: {', '.join(done)}." if done else ""
            return False, _explain(exc) + got
    return True, f"Committed {', '.join(done)} to {_CONFIG['repo']}@{_CONFIG['branch']}."


def delete(paths, message):
    """Remove files from the repository. Missing files are not an error."""
    if not enabled():
        return False, "Publishing to GitHub is not configured."
    gone = []
    for path in paths:
        try:
            sha = _sha(path)
            if not sha:
                continue
            _request("DELETE", path, {"message": message, "sha": sha,
                                      "branch": _CONFIG["branch"]})
            gone.append(os.path.basename(path))
        except Exception as exc:                              # noqa: BLE001
            return False, _explain(exc)
    return True, (f"Removed {', '.join(gone)} from {_CONFIG['repo']}."
                  if gone else "Nothing to remove.")
