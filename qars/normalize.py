"""
Cleaning layer for the raw audit sheets.

The real sheets contain the same developer under four spellings ("Amol",
"AMOL LAXMAN DOHALE", "Amol Dohale", plus a bare e-mail address), and defect
categories that drift month to month ("Design Related" / "Design layout
Related"). Everything downstream assumes clean keys, so all the fuzz is
absorbed here and nowhere else.
"""

from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------
STATUS_OK = "No Error"
STATUS_ERR = "Error"
STATUS_OBS = "Observation"

_STATUS_MAP = {
    "first time correct": STATUS_OK,
    "ftc": STATUS_OK,
    "no error": STATUS_OK,
    "noerror": STATUS_OK,
    "pass": STATUS_OK,
    "passed": STATUS_OK,
    "correct": STATUS_OK,
    "ok": STATUS_OK,
    "error": STATUS_ERR,
    "errors": STATUS_ERR,
    "fail": STATUS_ERR,
    "failed": STATUS_ERR,
    "defect": STATUS_ERR,
    "observation": STATUS_OBS,
    "observations": STATUS_OBS,
    "obs": STATUS_OBS,
}


def norm_status(value):
    key = _clean(value).lower()
    if not key:
        return None
    if key in _STATUS_MAP:
        return _STATUS_MAP[key]
    if "observ" in key:
        return STATUS_OBS
    if "error" in key or "fail" in key or "defect" in key:
        return STATUS_ERR
    if "correct" in key or "pass" in key:
        return STATUS_OK
    return None


# --------------------------------------------------------------------------
# Environment  ->  Internal / External
# --------------------------------------------------------------------------
ENV_INTERNAL = "Internal"
ENV_EXTERNAL = "External"


def norm_env(value):
    key = _clean(value).lower()
    if not key:
        return ENV_INTERNAL
    if key.startswith("live") or "external" in key or "prod" in key:
        return ENV_EXTERNAL
    return ENV_INTERNAL


# --------------------------------------------------------------------------
# Defect categories
# --------------------------------------------------------------------------
CATEGORY_ORDER = [
    "Content Related",
    "Design Related",
    "Image Related",
    "Video Related",
    "Redirect Links",
    "Navigation Related",
    "Functionality",
    "LinkBuilder",
    "EDM",
    "Multiple Issues",
]

_CATEGORY_RULES = [
    (("content",), "Content Related"),
    (("design", "layout"), "Design Related"),
    (("image", "images", "img"), "Image Related"),
    (("video",), "Video Related"),
    (("redirect", "redirected"), "Redirect Links"),
    (("navigation", "nav"), "Navigation Related"),
    (("functional", "functionality", "broken"), "Functionality"),
    (("linkbuilder", "link builder"), "LinkBuilder"),
    (("edm",), "EDM"),
    (("multiple",), "Multiple Issues"),
]


def norm_category(value):
    key = _clean(value).lower()
    if not key:
        return None
    for needles, canon in _CATEGORY_RULES:
        if any(n in key for n in needles):
            return canon
    return _titlecase(key)


# --------------------------------------------------------------------------
# Severity
# --------------------------------------------------------------------------
SEVERITY_ORDER = ["Critical", "Major", "Minor", "Cosmetic", "Unspecified"]


def norm_severity(value):
    key = _clean(value).lower()
    if not key:
        return "Unspecified"
    for s in SEVERITY_ORDER:
        if s.lower() in key:
            return s
    if "high" in key or "blocker" in key:
        return "Critical"
    if "med" in key:
        return "Major"
    if "low" in key or "trivial" in key:
        return "Minor"
    return "Unspecified"


# --------------------------------------------------------------------------
# Developer / QA names
# --------------------------------------------------------------------------
_NAME_NOISE = re.compile(r"[^a-z\s]")


def name_key(raw):
    """
    Collapse a raw name to a comparison key.

    'sandeep.j@craftww.com' -> 'sandeep j'
    'AMOL LAXMAN DOHALE'    -> 'amol laxman dohale'
    """
    s = _clean(raw)
    if not s:
        return ""
    if "@" in s:                       # e-mail -> local part, dots become spaces
        s = s.split("@", 1)[0].replace(".", " ").replace("_", " ")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _NAME_NOISE.sub(" ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def display_name(raw):
    """
    Title-case a raw name: 'AMOL LAXMAN DOHALE' -> 'Amol Laxman Dohale'.

    `keep_acronyms` is off here: the acronym rule exists for category labels
    like EDM, and applied to people it leaves 'Neha LAL' and 'DAN Dsouza'
    shouting in the middle of a report.
    """
    s = _clean(raw)
    if "@" in s:
        s = s.split("@", 1)[0].replace(".", " ").replace("_", " ")
    return _titlecase(s, keep_acronyms=False)


def suggest_alias_groups(raw_names):
    """Compatibility wrapper. See `classify_name_groups` for the real logic."""
    confident, ambiguous = classify_name_groups(raw_names)
    out = dict(confident)
    for canon, info in ambiguous.items():
        out[canon] = info["members"]
    return out


def _shares_full_token(a, b):
    """
    True when the two token sets share at least one whole word.

    Initials alone are not enough. Without this, "Komal" would match
    "Kapil K" (the lone "k" swallowing anything starting with k) and two
    different people would be merged into one.
    """
    real_a = {t for t in a if len(t) >= 3}
    real_b = {t for t in b if len(t) >= 3}
    return bool(real_a & real_b)


def classify_name_groups(raw_names):
    """
    Decide which spellings are safely the same person and which are not.

    Returns (confident, ambiguous).

    confident  {canonical: [raw, ...]}
        Applied automatically. A spelling joins a group when its tokens are
        covered by the group's fullest name (initials allowed), AND the two
        share at least one whole word, AND only one group could possibly claim
        it. "Kapil K" -> "Kapil Kumar" and "Amol Dohale" -> "Amol Laxman
        Dohale" both qualify.

    ambiguous  {label: {"members", "short", "rivals", "reason"}}
        Raised as a warning instead. "Amol" on its own, when both
        "Amol Laxman Dohale" and "Amol Gaikwad" exist, could be either person;
        merging it would silently move one developer's tasks onto another.
    """
    entries, seen = [], set()
    for raw in raw_names:
        k = name_key(raw)
        if k and raw not in seen:
            seen.add(raw)
            entries.append({"raw": raw, "key": k, "toks": set(k.split()),
                            "n": len(k.split())})
    entries.sort(key=lambda e: (-e["n"], -len(e["key"]), e["raw"]))

    # ---- 1. cluster the multi-word names into components -----------------
    fulls = [e for e in entries if e["n"] >= 2]
    parent = {e["raw"]: e["raw"] for e in fulls}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, a in enumerate(fulls):
        for b in fulls[i + 1:]:
            if not _shares_full_token(a["toks"], b["toks"]):
                continue
            small, big = ((a["toks"], b["toks"]) if a["n"] <= b["n"]
                          else (b["toks"], a["toks"]))
            if _covered_by(small, big):
                union(a["raw"], b["raw"])

    comps = {}
    for e in fulls:
        comps.setdefault(find(e["raw"]), []).append(e)

    # Canonical spelling of a component: the fullest, then the longest.
    comp_info = {}
    for root, members in comps.items():
        best = max(members, key=lambda e: (e["n"], len(e["key"])))
        toks = set()
        for m in members:
            toks |= m["toks"]
        comp_info[root] = {"canon": best["raw"], "toks": toks,
                           "members": [m["raw"] for m in members]}

    # ---- 2. attach the remaining spellings -------------------------------
    confident, ambiguous = {}, {}
    singles = [e for e in entries if e["n"] < 2]
    for e in singles:
        hosts = [root for root, info in comp_info.items()
                 if _shares_full_token(e["toks"], info["toks"])
                 and _covered_by(e["toks"], info["toks"])]
        if len(hosts) == 1:
            comp_info[hosts[0]]["members"].append(e["raw"])
        elif len(hosts) > 1:
            rivals = sorted(comp_info[h]["canon"] for h in hosts)
            ambiguous[display_name(e["raw"])] = {
                "members": sorted([e["raw"]] + rivals),
                "short": e["raw"],
                "rivals": rivals,
                "reason": (f"\u201c{e['raw']}\u201d could be any of "
                           + ", ".join(rivals)
                           + ". Merging it automatically could move one person\u2019s "
                             "tasks onto another, so it is left for you to decide."),
            }

    for info in comp_info.values():
        members = sorted(set(info["members"]))
        if len(members) > 1:
            confident[display_name(info["canon"])] = members
    return confident, ambiguous


def auto_merge_map(raw_names, existing=None):
    """
    Build the alias map to apply without asking.

    Only confident groups are included; ambiguous ones come back separately so
    they can be raised as a warning rather than quietly applied.
    """
    confident, ambiguous = classify_name_groups(raw_names)
    merged = dict(existing or {})
    for canon, members in confident.items():
        merged[canon] = sorted(set(merged.get(canon, [])) | set(members))
    return merged, ambiguous


def _tok_match(tok, pool):
    """A one-letter token stands in for any token starting with that letter."""
    if tok in pool:
        return True
    if len(tok) == 1:
        return any(p.startswith(tok) for p in pool)
    return any(len(p) == 1 and tok.startswith(p) for p in pool)


def _covered_by(small, big):
    """Every token of `small` has a match in `big`, allowing initials."""
    return all(_tok_match(t, big) for t in small)


def build_alias_lookup(dev_aliases):
    """{canonical: [raw,...]} -> {name_key(raw): canonical} for O(1) resolution."""
    lookup = {}
    for canon, raws in (dev_aliases or {}).items():
        for raw in list(raws) + [canon]:
            k = name_key(raw)
            if k:
                lookup[k] = canon
    return lookup


def resolve_name(raw, lookup):
    k = name_key(raw)
    if not k:
        return "(Unassigned)"
    return lookup.get(k) or display_name(raw)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _clean(v):
    if v is None:
        return ""
    s = str(v).replace("\xa0", " ").strip()
    return "" if s.lower() in {"nan", "none", "nat", "-", "na", "n/a"} else s


_SMALL = {"of", "and", "the", "in", "for"}


def _titlecase(s, keep_acronyms=True):
    parts = [p for p in re.split(r"\s+", s.strip()) if p]
    out = []
    for i, p in enumerate(parts):
        low = p.lower()
        if i and low in _SMALL:
            out.append(low)
        elif keep_acronyms and len(p) <= 3 and p.isupper():
            out.append(p)            # keep acronyms: EDM, C3, OOH
        else:
            out.append(low[:1].upper() + low[1:])
    return " ".join(out)
