# Moving QA Report Studio into an Omni agent

This folder turns the reporting tool into the **Developer Defect Tracker** agent
in Omni's Agent Builder (`omniai.omc.com` → Agent Builder). It holds the text for
every section of the builder, the files the agent needs, and this procedure.

Setting it up takes about half an hour, once. After that the monthly routine is:
give the agent the month's three sheets, check its figures, download the report.

---

## 1. What moves, and what changes

The tool is a program: it counts every row of a sheet with code, so its figures
are exact by construction. An Omni agent is a language model that you configure
with text and files. It cannot run the tool's code. So the tool is moved by
handing the agent everything the tool knows:

| The tool has | The agent gets it as |
|---|---|
| The rules for reading a sheet and calculating a score | **Instructions** and `Rulebook.txt` |
| The report's sections and layout | **Expected Output** and `Report_Layout.txt` |
| Every month already reported (the report library) | `QA_History.txt` |
| Which spellings are the same developer | `Developer_Names.txt` |
| The PowerPoint / PDF download | The **File Export** tool |

Two things are different, and you should know them before you rely on it:

1. **The agent reads a sheet; it does not compute it.** On sheets of this size a
   good model usually counts correctly, but "usually" is not "always". That is
   why the instructions make it show a reconciliation, and why section 4 below
   is a test with known answers. Run that test before you trust it.
2. **The agent remembers nothing between chats.** Its memory is the attached
   `QA_History.txt`. Each month you add that month's lines to the file and
   upload it again (section 5). That is the agent's version of the tool keeping
   a month for good.

If the Tools list in your Agent Builder has a tool for running code or analysing
data, tick it (step 6). With it the agent counts with a program, and point 1
stops being a concern.

---

## 2. What you need

The agent pack. Either use the zip you were sent, or build it yourself:

```
python agent/build_pack.py
```

That writes `agent/pack/`:

```
SETUP_GUIDE.html     this procedure as one page, with a Copy button for each text
1_agent_fields/      text to paste into Agent Builder
    1_description.txt
    2_instructions.txt
    3_expected_output.txt
    4_goals.txt
    5_tools.txt
2_attachments/       files to upload under Attachments
    QA_History.txt
    Developer_Names.txt
    Rulebook.txt
    Report_Layout.txt
3_for_you_only/      NOT for the agent
    Test_Answers.txt       the right answers, to check the agent against
    QA_History.xlsx        the same history as a spreadsheet
    sample_reports/        the tool's own reports, in the white layout
```

The pack is built from the sheets in `qars/library/`, by the same code that
produces the tool's reports, so the history the agent starts with is exact.

---

## 3. Build the agent

Open Agent Builder and the **Developer Defect Tracker** agent. The sections are
listed down the left. Do them in this order, and press **Save** at the bottom
of each one before moving on.

| Step | Section on the left | What to do |
|---|---|---|
| 1 | **Description** | **Name**: `Developer Defect Tracker`. **Description**: paste the DESCRIPTION paragraph from `1_description.txt`. Icon is optional. |
| 2 | **Instructions** | Open `2_instructions.txt`, select all, copy, paste into the box. |
| 3 | **Expected Output** | Paste all of `3_expected_output.txt`. |
| 4 | **Goals** | Paste all of `4_goals.txt`. |
| 5 | — | **Stop here and run Part 1 of the test (section 4).** The history is not attached yet, so the agent has to count for itself. |
| 6 | **Tools** | Tick **File Export**. Leave every other tool unticked. Then scroll to the end of the list: if there is a tool for running code or analysing data, tick that too. `5_tools.txt` explains why. |
| 7 | **Attachments** | Press **Upload Attachment** and upload the four files in `2_attachments/`. Nothing from `3_for_you_only/`. |
| 8 | **Data Sources** | Leave empty. Data sources are for client and audience datasets; this agent needs none. |
| 9 | **Share** (top right) | Share it with the people who produce or read the QA report. |

<!-- FIELD_BOXES -->

If a box will not take the whole text, paste as much as it accepts up to the end
of a section (a line starting with `#`), save the rest as `Instructions_More.txt`,
upload that as a fifth attachment, and add one line at the end of the box:
`The rest of these instructions is in Instructions_More.txt - read it first.`

---

## 4. Test it before you trust it

`3_for_you_only/Test_Answers.txt` holds the right answer to every test below,
worked out by the tool from the same sheets. Keep it open next to the chat.
**Never upload that file to the agent** — it would read the answers instead of
working them out.

**Part 1 — can it count a sheet?** Do this after step 4, before the attachments.

Open a chat with the agent, attach one sheet, and type `Count this sheet.`
(It may mention that its name and history files are missing; that is expected
at this point.) Compare its reply with the same test in `Test_Answers.txt`.
Start with these four, because each has something a careless reader gets wrong:

| Attach | It must find |
|---|---|
| `September 2026 India.xlsx` | 154 tasks, 95.45%. Two rows not counted: row 111 (no Status) and row 140 (no Developer Name). |
| `September 2026 Japan.xlsx` | 72 tasks, 94.44%. The typo "Psas" in row 3, read as Pass. |
| `September 2026 C3.xlsx` | 91 tasks, 94.51%. Two rows dated 1975, filed under September 2026. |
| `July 2026 Japan.xlsx` | 69 tasks, 92.75%. Three rows dated August, filed under July. |

Then check the developer table against the one in `Test_Answers.txt`, row by row.

- **Every figure matches** → the agent reads your sheets correctly. Carry on.
- **A total is off by a few** → it did not read every row. Try once more with
  `Count every row, one at a time, and show your tally per developer.` If it is
  still wrong, see "If the counts are wrong" below.
- **It says it cannot open the file, or sees only part of it** → the chat does
  not pass whole spreadsheets to the agent. See "If the counts are wrong".

**Part 2 — can it report from the history?** Do this after step 7.

Type `Give me the C3 report for January to September 2026.` It should give
980 tasks, 66 defects and an overall score of 93.27%, with the month table and
developer summary in `Test_Answers.txt`. Repeat for India (423 tasks, 93.85%)
and Japan (656 tasks, 96.19%).

**Part 3 — does it keep the rules?** Three one-line questions, at the end of
`Test_Answers.txt`. It must refuse to add observations on top of the error-free
tasks, and must answer N/A for a month with no tasks.

**Then try the export.** Ask `Export the India report for July to September 2026.`
Check the file opens, the figures match the chat, and the layout is white and
plain. If it offers a choice of format, PowerPoint or PDF suits this report.

---

## 5. The monthly routine

1. **Give it the sheets.** Open a chat, attach the month's three sheets (India,
   C3, Japan), and type `Here are October's sheets.` Keep the market in each
   file name — `October 2026 C3.xlsx` — because that is how it knows which
   market a sheet is for.
2. **Read the import check.** For each sheet it lists the tasks counted, the
   reconciliation, the rows it could not count and why, typos it corrected,
   dates it moved, and names it is unsure of. Fix anything that is a mistake in
   the sheet and give it the corrected sheet; answer any name question.
3. **Spot-check the count.** In Excel, filter the Status column to non-blank
   rows and look at the count in the status bar. It should equal the agent's
   "tasks counted" plus its "not counted" rows. This takes ten seconds and
   catches the one mistake a language model can make.
4. **Ask for the report.** `Give me the C3 report for January to October 2026.`
   One month only: `Give me the India report for October 2026.`
5. **Export it.** `Export this report as PowerPoint.` (or PDF).
6. **Save the month.** The agent ends its reply to each sheet with a
   **History update** block. Open `QA_History.txt`, paste each block at the end
   of its market's section, save, and in Agent Builder → **Attachments** remove
   the old `QA_History.txt` and upload the new one. Until you do this, the agent
   will not know October next month.

Keep a dated copy of `QA_History.txt` each month. It is the whole record.

Things you can ask at any time:

- `How did Neha Lal do from July to September in India?`
- `Which category caused the most defects in C3 this year?`
- `Compare the three markets for July to September.`
- `Why is the India score for August 90.32%?` — it shows the arithmetic.
- `Only live-link defects for Japan, please.`

A question about one severity, one week or one QA analyst needs that month's
sheet attached in the same chat: the history holds each month's totals, not its
individual rows.

---

## 6. Names

`Developer_Names.txt` ends with the questions nobody has answered yet — a short
name that two developers share, or two spellings that may be one person. Until
they are answered, each spelling is counted as its own person, which can split
one developer's work in two.

Answer them once: edit the file so the spellings sit on one `NAME` line (same
person) or stay on two (different people), delete the `ASK` line, and upload the
file again. If you merge two names, also change that developer's name on the
`DEV` lines of `QA_History.txt`, or run `python agent/build_pack.py` after
recording the decision in the tool (Data Manager → Developer name merging), which
rewrites both files for you.

---

## 7. If the counts are wrong

The agent reading a sheet is the one step that cannot be guaranteed from here,
because it depends on how Omni passes a spreadsheet to the model. If Part 1 of
the test does not pass, in order of preference:

1. **Turn on a code or data-analysis tool** in the Tools section, if there is
   one, and run the test again.
2. **Give it the sheet as CSV.** In Excel: File → Save As → CSV. Plain text is
   the easiest thing for a model to read completely.
3. **Give it one market at a time**, in separate chats, so a long sheet is not
   competing for attention with two others.
4. **Keep the tool for the counting.** Add the month's sheets to the tool, run
   `python agent/build_pack.py`, and upload the new `QA_History.txt`. The agent
   then reports from exact figures and never has to count. This always works.

---

## 8. Keeping the pack up to date from the tool

Whenever the tool's library gains a month (or a name decision), rebuild:

```
python agent/build_pack.py
```

and replace the agent's four attachments with the new `2_attachments/` files.
`--no-samples` skips the sample reports and is quicker.

The pack contains developer names and scores, so `agent/pack/` is not committed
to the repository. The texts in this folder contain no audit data and are.
