# QA Report Studio

Turns your monthly QA audit sheets into a branded PowerPoint and PDF quality
report for **BMW India, C3 and Japan** — completely offline, with no API keys,
no accounts, no usage limits and no external database.

---

## Contents

1. [Installation](#1-installation)
2. [Running the frontend](#2-running-the-frontend)
3. [Running the backend](#3-running-the-backend)
4. [Environment variables](#4-environment-variables)
5. [Using the application](#5-using-the-application)
6. [Generating reports](#6-generating-reports)
7. [How the quality score works](#7-how-the-quality-score-works)
8. [Running the tests](#8-running-the-tests)
9. [Troubleshooting](#9-troubleshooting)
10. [Deploying to Streamlit Community Cloud](#10-deploying-to-streamlit-community-cloud)
11. [Converting to a .exe later](#11-converting-to-a-exe-later)
12. [Project structure](#12-project-structure)

---

## 1. Installation

**You need Python 3.10 or newer.** If it is not installed, download it from
[python.org/downloads](https://www.python.org/downloads/) and — this part
matters — tick **"Add Python to PATH"** on the first screen of the installer.

To check what you have, open a terminal (Windows: press Start, type `cmd`,
press Enter) and run:

```
python --version
```

You should see `Python 3.10.x` or higher.

### The easy way (recommended)

Unzip the folder somewhere you can write to — your Documents folder is ideal,
**not** `C:\Program Files`. Then:

- **Windows** — double-click **`run_windows.bat`**
- **macOS / Linux** — open a terminal in the folder and run:

  ```
  chmod +x run_mac_linux.sh
  ./run_mac_linux.sh
  ```

The first run creates a private environment inside the folder and installs the
dependencies. This takes a minute or two and **needs internet once**. Every run
after that starts in seconds and needs no internet at all.

### The manual way (exact commands)

**Windows:**

```
cd path\to\QA_Report_Studio
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**macOS / Linux:**

```
cd path/to/QA_Report_Studio
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Optional: support for old .xls files

`.xlsx`, `.xlsm` and `.csv` work out of the box. If you also need to open
old-format `.xls` files:

```
pip install xlrd
```

If you skip this, the app tells you plainly when it meets an `.xls` file and
suggests re-saving it as `.xlsx`, which needs no extra install.

---

## 2. Running the frontend

**Exact command** (with the environment activated, as above):

```
streamlit run app.py
```

Your browser opens at `http://localhost:8501`. To stop the app, press
`Ctrl + C` in the terminal, or close the console window the launcher opened.

To run on a different port:

```
streamlit run app.py --server.port 8502
```

---

## 3. Running the backend

**There is no backend to run.** This is deliberate, not an omission.

QA Report Studio is a single-process desktop application. The Streamlit process
does everything: reading your Excel files, calculating every figure, drawing the
charts and building the PPTX and PDF. There is no server to start, no database
to install, no connection string to configure and no port to open.

Your data lives in two plain JSON files inside the `data` folder:

```
data/database.json    every task row and every imported month
data/settings.json    benchmarks, name merges, report defaults
data/backups/         automatic snapshots taken before anything destructive
```

This is what makes the offline requirement achievable, and it is why the app can
later be frozen into a single `.exe` that a colleague can run by double-clicking.

If you want your data on another PC, copy `data/database.json` across. That is
the whole migration.

---

## 4. Environment variables

**None are required.** The application reads no environment variables and needs
no `.env` file. If you were expecting to configure API keys, database URLs or
service endpoints — there are none, because the app calls nothing external.

Everything that would normally be an environment variable is either in the
sidebar of the app (organisation name, prepared-by, score benchmarks) or in
`.streamlit/config.toml` (theme and server settings).

The only variables that have any effect are Streamlit's own optional ones, which
you will almost certainly never need:

| Variable | Effect | Default here |
|---|---|---|
| `STREAMLIT_SERVER_PORT` | Which port to serve on | `8501` |
| `STREAMLIT_SERVER_HEADLESS` | Do not auto-open a browser | `true` |
| `STREAMLIT_BROWSER_GATHER_USAGE_STATS` | Telemetry | `false` |

Setting one, if you ever need to:

```
# Windows
set STREAMLIT_SERVER_PORT=8502 && streamlit run app.py

# macOS / Linux
STREAMLIT_SERVER_PORT=8502 streamlit run app.py
```

---

## 5. Using the application

The app walks through seven visible steps, shown as a progress strip at the top
of each market tab.

### Step 1 — Upload data

Pick a market tab (**India**, **C3** or **Japan**). Each market keeps its own
data and its own reports.

Under **Add data**, you can upload two different things:

- **Audit sheet** (`.xlsx`, `.xlsm`, `.xls`, `.csv`) — the monthly QA audit log.
  This is the important one: it gives task-level detail, so every filter and
  every chart works. You can upload several months at once.
- **Existing PowerPoint report** (`.pptx`) — *optional.* A deck you already
  issued. The app recovers the monthly totals from it, so months you reported
  before this tool existed still appear in a full-year report without you
  re-keying anything.

Press **Read file(s)**. Nothing is saved yet.

### Step 2 — Review mapping

For each file the app shows which sheet it used, which row it found the header
on, and which columns it recognised. It also shows **how it worked out the
reporting month**, from three independent signals: the dates in the data, the
filename, and the sheet name.

If those signals disagree you get a clear warning:

> ⚠ Month conflict detected — Filename: March 2026 · Date data: April 2026

You can then confirm or override the reporting period from the dropdown before
anything is imported.

### Step 3 — Validate

The app reports anything worth knowing before you commit: rows it had to skip
and why, rows dated outside the dominant year (usually typos in the sheet), and
rows with no date at all.

Press **Confirm and import**, or **Cancel** to discard.

### Step 4 — Review metrics

The full executive dashboard appears **in the browser** — the same one that goes
into the deck. KPI tiles, the monthly trend, the defect-category donut, the top
performers, the task-composition bar and the key insights.

Expand *Monthly detail, developer table and recommendations* for the full tables.

### Step 5 — Configure the report

Choose years, months and developers. *More filters* holds defect category,
severity, environment, ISO week, day of month and QA analyst. *Sections to
include and report options* holds the slide toggles, the cover label and the
optional note — collapsed by default so the common case stays a three-field
form.

**Nothing is processed while you do this.** Every filter sits inside a form, so
changing a dropdown does not trigger any work. This was a deliberate design
decision: the app should never grind away while you are still deciding.

### Step 6 — Generate report

Press **Generate report**. A progress bar pinned to the top of the page fills as
the deck, the PDF and the CSV are built, and settles on **REPORT GENERATED**.
Streamlit's own spinner is hidden — it sits in the corner, says nothing useful
and shifts the page while you are reading it.

### Step 7 — Download

Three buttons: PowerPoint, PDF, and the underlying filtered rows as CSV.
Downloading does not rebuild anything.

### Other tabs

- **Compare** — puts two or three markets side by side on one chart.
- **Data manager** — merge developer name variants, delete a period, view the
  full import history, back up or export the database.
- **Help** — the calculation rules, in the app itself.

### Clearing everything

The sidebar has **🗑 Clear all data**. It asks for confirmation, writes a backup
first, then empties all three markets so you can start fresh.

**Your import history is deliberately kept.** It is the audit trail of what was
loaded and when, and wiping it would destroy the record of work you actually
did. The reset itself is logged in that history too.

---

## 6. Generating reports

1. Import at least one audit sheet for the market.
2. Go to the **Data manager** tab and merge any flagged name variants. *Do this
   before reporting* — one person counted under three spellings splits their
   score three ways and distorts the whole report.
3. Back on the market tab, choose your years and months.
4. Optionally narrow by developer, category, severity, environment, week or day.
5. Tick the sections you want:

   | Section | What it contains |
   |---|---|
   | Monthly section | Per month: a **month divider** naming the month and year, then Quality Score, Developer Report, and Defect Analysis |
   | QA summary | Every KPI in one table, plus the month-by-month trend |
   | Developer summary | One full-width per-developer table |
   | Defect categories | Category breakdown and internal vs external |
   | Aging analysis | *(off by default)* Defect age distribution |
   | Critical defects | *(off by default)* Defects logged at Critical severity |
   | Recommendations | Actions derived from the numbers |
   | Score dashboard | The combined summary — **the last slide before Thank You** |

   Slide order is: Title → \[month divider → 3 slides] per month → Consolidated
   divider → QA Summary → Developer Summary → Defect Categories →
   Recommendations → **Dashboard** → Thank You.

   Every slide answers one question and holds at most two visual elements. That
   is deliberate: an earlier version packed four panels onto a slide and the
   numbers fought each other.

6. Press **Generate report**, then download.

The on-screen dashboard, the PPTX, the PDF and the CSV all read from the same
calculation functions, so their numbers are identical by construction — this is
covered by an automated test.

---

## 7. How the quality score works

An **observation** is a task that is error free but carries a remark. It is a
*subset* of the error-free tasks, never an extra bucket on top of them.

```
Error-Free Tasks = No Error + Observation
Total Tasks      = Error + Error-Free Tasks
                 = Error + No Error + Observation
Quality Score    = Error-Free Tasks ÷ Total Tasks × 100
```

**Worked example** — Total 20, Error 2, No Error 15, Observation 3:

```
Error-Free    = 15 + 3  = 18
Total Tasks   =  2 + 18 = 20
Quality Score = 18 / 20 = 90.00%
```

Adding `Error + No Error + Observation + Error-Free` would double-count the
error-free tasks. Nothing in this app does that, and a test asserts it.

**Zero tasks → the score is `N/A`**, never 100%.

All scores display to two decimal places: `92.00%`, `93.75%`, `95.65%`.

### Two headline measures, both shown

- **Overall Quality Score** — pooled: `SUM(Error-Free) ÷ SUM(Total)`. This is the
  headline figure everywhere.
- **Average Monthly Quality Score** — the mean of the monthly percentages.

They diverge when months have very different volumes: a 100% month with 4 tasks
lifts the *average* far more than it lifts the *overall*. Both are labelled
wherever they appear.

### Imported decks used an older convention

Decks issued before this tool counted observations **inside** the No Error
figure, so a developer row read `0 error, 19 no-error, 3 observation, Grand
Total 19`. Under the current rule those three counts are separate.

The importer detects the old convention and lifts the observations back out of
No Error, so an imported month keeps exactly the totals it was published with
instead of gaining phantom tasks and a higher score. The app tells you when it
does this.

### What gets tidied automatically

| In the sheet | Becomes |
|---|---|
| `First Time Correct`, `FTC`, `Pass`, `Correct` | No Error |
| `Error`, `Fail`, `Defect` | Error |
| `Observation`, `Obs` | Observation |
| `Test` (Test Environment) | Internal — caught before release |
| `Live`, `live`, `LIVE` | External |
| `Design layout Related` / `Design Related` | Design Related |
| `Redirected link` / `Redirect Links Related` | Redirect Links |

Developer names are **merged automatically when there is only one possible
match**, across every market. `Amol Dohale` → `Amol Laxman Dohale`, `Kapil K` →
`Kapil Kumar`, `sandeep.j@craftww.com` → `Sandeep Jadhav`, `Neha lal` →
`Neha Lal` — all applied without asking.

A merge is only ever left to you when it is genuinely ambiguous. If both
`Amol Laxman Dohale` and `Amol Gaikwad` are on the team, a bare `Amol` could be
either, and guessing would move one person's tasks onto another. Those cases
appear on the **Data manager** tab with a dropdown to resolve them.

Names that merely share a first name (`Neha Lal` / `Neha Gupta`,
`Mitesh Gupta` / `Mitesh Salunkhe`) are never merged.

### Excel and PowerPoint disagreeing

If the same month exists as both an Excel import and a PowerPoint import and the
figures differ, the app does not silently pick one. It shows:

> ⚠ Source discrepancy detected for Jan 2026 — Excel quality score 92.00%
> (92/100 tasks) vs PowerPoint 91.00% (91/100). Excel has been selected as the
> primary calculation source. Please review the discrepancy.

Task-level Excel data is always the primary source when it is available.

---

## 8. Running the tests

```
python tests.py
```

107 checks covering the calculation engine, ingestion, filtering, legacy deck
conversion, name merging, error handling, hosted storage and output
consistency. It needs no test framework,
touches no network, and never modifies your saved data.

Expected output ends with:

```
  107 passed, 0 failed
```

---

## 9. Troubleshooting

**"python is not recognised as an internal or external command"**
Python is not on your PATH. Reinstall from python.org and tick *"Add Python to
PATH"*, or use the full path to `python.exe`.

**"No header row could be found."**
The sheet needs a row containing at least a developer column and a status column
(for example `Developer Name` and `Status`). Check you uploaded the raw audit log
rather than a pivot or summary view.

**"No 'Status' column was found."**
That column decides pass or fail, so it is required. Check for a renamed column —
`Result` and `QA Status` are also recognised.

**"This file could not be opened as an Excel workbook."**
The file is corrupted, password protected, or is actually a different format
saved with an `.xlsx` name. Open it in Excel and re-save as `.xlsx`.

**"This is an old-format .xls file..."**
Either run `pip install xlrd`, or open it in Excel and save as `.xlsx`.

**"No monthly figures could be read from this deck."**
The PowerPoint importer looks for slide titles like `Quality Score for month of
C3 Jan 2026` with a table underneath. If your deck uses a different layout,
import the Excel audit sheet instead — it produces a better report anyway.

**A developer appears twice with split scores**
Unambiguous variants merge on import. If two rows remain, the name was
ambiguous — resolve it on the **Data manager** tab.

**An imported deck's numbers do not match the deck itself**
Fixed in this version. Consolidated slides at the end of a deck (titles naming a
range like "Jan – Jun 2026") were being read as if they belonged to January,
replacing that month's real figures with whole-period totals. Those slides are
now skipped, and a test asserts that importing your C3 deck reproduces its
published 641 tasks / 43 defects / 93.29% exactly.

**Scores look higher than expected after filtering**
Check whether a category or severity filter is active. Those filters narrow the
defects only and never remove passing tasks, but a developer or date filter
legitimately changes the denominator.

**The quality score differs from an older deck**
Almost always the observation rule. Older decks counted observations inside the
No Error figure; this app treats the three counts as separate. The *Help* tab
explains it, and imported decks are converted so their published totals hold.

**"Port 8501 is already in use"**
Another copy is running. Close it, or use `streamlit run app.py --server.port 8502`.

**The report failed to generate**
The message tells you what to adjust. There is a collapsed *Technical detail*
panel for whoever maintains the tool — nothing has been changed, so you can
alter the filters and try again.

**I cleared data by accident**
Look in `data/backups/`. A snapshot is written before every destructive action.
Copy the one you want over `data/database.json` and restart the app.

---

## 10. Deploying to Streamlit Community Cloud

### Read this first: hosted storage works differently

On your laptop, `data/database.json` **is** the database. On a hosted server it
cannot be, for two reasons:

- **The filesystem is wiped on every reboot.** Community Cloud restarts apps
  after inactivity, on redeploy, and when resources run short. Anything
  "saved" would silently vanish.
- **Everyone shares one container.** Without isolation, one person's uploaded
  audit sheet would be visible to the next visitor, and one person pressing
  *Clear all data* would wipe everybody's.

For client QA data neither is acceptable, so the app detects a hosted
environment and switches to **session storage**: nothing is written to disk, and
each browser session gets its own private copy. A banner at the top of the app
says so.

**Work is kept with the two buttons on the Data manager tab:**

| Button | What it does |
|---|---|
| **Export database (.json)** | Downloads everything currently loaded |
| **Restore database** | Loads that file back, replacing what's in the session |

Tell your QA head to export before closing the tab. It takes one click.

You can force either mode with an environment variable:

```
QARS_STORAGE=session   # never touch disk (the hosted default)
QARS_STORAGE=disk      # always use ./data (the local default)
```

If the disk turns out to be read-only at runtime, the app falls back to session
storage on its own rather than crashing.

### Putting it on GitHub

```bash
cd QA_Report_Studio
git init
git add .
git commit -m "QA Report Studio"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

A `.gitignore` is included. It deliberately excludes `data/*.json`, so **client
audit data is never committed** — check `git status` before your first commit
and confirm no database file is listed.

Use a **private** repository if the audit sheets are confidential. Community
Cloud can deploy from private repos, but note that the *app URL itself is
public* unless you restrict viewers in the app settings.

### Deploying

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. **Create app** → pick your repository and the `main` branch.
3. Set **Main file path** to `app.py`.
4. Open **Advanced settings** and choose **Python 3.11** (or 3.12). The default
   is usually fine; anything 3.10 or newer works.
5. **Deploy.** The first build takes a few minutes while the dependencies
   install.

Nothing else is required:

- **No secrets.** The app calls no external service, so the *Secrets* box stays
  empty.
- **No `packages.txt`.** Every dependency is pure Python or ships prebuilt
  wheels.
- **`.streamlit/config.toml`** is picked up automatically for the theme.

### Restricting who can see it

App settings → **Sharing** → invite specific email addresses. Without this, the
URL is public to anyone who has it. Given the app holds client QA data, set this
before you share the link.

### Things to expect on the free tier

| | |
|---|---|
| Memory | About 1 GB. A 12-month report with every section on is the heaviest thing the app does — if a build ever fails, untick *Monthly section* or generate fewer months at a time. |
| Sleeping | The app sleeps after inactivity and wakes on the next visit, taking a few seconds. Session data does **not** survive that. |
| Upload size | Capped at 200 MB per file in `.streamlit/config.toml`, far above any audit sheet. |
| `.xls` files | Not supported unless you uncomment `xlrd` in `requirements.txt` before deploying. `.xlsx` and `.csv` always work. |

### Updating the deployed app

Push to `main` and Community Cloud redeploys automatically. Remember that a
redeploy restarts the container, so anyone mid-session loses their loaded data —
worth mentioning before you push during working hours.

---

## 11. Converting to a .exe later

The app was built with freezing in mind: matplotlib rather than a browser-based
chart engine, ReportLab rather than a LibreOffice conversion, and drawn icons
rather than icon fonts — so nothing needs an external binary at runtime.

Create a small `run_exe.py` launcher that calls
`streamlit.web.bootstrap.run()` on `app.py`, then:

```
pip install pyinstaller
pyinstaller --noconfirm --onedir --name "QA Report Studio" ^
  --add-data "qars;qars" ^
  --add-data ".streamlit;.streamlit" ^
  --collect-all streamlit ^
  --collect-all matplotlib ^
  --collect-all pptx ^
  --collect-all reportlab ^
  run_exe.py
```

Use `--onedir`, not `--onefile`. One-file builds unpack to a temp folder on every
launch, which makes a Streamlit app slow to start and can trip antivirus.

Keep the `data` folder beside the executable so reports and settings persist. No
admin rights are needed to run the result, as long as it sits somewhere the user
can write to.

---

## 12. Project structure

```
QA_Report_Studio/
├── app.py                  Streamlit UI — workflow, dashboard, generation
├── tests.py                107 automated checks (python tests.py)
├── requirements.txt
├── .gitignore              keeps client data out of version control
├── run_windows.bat         Windows launcher
├── run_mac_linux.sh        macOS / Linux launcher
├── .streamlit/config.toml  Theme and server settings
├── data/                   Your JSON database (created on first run)
└── qars/
    ├── theme.py            Palette sampled from the dashboard reference
    ├── store.py            Atomic JSON persistence
    ├── normalize.py        Name, status, category and severity cleaning
    ├── ingest.py           Excel / CSV / PPTX readers, month detection
    ├── metrics.py          Every calculation, in one place
    ├── charts.py           Matplotlib charts and hand-drawn icons
    ├── deck.py             PPTX builder
    └── pdf.py              PDF builder
```

`metrics.py` is the only place any figure is calculated. The dashboard, the
deck, the PDF and the CSV all call into it, which is what makes their numbers
identical rather than merely similar.

The PPTX and the PDF are drawn independently from the same palette, the same
chart images and the same metrics, at the same 13.333 × 7.5in page — so they
look the same, and the PDF does not need PowerPoint or LibreOffice installed.
