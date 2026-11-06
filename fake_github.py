"""
A stand-in for the part of GitHub's API that `qars/publish.py` uses.

Used only by the test suites. It runs on 127.0.0.1 in a background thread,
holds one repository in memory, and behaves like GitHub where it matters to
the publisher: tokens are checked, a read-only token cannot write, a branch
only moves forward, and a commit lands whole or not at all. The tests point
`publish.API` at it, so the real request code runs end to end — nothing is
mocked out, and nothing leaves this machine.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


def _sha(kind, data):
    """The id git gives an object — the same sum the publisher compares."""
    return hashlib.sha1(f"{kind} {len(data)}\0".encode() + data).hexdigest()


class FakeGitHub:
    def __init__(self, repo="owner/repo", branch="main", token="good-token", push=True,
                 files=None):
        self.repo, self.branch, self.token, self.push = repo, branch, token, push
        # What GitHub reports as the *account's* permission. A fine-grained token
        # can be read-only while this still says push: True.
        self.account_push = push
        self.blobs, self.trees, self.commits, self.refs = {}, {}, {}, {}
        self.calls = []            # (method, path) of every request, in order
        self.fail_patch = 0        # reject this many branch moves as non-fast-forward
        self.on_patch = None       # called once, just before the next branch move
        self.lock = threading.Lock()
        tree = self._tree({p: self._blob(b) for p, b in (files or {}).items()})
        self.refs[branch] = self._commit(tree, [], "Initial commit")

    # ------------------------------------------------------------------ store
    def _blob(self, data):
        sha = _sha("blob", data)
        self.blobs[sha] = data
        return sha

    def _tree(self, entries):
        sha = _sha("tree", json.dumps(sorted(entries.items())).encode())
        self.trees[sha] = dict(entries)
        return sha

    def _commit(self, tree, parents, message):
        sha = _sha("commit", json.dumps([tree, parents, message, len(self.commits)]).encode())
        self.commits[sha] = {"tree": tree, "parents": list(parents), "message": message}
        return sha

    # ------------------------------------------------------- what tests read
    def head(self):
        return self.refs[self.branch]

    def files(self):
        """{path: bytes} on the branch as it stands now."""
        tree = self.trees[self.commits[self.head()]["tree"]]
        return {p: self.blobs[s] for p, s in tree.items()}

    def history(self):
        """Commit messages on the branch, newest first."""
        out, cur = [], self.head()
        while cur:
            c = self.commits[cur]
            out.append(c["message"])
            cur = c["parents"][0] if c["parents"] else None
        return out

    def blob_uploads(self):
        return sum(1 for m, p in self.calls if m == "POST" and p.endswith("/git/blobs"))

    def commit_elsewhere(self, files, message="Someone else's commit"):
        """Move the branch the way another person pushing would."""
        base = dict(self.trees[self.commits[self.head()]["tree"]])
        base.update({p: self._blob(b) for p, b in files.items()})
        self.refs[self.branch] = self._commit(self._tree(base), [self.head()], message)

    # ---------------------------------------------------------------- serving
    def start(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):                     # keep test output clean
                pass

            def _handle(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length)) if length else None
                code, body = fake.route(method, self.path,
                                        self.headers.get("Authorization", ""), payload)
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_PATCH(self):
                self._handle("PATCH")

        # Requests to this machine must not be sent to an outbound proxy.
        for var in ("NO_PROXY", "no_proxy"):
            have = [h for h in os.environ.get(var, "").split(",") if h]
            os.environ[var] = ",".join(have + [h for h in ("127.0.0.1", "localhost")
                                               if h not in have])
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    # ------------------------------------------------------------------ api
    def route(self, method, raw_path, auth, payload):
        with self.lock:
            path = urlparse(raw_path).path
            self.calls.append((method, path))
            if auth != f"Bearer {self.token}":
                return 401, {"message": "Bad credentials"}
            prefix = f"/repos/{self.repo}"
            if path != prefix and not path.startswith(prefix + "/"):
                return 404, {"message": "Not Found"}
            rest = path[len(prefix):].lstrip("/")

            if method == "GET":
                if rest == "":
                    return 200, {"full_name": self.repo,
                                 "permissions": {"pull": True, "push": self.account_push}}
                if rest.startswith("git/ref/heads/"):
                    branch = rest[len("git/ref/heads/"):]
                    if branch not in self.refs:
                        return 404, {"message": "Not Found"}
                    return 200, {"ref": f"refs/heads/{branch}",
                                 "object": {"sha": self.refs[branch], "type": "commit"}}
                if rest.startswith("git/commits/"):
                    sha = rest[len("git/commits/"):]
                    c = self.commits.get(sha)
                    if c is None:
                        return 404, {"message": "Not Found"}
                    return 200, {"sha": sha, "tree": {"sha": c["tree"]},
                                 "parents": [{"sha": p} for p in c["parents"]]}
                if rest.startswith("git/blobs/"):
                    sha = rest[len("git/blobs/"):]
                    if sha not in self.blobs:
                        return 404, {"message": "Not Found"}
                    return 200, {"sha": sha, "size": len(self.blobs[sha]),
                                 "encoding": "base64",
                                 "content": base64.b64encode(self.blobs[sha]).decode()}
                if rest.startswith("git/trees/"):
                    sha = rest[len("git/trees/"):]
                    t = self.trees.get(sha)
                    if t is None:
                        return 404, {"message": "Not Found"}
                    return 200, {"sha": sha, "truncated": False,
                                 "tree": [{"path": p, "mode": "100644", "type": "blob",
                                           "sha": s} for p, s in sorted(t.items())]}
                return 404, {"message": "Not Found"}

            if not self.push:
                return 403, {"message": "Resource not accessible by personal access token"}

            if method == "POST" and rest == "git/blobs":
                return 201, {"sha": self._blob(base64.b64decode(payload["content"]))}
            if method == "POST" and rest == "git/trees":
                base = dict(self.trees.get(payload.get("base_tree"), {}))
                for change in payload["tree"]:
                    if change.get("sha") is None:
                        base.pop(change["path"], None)
                    elif change["sha"] not in self.blobs:
                        return 422, {"message": "Invalid tree info"}
                    else:
                        base[change["path"]] = change["sha"]
                return 201, {"sha": self._tree(base)}
            if method == "POST" and rest == "git/commits":
                if payload["tree"] not in self.trees:
                    return 422, {"message": "Tree not found"}
                return 201, {"sha": self._commit(payload["tree"], payload["parents"],
                                                 payload["message"])}
            if method == "PATCH" and rest.startswith("git/refs/heads/"):
                branch = rest[len("git/refs/heads/"):]
                if self.on_patch:
                    hook, self.on_patch = self.on_patch, None
                    hook()
                if self.fail_patch:
                    self.fail_patch -= 1
                    return 422, {"message": "Update is not a fast forward"}
                new = payload["sha"]
                if new not in self.commits or branch not in self.refs:
                    return 422, {"message": "Reference update failed"}
                if not payload.get("force") and \
                        self.refs[branch] not in self.commits[new]["parents"]:
                    return 422, {"message": "Update is not a fast forward"}
                self.refs[branch] = new
                return 200, {"ref": f"refs/heads/{branch}", "object": {"sha": new}}
            return 404, {"message": "Not Found"}
