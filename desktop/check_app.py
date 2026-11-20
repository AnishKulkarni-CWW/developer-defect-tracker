#!/usr/bin/env python3
"""
A quick check that the app works, end to end, without opening a window.

    python desktop/check_app.py                  from a checkout or the build venv
    "QA Report Studio.exe" --selftest <file>     inside the finished program

It loads every library the app needs, reads every report and sheet in the
library, and builds a real PowerPoint deck and PDF for each market — the same
code paths the app uses when you press Generate. build_exe.bat runs it before
building (a setup file would only carry the same fault), and the packaged
program runs it to prove the files PyInstaller collected are complete.

Figures are checked against the rules every report must obey, not against
fixed numbers, so the check stays valid as months are added.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from pathlib import Path


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def run(out=print) -> bool:
    started = time.time()
    root = _root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "qars-selftest-mpl"))
    failures = []

    def check(label, ok, detail=""):
        out(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  --  {detail}" if detail else ""))
        if not ok:
            failures.append(label)

    def step(label, fn):
        try:
            return fn()
        except Exception as exc:                              # noqa: BLE001
            check(label, False, f"{type(exc).__name__}: {exc}")
            out(traceback.format_exc())
            return None

    out(f"QA Report Studio self-check - Python {sys.version.split()[0]}, "
        f"{'packaged' if getattr(sys, 'frozen', False) else 'from source'}")

    # ---- the libraries -------------------------------------------------
    def libraries():
        import streamlit
        import pandas
        import pyarrow
        import openpyxl
        import pptx
        import reportlab
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        pyarrow.array([1, 2, 3])                    # loads the Arrow shared libraries
        pptx.Presentation()                         # needs the bundled template
        fig, ax = plt.subplots(figsize=(1, 1))
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        plt.close(fig)
        check("libraries load", True,
              f"streamlit {streamlit.__version__}, pandas {pandas.__version__}, "
              f"pyarrow {pyarrow.__version__}, openpyxl {openpyxl.__version__}, "
              f"reportlab {reportlab.Version}, matplotlib {matplotlib.__version__}")
        static = Path(streamlit.__file__).parent / "static"
        if not static.is_dir():
            static = root / "streamlit" / "static"
        js = list((static / "static" / "js").glob("*.js"))
        check("Streamlit's frontend is complete", (static / "index.html").is_file()
              and len(js) >= 50, f"{len(js)} script files")

    step("libraries load", libraries)

    # ---- the app's own files ---------------------------------------------
    check("app.py is present", (root / "app.py").is_file(), str(root / "app.py"))
    check(".streamlit/config.toml is present",
          (root / ".streamlit" / "config.toml").is_file())
    check("no secrets.toml travels with the app",
          not (root / ".streamlit" / "secrets.toml").exists() or not getattr(sys, "frozen", False))

    # ---- the report library and the reports ------------------------------
    def reports():
        from qars import deck, library, metrics, normalize as nz, pdf, store
        rows = library.entries()
        check("report library found", bool(rows), f"{len(rows)} file(s) in {library.DIR}")
        unreadable = [e["file"] for e in rows if library.parse(e)[0] is None]
        check("every library file can be read", not unreadable, ", ".join(unreadable))
        db = store._empty_db()
        library.seed(db)
        settings = store._default_settings()
        settings["dev_aliases"], _ = nz.auto_merge_map(
            {r["dev_raw"] for m in store.MARKETS for r in db["tasks"][m] if r.get("dev_raw")}
            | {d["raw"] for m in store.MARKETS for b in db["monthly"][m]
               for d in b.get("developers", [])})
        for market in store.MARKETS:
            if not library.periods_for(market):
                continue
            sel = metrics.select(db, market, settings, {})
            tot = metrics.totals(sel)
            months = metrics.monthly_series(sel)
            check(f"{market}: totals add up",
                  tot["total_tasks"] == tot["error_tasks"] + tot["error_free"]
                  and tot["error_free"] == tot["no_error"] + tot["observations"]
                  and sum(r["total"] for r in months) == tot["total_tasks"],
                  f"{tot['total_tasks']:,} tasks, {len(months)} month(s), "
                  f"score {metrics.fmt_score(tot.get('score'))}")
            opts = {"market_label": market, "org": ""}
            deck_bytes = deck.build_deck(sel, opts)
            pdf_bytes = pdf.build_pdf(sel, opts)
            check(f"{market}: PowerPoint and PDF build",
                  len(deck_bytes) > 50_000 and pdf_bytes[:5] == b"%PDF-",
                  f"{len(deck_bytes) // 1024} KB deck, {len(pdf_bytes) // 1024} KB PDF")

    step("reports build", reports)

    out(f"{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' CHECK(S) FAILED'}"
        f" in {time.time() - started:.1f}s")
    return not failures


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
