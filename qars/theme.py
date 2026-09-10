"""
Central design system for QA Report Studio.

Every colour here was sampled directly from the reference dashboard image so the
Streamlit UI, the generated PPTX and the generated PDF all look like one product.
Nothing in this module touches the network or the disk.
"""

# --------------------------------------------------------------------------
# Core palette (sampled from the reference dashboard)
# --------------------------------------------------------------------------
NAVY = "001848"   # header banners, section title bars
NAVY_DK = "00102F"   # deeper navy for the title slide gradient feel
BLUE = "0046A5"   # primary data colour: bars, donut slice 1
BLUE_LT = "3D7CC9"   # lighter blue for secondary series
GREEN = "1E7024"   # success / error-free
RED = "E10600"   # defects
ORANGE = "FF6600"   # internal defects
PURPLE = "381B7A"   # developer counts
TEAL = "00838C"   # average score
GOLD = "F1B100"   # rank 1
SILVER = "A9B0BC"   # rank 2
BRONZE = "B7703C"   # rank 3

WHITE = "FFFFFF"
PAGE_BG = "F4F6FA"   # app / slide canvas
CARD_BG = "FFFFFF"
BORDER = "D8DEE9"
GRID = "E8ECF3"
TEXT = "1B2437"
TEXT_MUTED = "5A6478"
ROW_ALT = "F7F9FC"

# Ordered accent ramp used for KPI tiles and category charts.
ACCENTS = [BLUE, GREEN, RED, ORANGE, NAVY, PURPLE, TEAL]

# Fixed colour per defect category so a category keeps its colour everywhere.
CATEGORY_COLORS = {
    "Content Related": BLUE,
    "Design Related": ORANGE,
    "Redirect Links": GREEN,
    "Navigation Related": PURPLE,
    "Image Related": TEAL,
    "Video Related": SILVER,
    "Functionality": RED,
    "LinkBuilder": BLUE_LT,
    "EDM": BRONZE,
    "Multiple Issues": NAVY,
    "Other": TEXT_MUTED,
}

# Severity colours (worst -> mildest).
SEVERITY_COLORS = {
    "Critical": RED,
    "Major": ORANGE,
    "Minor": GOLD,
    "Cosmetic": TEAL,
    "Unspecified": SILVER,
}

# --------------------------------------------------------------------------
# Typography — every face below ships with Office AND renders predictably.
# --------------------------------------------------------------------------
FONT_HEAD = "Arial"
FONT_BODY = "Calibri"

# --------------------------------------------------------------------------
# Score bands — drive the colour of any score shown anywhere in the product.
# --------------------------------------------------------------------------
BAND_GOOD = 95.0
BAND_OK = 90.0


def score_color(score):
    """Green at/above 95, amber 90-95, red below 90. `None` -> muted grey."""
    if score is None:
        return TEXT_MUTED
    if score >= BAND_GOOD:
        return GREEN
    if score >= BAND_OK:
        return ORANGE
    return RED


def score_band(score):
    if score is None:
        return "No data"
    if score >= BAND_GOOD:
        return "On target"
    if score >= BAND_OK:
        return "Watch"
    return "Below benchmark"


def hx(color):
    """`001848` -> `#001848` for CSS / matplotlib."""
    return "#" + color.lstrip("#")


# --------------------------------------------------------------------------
# Streamlit CSS. Injected once per run.
# --------------------------------------------------------------------------
def app_css():
    return f"""
<style>
:root {{
  --navy: {hx(NAVY)}; --blue: {hx(BLUE)}; --green: {hx(GREEN)};
  --red: {hx(RED)};  --orange: {hx(ORANGE)}; --teal: {hx(TEAL)};
  --purple: {hx(PURPLE)}; --border: {hx(BORDER)}; --muted: {hx(TEXT_MUTED)};
}}
.stApp {{ background: {hx(PAGE_BG)}; }}
/* Streamlit's toolbar is fixed at the top and about 3.75rem tall; the default
   container padding exists to clear it. Trimming it to 1.4rem pulled the first
   element on the page up underneath the toolbar, which is what was slicing the
   top off the progress bar. */
.block-container {{ padding-top: 0.75rem; padding-bottom: 3rem; max-width: 1500px; }}

/* ---------- masthead ---------- */
.qrs-head {{
  background: linear-gradient(100deg, {hx(NAVY_DK)} 0%, {hx(NAVY)} 55%, {hx(BLUE)} 165%);
  border-radius: 14px; padding: 20px 26px; margin-bottom: 18px;
  box-shadow: 0 6px 20px rgba(0,24,72,.20);
}}
.qrs-head h1 {{
  color:#fff; font-family:{FONT_HEAD},sans-serif; font-size:1.62rem;
  font-weight:800; margin:0; letter-spacing:.4px;
}}
.qrs-head p {{ color:#C6D4EC; margin:.35rem 0 0; font-size:.88rem; }}

/* ---------- section title bar ---------- */
.qrs-bar {{
  background:{hx(NAVY)}; color:#fff; border-radius:9px; padding:9px 16px;
  font-family:{FONT_HEAD},sans-serif; font-weight:700; font-size:.94rem;
  letter-spacing:.6px; margin:16px 0 12px;
}}

/* ---------- KPI tiles ---------- */
.qrs-kpis {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:6px; }}
.qrs-kpi {{
  flex:1 1 150px; background:#fff; border:1px solid {hx(BORDER)};
  border-radius:12px; padding:14px 16px; box-shadow:0 2px 6px rgba(16,32,64,.06);
}}
.qrs-kpi .v {{ font-family:{FONT_HEAD},sans-serif; font-size:1.72rem; font-weight:800;
               line-height:1.1; white-space:nowrap; }}
.qrs-kpi .l {{ color:{hx(TEXT_MUTED)}; font-size:.74rem; margin-top:4px;
              text-transform:uppercase; letter-spacing:.5px; font-weight:600; }}
.qrs-kpi .s {{ color:{hx(TEXT_MUTED)}; font-size:.70rem; margin-top:2px;
               white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}

/* Four-across inside a narrow column: shrink the number so the whole value is
   readable instead of being clipped to "9…". */
.qrs-kpis.tight {{ gap:7px; }}
.qrs-kpis.tight .qrs-kpi {{ flex:1 1 0; min-width:0; padding:9px 10px; }}
.qrs-kpi.small .v {{ font-size:1.02rem; }}
.qrs-kpi.small .l {{ font-size:.60rem; letter-spacing:.3px; margin-top:3px; }}
.qrs-kpi.small .s {{ font-size:.60rem; }}

/* ---------- generic card ---------- */
.qrs-card {{
  background:#fff; border:1px solid {hx(BORDER)}; border-radius:12px;
  padding:16px 18px; box-shadow:0 2px 6px rgba(16,32,64,.06); margin-bottom:12px;
}}
.qrs-note {{
  background:#FFF7E8; border:1px solid #F0D9A8; color:#6B4E12;
  border-radius:10px; padding:10px 14px; font-size:.85rem; margin:8px 0;
}}
.qrs-ok {{
  background:#EAF6EC; border:1px solid #B9DEC0; color:#1C4C24;
  border-radius:10px; padding:10px 14px; font-size:.85rem; margin:8px 0;
}}

/* ---------- primary action button ---------- */
div[data-testid="stForm"] button[kind="primaryFormSubmit"],
.stButton > button[kind="primary"] {{
  background:{hx(NAVY)} !important; border:0 !important; color:#fff !important;
  font-weight:700 !important; letter-spacing:.5px; border-radius:10px !important;
  padding:.62rem 1.1rem !important; box-shadow:0 3px 10px rgba(0,24,72,.25) !important;
}}
div[data-testid="stForm"] button[kind="primaryFormSubmit"]:hover,
.stButton > button[kind="primary"]:hover {{ background:{hx(BLUE)} !important; }}

/* ---------- tabs ---------- */
.stTabs [data-baseweb="tab-list"] {{ gap:6px; border-bottom:2px solid {hx(BORDER)}; }}
.stTabs [data-baseweb="tab"] {{
  background:#EDF1F8; border-radius:9px 9px 0 0; padding:9px 20px;
  font-weight:700; font-size:.87rem; color:{hx(TEXT_MUTED)};
}}
.stTabs [aria-selected="true"] {{ background:{hx(NAVY)} !important; color:#fff !important; }}

section[data-testid="stSidebar"] {{ background:#fff; border-right:1px solid {hx(BORDER)}; }}
section[data-testid="stSidebar"] h2 {{ font-size:1rem; color:{hx(NAVY)}; }}
#MainMenu, footer {{ visibility:hidden; }}

/* Streamlit's own spinner sits top-right and jitters the layout. The app
   reports its own progress in the sticky bar below instead. */
[data-testid="stStatusWidget"] {{ display:none !important; }}

/* ---------- sticky progress bar ---------- */
/* Streamlit's toolbar is fixed at the top with a very high z-index, so a bar
   stuck at top:0 scrolls underneath it and gets half-eaten. Sticking just below
   the toolbar keeps the whole bar readable; making the toolbar opaque stops
   page content showing through it on the way past. */
/* Streamlit's top toolbar is removed outright. It held only the "Deploy"
   prompt and a menu that is already hidden below, and leaving it in meant the
   page began 60px down with a grey band that merged with the progress strip
   and read as one oversized header.
   To bring the toolbar back, delete this rule and set `top` on the sticky
   rule below back to 2.75rem. */
header[data-testid="stHeader"],
[data-testid="stHeader"],
[data-testid="stToolbar"],
.stAppHeader {{ display:none !important; height:0 !important; }}
/* ---------- sticky progress bar ----------
   A sticky element can only travel inside its own parent, and st.empty() wraps
   the bar in a container exactly as tall as the bar itself — so sticking the
   bar directly just scrolls it away. The ELEMENT CONTAINER is made sticky
   instead: its parent is the page-length vertical block, which gives it the
   full height of the page to stick against.

   `:has()` is used so the rule only ever hits our own bar and never some other
   first element on the page. */
[data-testid="stMain"] [data-testid="stElementContainer"]:has(.qrs-sticky),
[data-testid="stMain"] .element-container:has(.qrs-sticky),
section.main .element-container:has(.qrs-sticky) {{
  position:sticky !important;
  top:0;
  z-index:1000001;
  background:{hx(PAGE_BG)};
}}
.qrs-sticky {{
  background:{hx(PAGE_BG)};
  padding:6px 0; margin:0;
  box-shadow:0 6px 12px -10px rgba(0,24,72,.45);
}}

/* Fallback for browsers without :has() — the rule above cannot match there, so
   the bar is pinned with `fixed` instead. Fixed ignores ancestors entirely, at
   the cost of spanning the sidebar too. The spacer keeps the page from sliding
   underneath it. */
@supports not selector(:has(*)) {{
  .qrs-sticky {{
    position:fixed; top:0; left:0; right:0;
    z-index:1000001; padding:6px 18px;
  }}
  .qrs-sticky::after {{ content:""; display:block; }}
  .qrs-spacer {{ display:block; height:38px; }}
}}
.qrs-spacer {{ display:none; }}
.qrs-track {{
  height:26px; border-radius:8px; background:#E4E9F2; overflow:hidden;
  border:1px solid {hx(BORDER)}; position:relative;
}}
.qrs-fill {{
  height:100%; background:linear-gradient(90deg,{hx(NAVY)},{hx(BLUE)});
  transition:width .25s ease;
}}
.qrs-fill.done {{ background:linear-gradient(90deg,{hx(GREEN)},#2E9E4F); }}
.qrs-track span {{
  position:absolute; top:0; left:0; right:0; bottom:0;
  display:flex; align-items:center; justify-content:center;
  font-size:.76rem; font-weight:700; letter-spacing:.4px; line-height:1;
  color:{hx(TEXT)};
}}
.qrs-track span.on {{ color:#fff; }}

/* Compact table used where a dataframe would scroll sideways. */
.qrs-table {{
  width:100%; border-collapse:collapse; font-size:.78rem;
  background:#fff; border:1px solid {hx(BORDER)}; border-radius:8px;
  overflow:hidden; table-layout:fixed;
}}
.qrs-table th {{
  background:{hx(NAVY)}; color:#fff; text-align:left; padding:6px 8px;
  font-size:.70rem; font-weight:700; letter-spacing:.3px;
}}
.qrs-table td {{ padding:6px 8px; border-top:1px solid {hx(GRID)};
                 overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.qrs-table th.num, .qrs-table td.num {{ text-align:right; width:64px; }}
.qrs-table tr:nth-child(even) td {{ background:{hx(ROW_ALT)}; }}

/* Keep tables inside their column instead of scrolling sideways. */
div[data-testid="stDataFrame"] {{ width:100% !important; }}
div[data-testid="stDataFrame"] table {{ table-layout:fixed; width:100% !important; }}
</style>
"""
