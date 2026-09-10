"""
The single source of truth for every number in the product.

MANDATORY BUSINESS RULE — OBSERVATIONS
--------------------------------------
An observation is a task that is error free but carries a remark. It is a
SUBSET of the error-free tasks, never an extra bucket on top of them.

    Error-Free Tasks = No Error + Observation
    Total Tasks      = Error + Error-Free Tasks
                     = Error + No Error + Observation
    Quality Score    = Error-Free Tasks / Total Tasks * 100

`No Error` and `Observation` are DISJOINT counts: a task is exactly one of
Error, No Error, or Observation. Adding Error + No Error + Observation +
Error-Free would double-count, and nothing here ever does that.

    Total Tasks = 0  ->  Quality Score = N/A.  Never 100%.

CONSOLIDATED SCORE
------------------
Across several months the headline score is computed from the pooled counts,
not by averaging the monthly percentages:

    Overall Quality Score = SUM(Error-Free) / SUM(Total) * 100

The mean of the monthly scores is also reported, separately and clearly
labelled, as `average_monthly_score`.
"""

from __future__ import annotations

from . import normalize as nz

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_FULL = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]

NA = "N/A"


def month_label(y, m):
    return f"{MONTH_ABBR[m - 1]} {y}"


# ==========================================================================
# the calculation, in one place
# ==========================================================================
def compute(error, no_error, observation):
    """
    Canonical task maths. `no_error` and `observation` must be disjoint counts.

    Returns every derived figure the rest of the app is allowed to use, so no
    caller ever re-derives a total or a percentage on its own.
    """
    error = int(error or 0)
    no_error = int(no_error or 0)
    observation = int(observation or 0)
    error_free = no_error + observation
    total = error + error_free
    return {
        "error": error,
        "no_error": no_error,
        "observation": observation,
        "error_free": error_free,
        "total": total,
        "score": round(error_free / total * 100, 2) if total > 0 else None,
    }


def fmt_score(score):
    """Two decimal places everywhere, and N/A rather than a misleading 100%."""
    return NA if score is None else f"{score:.2f}%"


def consolidated_score(rows):
    """Pooled score across month rows. Never an average of percentages."""
    ef = sum(r["error_free"] for r in rows)
    tot = sum(r["total"] for r in rows)
    return round(ef / tot * 100, 2) if tot > 0 else None


def average_monthly_score(rows):
    """Mean of the monthly percentages. Reported alongside, never instead."""
    vals = [r["score"] for r in rows if r["score"] is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


# ==========================================================================
# selection
# ==========================================================================
class Selection:
    def __init__(self, market, tasks, blocks, settings, filters):
        self.market = market
        self.tasks = tasks
        self.blocks = blocks
        self.settings = settings
        self.filters = filters


def available_periods(db, market):
    out = set()
    for r in db["tasks"].get(market, []):
        out.add((r["year"], r["month"]))
    for b in db["monthly"].get(market, []):
        out.add((b["year"], b["month"]))
    return sorted(out)


def facet_values(db, market, settings):
    lookup = nz.build_alias_lookup(settings.get("dev_aliases"))
    tasks = db["tasks"].get(market, [])
    blocks = db["monthly"].get(market, [])

    devs, qas, cats, sevs, envs, weeks, days, files = (set() for _ in range(8))
    for r in tasks:
        devs.add(nz.resolve_name(r.get("dev_raw"), lookup))
        if r.get("qa_raw"):
            qas.add(nz.resolve_name(r.get("qa_raw"), lookup))
        if r.get("category"):
            cats.add(r["category"])
        if r.get("severity"):
            sevs.add(r["severity"])
        envs.add(r.get("env", nz.ENV_INTERNAL))
        if r.get("week"):
            weeks.add(r["week"])
        if r.get("day"):
            days.add(r["day"])
        if r.get("source_file"):
            files.add(r["source_file"])
    for b in blocks:
        for d in b.get("developers", []):
            devs.add(nz.resolve_name(d.get("raw") or d.get("name"), lookup))
        for c in b.get("categories", []):
            if c.get("category"):
                cats.add(c["category"])

    periods = available_periods(db, market)
    return {
        "years": sorted({y for y, _ in periods}),
        "periods": periods,
        "developers": sorted(devs),
        "qa_people": sorted(qas),
        "categories": _ordered(cats, nz.CATEGORY_ORDER),
        "severities": _ordered(sevs, nz.SEVERITY_ORDER),
        "environments": sorted(envs),
        "weeks": sorted(weeks),
        "days": sorted(days),
        "source_files": sorted(files),
        "has_tasks": bool(tasks),
        "has_blocks": bool(blocks),
        "task_months": sorted({(r["year"], r["month"]) for r in tasks}),
        "block_months": sorted({(b["year"], b["month"]) for b in blocks}),
    }


def _ordered(values, canonical):
    return [c for c in canonical if c in values] + sorted(v for v in values if v not in canonical)


def select(db, market, settings, filters):
    """Apply filters and return a Selection. An empty filter means no restriction."""
    lookup = nz.build_alias_lookup(settings.get("dev_aliases"))
    f = filters or {}
    want = {k: set(f.get(k) or []) for k in
            ("periods", "developers", "qa_people", "categories", "severities",
             "environments", "weeks", "days")}

    tasks = []
    for r in db["tasks"].get(market, []):
        if want["periods"] and (r["year"], r["month"]) not in want["periods"]:
            continue
        if want["weeks"] and r.get("week") not in want["weeks"]:
            continue
        if want["days"] and r.get("day") not in want["days"]:
            continue
        if want["environments"] and r.get("env") not in want["environments"]:
            continue
        dev = nz.resolve_name(r.get("dev_raw"), lookup)
        if want["developers"] and dev not in want["developers"]:
            continue
        qa = nz.resolve_name(r.get("qa_raw"), lookup) if r.get("qa_raw") else "(Unassigned)"
        if want["qa_people"] and qa not in want["qa_people"]:
            continue
        # Category and severity describe defects. Applying them to a clean task
        # would delete the denominator and inflate every score, so they only
        # ever narrow the Error rows.
        if r["status"] == nz.STATUS_ERR:
            if want["categories"] and r.get("category") not in want["categories"]:
                continue
            if want["severities"] and r.get("severity") not in want["severities"]:
                continue
        rr = dict(r)
        rr["dev"] = dev
        rr["qa"] = qa
        tasks.append(rr)

    task_months = {(r["year"], r["month"]) for r in tasks}
    month_level_only = not any(want[k] for k in
                               ("developers", "qa_people", "categories",
                                "severities", "environments", "weeks", "days"))
    blocks = []
    if f.get("include_blocks", True) and month_level_only:
        for b in db["monthly"].get(market, []):
            if want["periods"] and (b["year"], b["month"]) not in want["periods"]:
                continue
            if (b["year"], b["month"]) in task_months:
                continue                                   # Excel detail is primary
            blocks.append(b)

    return Selection(market, tasks, blocks, settings, f)


# ==========================================================================
# aggregation
# ==========================================================================
def monthly_series(sel):
    acc = {}
    for r in sel.tasks:
        a = acc.setdefault((r["year"], r["month"]), _zero())
        _bump(a, r["status"])
    for b in sel.blocks:
        a = acc.setdefault((b["year"], b["month"]), _zero())
        a["error"] += b.get("error", 0)
        a["no_error"] += b.get("no_error", 0)
        a["observation"] += b.get("observation", 0)
        a["from_block"] = True

    rows = []
    for (y, m), a in sorted(acc.items()):
        c = compute(a["error"], a["no_error"], a["observation"])
        c.update({"year": y, "month": m, "label": month_label(y, m),
                  "month_name": MONTH_FULL[m - 1],
                  "source": "summary" if a.get("from_block") else "detail"})
        rows.append(c)
    return rows


def totals(sel):
    rows = monthly_series(sel)
    agg = compute(sum(r["error"] for r in rows),
                  sum(r["no_error"] for r in rows),
                  sum(r["observation"] for r in rows))

    internal = external = 0
    for r in sel.tasks:
        if r["status"] == nz.STATUS_ERR:
            if r.get("env") == nz.ENV_EXTERNAL:
                external += 1
            else:
                internal += 1
    for b in sel.blocks:
        for c in b.get("categories", []):
            internal += c.get("internal", 0)
            external += c.get("external", 0)
    # Reconcile against the authoritative defect count. Category tables can be
    # missing (top up) or, in a hand-built deck, over-count (scale back), and
    # "40 internal + 6 external out of 43 defects" on a slide is indefensible.
    span = internal + external
    if span < agg["error"]:
        internal += agg["error"] - span
    elif span > agg["error"] and span:
        keep_ext = min(external, agg["error"])
        external = keep_ext
        internal = max(agg["error"] - keep_ext, 0)

    devs = developer_table(sel)
    watch = float(sel.settings.get("watch_score", 90.0))
    below = [d for d in devs if d["score"] is not None and d["score"] < watch]
    crit = sum(1 for r in sel.tasks
               if r["status"] == nz.STATUS_ERR and r.get("severity") == "Critical")

    out = dict(agg)
    out.update({
        "total_tasks": agg["total"],
        "error_tasks": agg["error"],
        "observations": agg["observation"],
        "internal": internal,
        "external": external,
        "internal_pct": round(internal / agg["error"] * 100, 2) if agg["error"] else 0.0,
        "external_pct": round(external / agg["error"] * 100, 2) if agg["error"] else 0.0,
        "developers": len(devs),
        "below_target": len(below),
        "below_names": [d["name"] for d in below],
        "critical": crit,
        "months": len(rows),
        "period_label": period_label(rows),
        "avg_monthly_score": average_monthly_score(rows),
        "hours": round(sum(r.get("hours") or 0 for r in sel.tasks), 1),
    })
    return out


def period_label(rows):
    if not rows:
        return "No period"
    a, b = rows[0], rows[-1]
    if a["year"] == b["year"]:
        if a["month"] == b["month"]:
            return f"{MONTH_FULL[a['month'] - 1]} {a['year']}"
        return f"{MONTH_ABBR[a['month'] - 1]} \u2013 {MONTH_ABBR[b['month'] - 1]} {a['year']}"
    return f"{MONTH_ABBR[a['month'] - 1]} {a['year']} \u2013 {MONTH_ABBR[b['month'] - 1]} {b['year']}"


def developer_table(sel, month=None):
    acc = {}
    for r in sel.tasks:
        if month and (r["year"], r["month"]) != month:
            continue
        _bump(acc.setdefault(r["dev"], _zero()), r["status"])
    lookup = nz.build_alias_lookup(sel.settings.get("dev_aliases"))
    for b in sel.blocks:
        if month and (b["year"], b["month"]) != month:
            continue
        for d in b.get("developers", []):
            a = acc.setdefault(nz.resolve_name(d.get("raw") or d.get("name"), lookup), _zero())
            a["error"] += d.get("error", 0)
            a["no_error"] += d.get("no_error", 0)
            a["observation"] += d.get("observation", 0)

    rows = []
    for name, a in acc.items():
        c = compute(a["error"], a["no_error"], a["observation"])
        if c["total"] == 0:
            continue
        c["name"] = name
        rows.append(c)
    rows.sort(key=lambda r: (r["score"] if r["score"] is not None else 999, -r["total"]))
    return rows


def category_table(sel, month=None):
    acc = {}
    for r in sel.tasks:
        if r["status"] != nz.STATUS_ERR:
            continue
        if month and (r["year"], r["month"]) != month:
            continue
        a = acc.setdefault(r.get("category") or "Other", {"internal": 0, "external": 0})
        a["external" if r.get("env") == nz.ENV_EXTERNAL else "internal"] += 1
    for b in sel.blocks:
        if month and (b["year"], b["month"]) != month:
            continue
        for c in b.get("categories", []):
            a = acc.setdefault(c.get("category") or "Other", {"internal": 0, "external": 0})
            a["internal"] += c.get("internal", 0)
            a["external"] += c.get("external", 0)

    grand = sum(v["internal"] + v["external"] for v in acc.values())
    rows = [{"category": k, "internal": v["internal"], "external": v["external"],
             "total": v["internal"] + v["external"],
             "pct": round((v["internal"] + v["external"]) / grand * 100, 2) if grand else 0.0}
            for k, v in acc.items()]
    rows.sort(key=lambda r: (-r["total"], r["category"]))
    return rows


def severity_table(sel):
    acc = {}
    for r in sel.tasks:
        if r["status"] == nz.STATUS_ERR:
            k = r.get("severity") or "Unspecified"
            acc[k] = acc.get(k, 0) + 1
    known = [{"severity": s, "count": acc[s]} for s in nz.SEVERITY_ORDER if s in acc]
    extra = [{"severity": s, "count": c} for s, c in sorted(acc.items())
             if s not in nz.SEVERITY_ORDER]
    return known + extra


def aging_table(sel):
    """
    Defect age in days, measured from when each defect was logged to the latest
    audit date in the selection.

    The audit sheets carry no resolution date, so this shows how long ago
    defects were raised — NOT how long they stayed open. Every surface that
    renders it says so, because an aging chart that silently means something
    else is worse than no aging chart at all.

    Returns (rows, reference_date).
    """
    from datetime import date as _date
    dates = [r["date"] for r in sel.tasks if r.get("date")]
    if not dates:
        return [], None
    ry, rm, rd = (int(x) for x in max(dates).split("-"))
    ref_d = _date(ry, rm, rd)

    buckets = [("0\u20137 days", 0, 7), ("8\u201315 days", 8, 15), ("16\u201330 days", 16, 30),
               ("31\u201360 days", 31, 60), ("60+ days", 61, 10 ** 6)]
    acc = {b[0]: 0 for b in buckets}
    for r in sel.tasks:
        if r["status"] != nz.STATUS_ERR or not r.get("date"):
            continue
        y, m, d = (int(x) for x in r["date"].split("-"))
        age = (ref_d - _date(y, m, d)).days
        for name, lo, hi in buckets:
            if lo <= age <= hi:
                acc[name] += 1
                break
    total = sum(acc.values())
    rows = [{"bucket": b[0], "count": acc[b[0]],
             "pct": round(acc[b[0]] / total * 100, 2) if total else 0.0} for b in buckets]
    return rows, max(dates)


def critical_defects(sel, limit=40):
    rows = [r for r in sel.tasks
            if r["status"] == nz.STATUS_ERR and r.get("severity") == "Critical"]
    rows.sort(key=lambda r: (r.get("date") or "", r.get("dev") or ""))
    return rows[:limit], len(rows)


def qa_table(sel):
    acc = {}
    for r in sel.tasks:
        _bump(acc.setdefault(r.get("qa") or "(Unassigned)", _zero()), r["status"])
    rows = []
    for name, a in acc.items():
        c = compute(a["error"], a["no_error"], a["observation"])
        rows.append({"name": name, "audited": c["total"], "found": c["error"],
                     "observation": c["observation"],
                     "catch_rate": round(c["error"] / c["total"] * 100, 2) if c["total"] else 0.0})
    rows.sort(key=lambda r: -r["audited"])
    return rows


def weekly_series(sel):
    acc = {}
    for r in sel.tasks:
        if r.get("week") is None:
            continue
        _bump(acc.setdefault((r["year"], r["week"]), _zero()), r["status"])
    rows = []
    for (y, w), a in sorted(acc.items()):
        c = compute(a["error"], a["no_error"], a["observation"])
        c.update({"year": y, "week": w, "label": f"W{w}"})
        rows.append(c)
    return rows


def daily_series(sel):
    acc = {}
    for r in sel.tasks:
        if r.get("date"):
            _bump(acc.setdefault(r["date"], _zero()), r["status"])
    rows = []
    for d, a in sorted(acc.items()):
        c = compute(a["error"], a["no_error"], a["observation"])
        c.update({"date": d, "label": d[-5:]})
        rows.append(c)
    return rows


def top_performer_threshold(sel, rows=None):
    """
    Minimum task count a developer needs before they can appear on the podium.

    A perfect score off three tasks is not the same achievement as 149 clean
    tasks out of 151. The bar is a share of the busiest developer's workload,
    which scales with the size of the period instead of needing a magic number,
    and it is shown on the slide so the ranking is never a black box.

    `top_min_share` in settings tunes it (default 0.17, which reproduces the
    podium in the client's own Jan-Jun C3 deck).
    """
    rows = rows if rows is not None else [d for d in developer_table(sel)
                                          if d["score"] is not None]
    if not rows:
        return 0
    share = float(sel.settings.get("top_min_share", 0.17))
    floor = int(sel.settings.get("top_min_tasks", 3))
    busiest = max(d["total"] for d in rows)
    return max(floor, int(round(busiest * share)))


def top_developers(sel, n=3, min_tasks=None):
    """Podium, worthiest first. Returns (rows, threshold_actually_used)."""
    rows = [d for d in developer_table(sel) if d["score"] is not None]
    if not rows:
        return [], 0
    bar = min_tasks if min_tasks is not None else top_performer_threshold(sel, rows)
    for candidate in (bar, max(2, bar // 2), 1):
        pool = [d for d in rows if d["total"] >= candidate]
        if len(pool) >= n or candidate == 1:
            pool.sort(key=lambda r: (-r["score"], -r["total"], r["name"]))
            return pool[:n], candidate
    return [], bar


# ==========================================================================
# narrative
# ==========================================================================
def insights(sel):
    t = totals(sel)
    devs = developer_table(sel)
    cats = category_table(sel)
    target = float(sel.settings.get("target_score", 95.0))
    watch = float(sel.settings.get("watch_score", 90.0))
    out = []

    if t["score"] is not None:
        out.append({"icon": "target", "value": fmt_score(t["score"]),
                    "text": f"overall quality score across {t['period_label']}."})
    if t["error_tasks"]:
        out.append({"icon": "shield", "value": f"{t['internal_pct']:.2f}%",
                    "text": "of defects were caught internally, before release."})
    if devs:
        at_target = sum(1 for d in devs if d["score"] is not None and d["score"] >= target)
        out.append({"icon": "chart", "value": str(at_target),
                    "text": f"of {len(devs)} developers scored {target:.0f}% or higher."})
        out.append({"icon": "people", "value": str(t["below_target"]),
                    "text": f"developers sit below the {watch:.0f}% benchmark."})
    if t["total_tasks"]:
        out.append({"icon": "check", "value": f"{t['error_free']}",
                    "text": f"of {t['total_tasks']} tasks were error free, including "
                            f"{t['observations']} with an observation."})
    if cats:
        out.append({"icon": "bug", "value": f"{cats[0]['pct']:.2f}%",
                    "text": f"of defects came from {cats[0]['category'].lower()} issues."})
    return out[:6]


def recommendations(sel):
    """
    Rule-based actions derived from the selection. No model and no network —
    just thresholds applied to the numbers already on the page.
    """
    t = totals(sel)
    rows = monthly_series(sel)
    cats = category_table(sel)
    sev = {s["severity"]: s["count"] for s in severity_table(sel)}
    target = float(sel.settings.get("target_score", 95.0))
    watch = float(sel.settings.get("watch_score", 90.0))
    out = []

    if t["score"] is None:
        return [{"icon": "clipboard", "title": "No tasks in this selection",
                 "text": "Widen the filters, or import the audit sheet for this period."}]

    if cats and cats[0]["pct"] >= 40:
        out.append({"icon": "bug", "title": f"Target {cats[0]['category'].lower()} defects",
                    "text": f"{cats[0]['category']} accounts for {cats[0]['pct']:.2f}% of all "
                            f"defects ({cats[0]['total']} of {t['error_tasks']}). A focused "
                            "checklist for this one category would move the score more than "
                            "any other single action."})
    if t["external"] > 0:
        out.append({"icon": "globe", "title": "Close the external leakage",
                    "text": f"{t['external']} defect(s) ({t['external_pct']:.2f}%) were found on "
                            "live links rather than in test, so they reached the client. "
                            "Tighten the pre-release check for the categories involved."})
    if sev.get("Critical"):
        out.append({"icon": "shield", "title": f"{sev['Critical']} critical defect(s) logged",
                    "text": "Review each one at the next QA huddle and confirm the root cause "
                            "was addressed, not just the symptom."})
    if t["below_target"]:
        names = ", ".join(t["below_names"][:4])
        more = f" and {t['below_target'] - 4} other(s)" if t["below_target"] > 4 else ""
        out.append({"icon": "people", "title": f"Coach {t['below_target']} developer(s)",
                    "text": f"{names}{more} scored below the {watch:.0f}% benchmark. Pair them "
                            "with a reviewer on the defect category they hit most often."})
    if len(rows) > 1:
        first, last = rows[0], rows[-1]
        if first["score"] is not None and last["score"] is not None:
            delta = last["score"] - first["score"]
            if delta <= -1:
                out.append({"icon": "down", "title": "Quality is trending down",
                            "text": f"The score fell {abs(delta):.2f} points from "
                                    f"{first['label']} ({fmt_score(first['score'])}) to "
                                    f"{last['label']} ({fmt_score(last['score'])}). Check whether "
                                    "workload or team composition changed over that period."})
            elif delta >= 1:
                out.append({"icon": "up", "title": "Quality is trending up",
                            "text": f"The score rose {delta:.2f} points from {first['label']} to "
                                    f"{last['label']}. Capture what changed so it holds."})
    if t["observations"]:
        pct = t["observations"] / t["total_tasks"] * 100
        out.append({"icon": "clipboard", "title": f"{t['observations']} observation(s) recorded",
                    "text": f"{pct:.2f}% of tasks were error free but carried a remark. These "
                            "count as passes, but a rising trend often precedes real defects."})
    if t["score"] >= target and not out:
        out.append({"icon": "check", "title": "Holding above target",
                    "text": f"The period closed at {fmt_score(t['score'])}, at or above the "
                            f"{target:.0f}% target. Keep the current review cadence."})
    return out[:6]


# ==========================================================================
# data quality
# ==========================================================================
def data_warnings(db, market, settings):
    """Problems worth surfacing before anyone builds a report."""
    warn = []
    tasks = db["tasks"].get(market, [])
    lookup = nz.build_alias_lookup(settings.get("dev_aliases"))

    names = {r.get("dev_raw") for r in tasks if r.get("dev_raw")}
    for b in db["monthly"].get(market, []):
        for d in b.get("developers", []):
            if d.get("raw"):
                names.add(d["raw"])
    confident, ambiguous = nz.classify_name_groups(names)
    unmerged = {c: m for c, m in confident.items()
                if len({nz.resolve_name(x, lookup) for x in m}) > 1}
    if unmerged:
        warn.append({"kind": "aliases", "severity": "info",
                     "text": f"{len(unmerged)} name variant(s) have not been merged yet. "
                             "Open the Data manager tab and press Merge all.",
                     "detail": unmerged})
    still = {c: v for c, v in ambiguous.items()
             if len({nz.resolve_name(x, lookup) for x in v["members"]}) > 1}
    if still:
        warn.append({"kind": "ambiguous", "severity": "warning",
                     "text": f"{len(still)} developer name(s) are genuinely ambiguous and "
                             "were NOT merged automatically.",
                     "detail": still})

    no_cat = sum(1 for r in tasks if r["status"] == nz.STATUS_ERR and not r.get("category"))
    if no_cat:
        warn.append({"kind": "category", "severity": "info",
                     "text": f"{no_cat} defect row(s) have no Error Type and are grouped "
                             "under 'Other'."})

    years = {}
    for r in tasks:
        years[r["year"]] = years.get(r["year"], 0) + 1
    if len(years) > 1:
        dom = max(years, key=years.get)
        strays = {y: c for y, c in years.items() if y != dom}
        if any(c <= 5 for c in strays.values()):
            warn.append({"kind": "dates", "severity": "warning",
                         "text": f"Some rows are dated outside {dom}: "
                                 + ", ".join(f"{c} row(s) in {y}" for y, c in sorted(strays.items()))
                                 + ". These are usually typos in the audit sheet."})

    # Excel vs PowerPoint disagreement on the same month.
    for b in db["monthly"].get(market, []):
        ym = (b["year"], b["month"])
        rows = [r for r in tasks if (r["year"], r["month"]) == ym]
        if not rows:
            continue
        a = _zero()
        for r in rows:
            _bump(a, r["status"])
        xl = compute(a["error"], a["no_error"], a["observation"])
        pp = compute(b.get("error", 0), b.get("no_error", 0), b.get("observation", 0))
        if xl["score"] is None or pp["score"] is None:
            continue
        if abs(xl["score"] - pp["score"]) >= 0.01 or xl["total"] != pp["total"]:
            warn.append({
                "kind": "discrepancy", "severity": "warning",
                "text": f"Source discrepancy detected for {month_label(*ym)} — "
                        f"Excel quality score {fmt_score(xl['score'])} "
                        f"({xl['error_free']}/{xl['total']} tasks) vs PowerPoint "
                        f"{fmt_score(pp['score'])} ({pp['error_free']}/{pp['total']}). "
                        "Excel has been selected as the primary calculation source. "
                        "Please review the discrepancy.",
                "detail": {"period": month_label(*ym), "excel": xl, "pptx": pp}})
    return warn


# ==========================================================================
# helpers
# ==========================================================================
def _zero():
    return {"error": 0, "no_error": 0, "observation": 0}


def _bump(acc, status):
    if status == nz.STATUS_ERR:
        acc["error"] += 1
    elif status == nz.STATUS_OK:
        acc["no_error"] += 1
    elif status == nz.STATUS_OBS:
        acc["observation"] += 1
