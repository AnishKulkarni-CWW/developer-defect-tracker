"""
Central design system for QA Report Studio.

One palette drives three surfaces — the Streamlit app, the generated PPTX and
the generated PDF — so the product looks like one thing everywhere. The palette
is brand-orange led: a warm vermilion for chrome and calls to action, a light
warm-grey canvas, white cards, and a small set of data colours that stay
distinct from the brand so a chart never reads as decoration.

Nothing in this module touches the network or the disk.
"""

from string import Template

# --------------------------------------------------------------------------
# Brand
# --------------------------------------------------------------------------
BRAND = "F4511E"   # primary action / active nav / brand marks
BRAND_DK = "D8441C"   # chrome on print surfaces, where white text must pass contrast
BRAND_DP = "A83411"   # deepest stop of the brand gradient
BRAND_LT = "FF8A5B"   # hover / secondary brand fill
BRAND_SOFT = "FFF1EA"   # peach wash behind hero banners and active nav

# --------------------------------------------------------------------------
# Core palette
#
# NAVY / NAVY_DK keep their names because the deck and PDF builders use them to
# mean "the brand's chrome colour" — banners, title slides, section bars. In
# this design that colour is the brand orange, deepened enough that white text
# on top of it stays legible in print.
# --------------------------------------------------------------------------
NAVY = BRAND_DK    # header banners, section title bars
NAVY_DK = BRAND_DP    # deeper stop for the title-slide gradient

BLUE = "2563EB"   # data colour: audited volume
BLUE_LT = "60A5FA"   # lighter blue for secondary series
GREEN = "16A34A"   # success / error-free
RED = "E11D2E"   # defects
ORANGE = "F59E0B"   # amber — internal defects (kept distinct from the brand)
PURPLE = "7C3AED"   # developer counts
TEAL = "0D9488"   # observations / average score
GOLD = "F0B429"   # rank 1
SILVER = "9AA3B2"   # rank 2
BRONZE = "C0764A"   # rank 3

WHITE = "FFFFFF"
PAGE_BG = "F7F8FC"   # app / slide canvas
CARD_BG = "FFFFFF"
BORDER = "E8EAF0"
GRID = "EFF1F6"
TEXT = "171A23"
TEXT_MUTED = "6B7384"
ROW_ALT = "FAFBFD"

# Ordered accent ramp used for KPI tiles and category charts.
ACCENTS = [BLUE, GREEN, RED, ORANGE, BRAND, PURPLE, TEAL]

# Fixed colour per defect category so a category keeps its colour everywhere.
CATEGORY_COLORS = {
    "Content Related": BRAND,
    "Design Related": BLUE,
    "Redirect Links": GREEN,
    "Navigation Related": PURPLE,
    "Image Related": TEAL,
    "Video Related": SILVER,
    "Functionality": RED,
    "LinkBuilder": BLUE_LT,
    "EDM": BRONZE,
    "Multiple Issues": ORANGE,
    "Other": TEXT_MUTED,
}

# Severity colours (worst -> mildest).
SEVERITY_COLORS = {
    "Critical": RED,
    "Major": BRAND,
    "Minor": GOLD,
    "Cosmetic": TEAL,
    "Unspecified": SILVER,
}

# --------------------------------------------------------------------------
# Typography — every face below ships with Office AND renders predictably.
# --------------------------------------------------------------------------
FONT_HEAD = "Arial"
FONT_BODY = "Calibri"

# Web stack for the app only. Every face here is already on the machine — the
# app promises that nothing calls the internet, and a webfont import would be a
# network call. Inter is listed first for anyone who has it installed locally.
FONT_UI = ('Inter, "Segoe UI Variable Text", "Segoe UI", -apple-system, '
           'BlinkMacSystemFont, Roboto, "Helvetica Neue", Arial, sans-serif')

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
    """`F4511E` -> `#F4511E` for CSS / matplotlib."""
    return "#" + color.lstrip("#")


def mix(color, other, amount):
    """
    Blend `color` towards `other` by `amount` (0..1) and return a bare hex.

    Used for the soft tints behind KPI icons and status pills, so every tint is
    derived from its own accent instead of being hand-picked and drifting.
    """
    a = color.lstrip("#")
    b = other.lstrip("#")
    amount = max(0.0, min(1.0, amount))
    out = []
    for i in (0, 2, 4):
        ca, cb = int(a[i:i + 2], 16), int(b[i:i + 2], 16)
        out.append(f"{round(ca + (cb - ca) * amount):02X}")
    return "".join(out)


def soft(color, amount=0.88):
    """Tint of `color` on white — the fill behind an icon tile or a pill."""
    return mix(color, WHITE, amount)


def rgba(color, alpha):
    c = color.lstrip("#")
    return (f"rgba({int(c[0:2], 16)},{int(c[2:4], 16)},{int(c[4:6], 16)},{alpha})")


# ==========================================================================
# Streamlit CSS. Injected once per run.
#
# Written with string.Template rather than an f-string: CSS is made of braces,
# and doubling every one of them to survive f-string formatting makes the
# stylesheet unreadable and easy to break. `$name` placeholders keep it plain
# CSS that can be copied into a browser and checked as-is.
# ==========================================================================
_CSS = Template("""
<style>
:root {
  --brand:$brand; --brand-dk:$brand_dk; --brand-lt:$brand_lt; --brand-soft:$brand_soft;
  --ok:$green; --bad:$red; --warn:$amber; --info:$blue; --teal:$teal; --purple:$purple;
  --ok-soft:$ok_soft; --bad-soft:$bad_soft; --warn-soft:$warn_soft; --info-soft:$info_soft;
  --page:$page; --card:$card; --card-2:$card2;
  --ink:$ink; --muted:$muted; --border:$border; --grid:$grid;
  --radius:16px; --radius-sm:12px; --radius-xs:9px;
  --shadow-1:0 1px 2px $sh1, 0 1px 3px $sh1;
  --shadow-2:0 2px 4px $sh1, 0 12px 28px -14px $sh2;
  --shadow-3:0 18px 40px -20px $sh2;
  --ui:$font_ui;
}

/* ====================================================================
   Canvas
   ==================================================================== */
html, body, .stApp, [data-testid="stAppViewContainer"] {
  background:var(--page) !important;
  font-family:var(--ui);
  color:var(--ink);
}
.stApp p, .stApp label, .stApp li, .stApp td, .stApp th, .stApp a,
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
.stApp input, .stApp textarea, .stApp button, .stApp select,
.stApp [data-testid="stMarkdownContainer"] { font-family:var(--ui); }
/* Streamlit draws its icons as ligatures in a Material face. Never let the UI
   stack reach them, or every icon turns into the word it is named after. */
.stApp [data-testid="stIconMaterial"], .stApp [class*="material-symbols"],
.stApp .material-icons, .stApp [data-testid="stExpanderToggleIcon"] {
  font-family:"Material Symbols Rounded","Material Symbols Outlined",
              "Material Icons" !important;
}
.block-container {
  padding-top:1.1rem !important; padding-bottom:3.5rem;
  max-width:1560px;
}
/* Streamlit's own top toolbar held only a Deploy prompt and a menu that is
   hidden below. Removing it lets the app own the full height of the page. */
header[data-testid="stHeader"], [data-testid="stHeader"],
[data-testid="stToolbar"], .stAppHeader { display:none !important; height:0 !important; }
#MainMenu, footer { visibility:hidden; }
/* The built-in running indicator sits top-right, says nothing useful and
   shifts the layout. The app reports its own progress instead. */
[data-testid="stStatusWidget"] { display:none !important; }

h1, h2, h3, h4, h5 { font-family:var(--ui); color:var(--ink); letter-spacing:-.015em; }
.stApp a { color:var(--brand); }

/* ====================================================================
   Sidebar — product rail
   ==================================================================== */
section[data-testid="stSidebar"] {
  background:var(--card) !important;
  border-right:1px solid var(--border);
  width:286px !important; min-width:286px !important;
}
section[data-testid="stSidebar"] > div { padding-top:0 !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding:14px 14px 22px; }
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] { padding-bottom:0; height:0; }

.qrs-brand { display:flex; align-items:center; gap:11px; padding:8px 8px 16px; }
.qrs-brand .mark {
  width:42px; height:42px; border-radius:13px; flex:0 0 42px;
  background:linear-gradient(145deg,var(--brand-lt),var(--brand));
  display:flex; align-items:center; justify-content:center;
  font-size:21px; box-shadow:0 6px 14px -6px $brand_glow;
}
.qrs-brand .name { font-size:1.0rem; font-weight:800; color:var(--ink); line-height:1.15;
                   white-space:nowrap; }
.qrs-brand .tag  { font-size:.70rem; color:var(--muted); margin-top:2px; letter-spacing:.01em; }

.qrs-navlabel {
  font-size:.64rem; font-weight:700; letter-spacing:.09em; text-transform:uppercase;
  color:var(--muted); padding:10px 10px 6px; opacity:.85;
}

/* Nav items are real buttons so a click reruns and switches page. The active
   one is rendered as `primary`, which is what these two rules separate. */
section[data-testid="stSidebar"] .stButton > button {
  width:100%; justify-content:flex-start !important; text-align:left !important;
  background:transparent !important; border:0 !important; color:var(--ink) !important;
  font-weight:600 !important; font-size:.905rem !important;
  padding:.62rem .8rem !important; border-radius:var(--radius-sm) !important;
  box-shadow:none !important; margin-bottom:2px; position:relative;
  transition:background .14s ease, color .14s ease;
}
section[data-testid="stSidebar"] .stButton > button p {
  font-weight:600 !important; font-size:.885rem !important; margin:0 !important;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
section[data-testid="stSidebar"] .stButton > button:hover {
  background:var(--card-2) !important; color:var(--brand) !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background:var(--brand-soft) !important; color:var(--brand) !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"] p {
  color:var(--brand) !important; font-weight:700 !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"]::before {
  content:""; position:absolute; left:0; top:18%; bottom:18%;
  width:3.5px; border-radius:0 4px 4px 0; background:var(--brand);
}

.qrs-help-card {
  background:linear-gradient(160deg,var(--brand-soft),$help_card_to);
  border:1px solid $help_card_bd; border-radius:var(--radius);
  padding:15px 16px; margin-top:16px;
}
.qrs-help-card .t { font-weight:800; font-size:.86rem; color:var(--ink); }
.qrs-help-card .d { font-size:.74rem; color:var(--muted); margin-top:4px; line-height:1.5; }
section[data-testid="stSidebar"] .st-key-nav_help_cta button {
  background:var(--card) !important; border:1px solid $drop_bd !important;
  color:var(--brand) !important; justify-content:center !important;
  text-align:center !important; margin-top:9px;
}
section[data-testid="stSidebar"] .st-key-nav_help_cta button p {
  color:var(--brand) !important; font-weight:700 !important;
}
section[data-testid="stSidebar"] .st-key-nav_help_cta button:hover {
  background:var(--brand-soft) !important;
}
.qrs-foot {
  display:flex; align-items:center; gap:10px; margin-top:16px; padding:11px 10px;
  border-top:1px solid var(--border);
}
.qrs-foot .av {
  width:34px; height:34px; border-radius:11px; flex:0 0 34px;
  background:linear-gradient(145deg,var(--brand-lt),var(--brand)); color:#fff;
  display:flex; align-items:center; justify-content:center; font-weight:800; font-size:.8rem;
}
.qrs-foot .n { font-size:.8rem; font-weight:700; color:var(--ink); line-height:1.2; }
.qrs-foot .s { font-size:.68rem; color:var(--muted); margin-top:1px; }

/* ====================================================================
   Top bar
   ==================================================================== */
.qrs-topbar { display:flex; align-items:center; gap:14px; margin:0 0 4px; }
.qrs-crumb { font-size:.74rem; color:var(--muted); font-weight:600; letter-spacing:.01em; }
.qrs-crumb b { color:var(--ink); font-weight:700; }
.qrs-page-title { font-size:1.55rem; font-weight:800; margin:2px 0 2px; letter-spacing:-.02em; }
.qrs-page-sub { color:var(--muted); font-size:.87rem; margin-bottom:14px; }

/* ====================================================================
   Hero
   ==================================================================== */
.qrs-hero {
  position:relative; overflow:hidden;
  background:
    radial-gradient(760px 300px at 88% -35%, $hero_blob1 0%, transparent 62%),
    radial-gradient(520px 260px at 62% 130%, $hero_blob2 0%, transparent 60%),
    linear-gradient(100deg, $hero_a 0%, $hero_b 55%, $hero_c 100%);
  border:1px solid $hero_bd; border-radius:22px;
  padding:30px 34px; margin-bottom:20px;
}
.qrs-hero .eyebrow {
  font-size:.70rem; font-weight:800; letter-spacing:.13em; text-transform:uppercase;
  color:var(--brand); margin-bottom:9px;
}
.qrs-hero h1 {
  font-size:2.0rem; font-weight:800; margin:0; color:var(--ink); letter-spacing:-.03em;
  line-height:1.16;
}
.qrs-hero h1 .accent { color:var(--brand); }
.qrs-hero p { color:$hero_text; margin:.6rem 0 0; font-size:.95rem; max-width:62ch; line-height:1.6; }
.qrs-hero .chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }
.qrs-hero .chip {
  background:$chip_bg; border:1px solid $chip_bd; color:var(--ink);
  border-radius:999px; padding:6px 13px; font-size:.75rem; font-weight:600;
}
.qrs-hero .art {
  position:absolute; right:30px; top:50%; transform:translateY(-50%);
  font-size:5.4rem; opacity:.20; line-height:1; pointer-events:none; user-select:none;
}

/* ====================================================================
   Stat cards
   ==================================================================== */
.qrs-kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(178px,1fr)); gap:13px; margin-bottom:6px; }
.qrs-kpi {
  background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
  padding:16px 17px; box-shadow:var(--shadow-1); transition:box-shadow .16s ease, transform .16s ease;
}
.qrs-kpi:hover { box-shadow:var(--shadow-2); transform:translateY(-1px); }
.qrs-kpi .ico {
  width:38px; height:38px; border-radius:11px; display:flex; align-items:center;
  justify-content:center; font-size:18px; margin-bottom:11px;
}
.qrs-kpi .v { font-size:1.72rem; font-weight:800; line-height:1.08; letter-spacing:-.025em; white-space:nowrap; }
.qrs-kpi .l { color:var(--muted); font-size:.795rem; margin-top:3px; font-weight:600; }
.qrs-kpi .s { color:var(--muted); font-size:.71rem; margin-top:7px; white-space:nowrap;
              overflow:hidden; text-overflow:ellipsis; }
.qrs-kpi .s .up { color:var(--ok); font-weight:700; }
.qrs-kpi .s .down { color:var(--bad); font-weight:700; }

/* Four-across inside a narrow column: shrink the number so the whole value
   stays readable instead of being clipped to "9…". */
.qrs-kpis.c4 { grid-template-columns:repeat(4,minmax(0,1fr)); }
.qrs-kpis.c5 { grid-template-columns:repeat(5,minmax(0,1fr)); }
.qrs-kpis.c6 { grid-template-columns:repeat(6,minmax(0,1fr)); }
@media (max-width:1450px) {
  .qrs-kpis.c6 { grid-template-columns:repeat(3,minmax(0,1fr)); }
  .qrs-kpis.c5 { grid-template-columns:repeat(3,minmax(0,1fr)); }
}
@media (max-width:1050px) {
  .qrs-kpis.c4, .qrs-kpis.c5, .qrs-kpis.c6 { grid-template-columns:repeat(2,minmax(0,1fr)); }
}
.qrs-kpis.tight { grid-template-columns:repeat(auto-fit,minmax(108px,1fr)); gap:9px; }
.qrs-kpis.tight .qrs-kpi { padding:11px 12px; }
.qrs-kpi.small .v { font-size:1.06rem; }
.qrs-kpi.small .l { font-size:.665rem; margin-top:2px; }
.qrs-kpi.small .s { font-size:.635rem; margin-top:3px; }

/* ====================================================================
   Panels, section heads, cards
   ==================================================================== */
.qrs-panel {
  background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
  padding:18px 20px; box-shadow:var(--shadow-1); margin-bottom:14px;
}
.qrs-card {
  background:var(--card); border:1px solid var(--border); border-radius:var(--radius-sm);
  padding:15px 17px; box-shadow:var(--shadow-1); margin-bottom:12px;
}
.qrs-bar {
  display:flex; align-items:center; gap:10px;
  font-size:1.0rem; font-weight:800; color:var(--ink);
  letter-spacing:-.015em; margin:20px 0 11px;
}
.qrs-bar::before {
  content:""; width:4px; height:17px; border-radius:3px;
  background:linear-gradient(180deg,var(--brand-lt),var(--brand)); flex:0 0 4px;
}
.qrs-bar .sub { font-size:.775rem; font-weight:500; color:var(--muted); letter-spacing:0; }

/* ====================================================================
   Messages
   ==================================================================== */
.qrs-note, .qrs-ok, .qrs-info {
  border-radius:var(--radius-sm); padding:12px 15px; font-size:.845rem;
  margin:9px 0; line-height:1.55; border:1px solid transparent;
}
.qrs-note { background:var(--warn-soft); border-color:$warn_bd; color:$warn_ink; }
.qrs-ok   { background:var(--ok-soft);   border-color:$ok_bd;   color:$ok_ink; }
.qrs-info { background:var(--info-soft); border-color:$info_bd; color:$info_ink; }

/* ====================================================================
   Stepper
   ==================================================================== */
.qrs-steps {
  display:flex; align-items:center; background:var(--card); border:1px solid var(--border);
  border-radius:var(--radius); padding:15px 20px; margin:0 0 18px; box-shadow:var(--shadow-1);
  overflow-x:auto;
}
.qrs-steps .st { display:flex; align-items:center; gap:9px; white-space:nowrap; }
.qrs-steps .dot {
  width:27px; height:27px; border-radius:50%; flex:0 0 27px;
  display:flex; align-items:center; justify-content:center;
  font-size:.76rem; font-weight:800; border:1.5px solid var(--border);
  background:var(--card-2); color:var(--muted);
}
.qrs-steps .st.active .dot {
  background:linear-gradient(145deg,var(--brand-lt),var(--brand)); color:#fff;
  border-color:transparent; box-shadow:0 5px 12px -5px $brand_glow;
}
.qrs-steps .st.done .dot { background:var(--ok-soft); color:var(--ok); border-color:$ok_bd; }
.qrs-steps .st .lb { font-size:.80rem; font-weight:600; color:var(--muted); }
.qrs-steps .st.active .lb { color:var(--brand); font-weight:700; }
.qrs-steps .st.done .lb { color:var(--ink); }
.qrs-steps .line { flex:1 1 20px; height:2px; background:var(--border); margin:0 13px; border-radius:2px; min-width:14px; }
.qrs-steps .line.done { background:$ok_bd; }

/* ====================================================================
   Ranked performers
   ==================================================================== */
.qrs-rank { display:flex; align-items:center; gap:12px; padding:11px 0; border-bottom:1px solid var(--grid); }
.qrs-rank:last-child { border-bottom:0; }
.qrs-rank .badge {
  width:31px; height:31px; border-radius:50%; flex:0 0 31px; display:flex;
  align-items:center; justify-content:center; font-weight:800; font-size:.79rem; color:#fff;
}
.qrs-rank .body { flex:1 1 auto; min-width:0; }
.qrs-rank .nm {
  font-weight:700; font-size:.885rem; color:var(--ink);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.qrs-rank .mt { font-size:.715rem; color:var(--muted); margin-top:1px; }
.qrs-rank .meter { height:5px; border-radius:3px; background:var(--grid); margin-top:7px; overflow:hidden; }
.qrs-rank .meter i { display:block; height:100%; border-radius:3px;
                     background:linear-gradient(90deg,var(--brand-lt),var(--brand)); }
.qrs-rank .sc { font-weight:800; font-size:.96rem; flex:0 0 auto; letter-spacing:-.02em; }

/* ====================================================================
   Insight + quick-action tiles
   ==================================================================== */
.qrs-ins { display:grid; grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); gap:12px; }
.qrs-ins .it {
  background:var(--card-2); border:1px solid var(--border); border-radius:var(--radius-sm);
  padding:14px 15px;
}
.qrs-ins .it .v { font-size:1.28rem; font-weight:800; letter-spacing:-.02em; }
.qrs-ins .it .t { font-size:.755rem; color:var(--muted); margin-top:5px; line-height:1.5; }

.qrs-quick { display:grid; grid-template-columns:repeat(auto-fit,minmax(196px,1fr)); gap:12px; }
.qrs-qa {
  display:flex; align-items:center; gap:12px; padding:15px 16px;
  border:1px solid var(--border); border-radius:var(--radius-sm); background:var(--card-2);
}
.qrs-qa .ico {
  width:40px; height:40px; border-radius:12px; flex:0 0 40px; font-size:19px;
  display:flex; align-items:center; justify-content:center;
}
.qrs-qa .t { font-weight:700; font-size:.875rem; color:var(--ink); }
.qrs-qa .d { font-size:.72rem; color:var(--muted); margin-top:2px; }

/* ====================================================================
   Pills + tables
   ==================================================================== */
.qrs-pill {
  display:inline-flex; align-items:center; gap:6px; border-radius:999px;
  padding:3px 10px; font-size:.70rem; font-weight:700; letter-spacing:.01em;
}
.qrs-pill::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor; }

.qrs-table {
  width:100%; border-collapse:collapse; font-size:.795rem; background:var(--card);
  border:1px solid var(--border); border-radius:var(--radius-sm); overflow:hidden;
  table-layout:fixed;
}
.qrs-table th {
  background:var(--card-2); color:var(--muted); text-align:left; padding:9px 11px;
  font-size:.695rem; font-weight:700; letter-spacing:.055em; text-transform:uppercase;
  border-bottom:1px solid var(--border);
}
.qrs-table td { padding:9px 11px; border-top:1px solid var(--grid); color:var(--ink);
                overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.qrs-table th.num, .qrs-table td.num { text-align:right; width:72px; }
.qrs-table tr:hover td { background:var(--card-2); }

/* Keep dataframes inside their column instead of scrolling sideways. */
div[data-testid="stDataFrame"] { width:100% !important; }
div[data-testid="stDataFrame"] table { table-layout:fixed; width:100% !important; }
div[data-testid="stDataFrame"] > div { border-radius:var(--radius-sm); border-color:var(--border) !important; }

/* Charts rendered by matplotlib carry their own light background. Keeping them
   on an explicit plate means they still read correctly in dark mode instead of
   floating as a bright rectangle with no edge. */
/* Every chart is a matplotlib PNG drawn on white. Giving the <img> its own
   white plate means it still reads as a chart in dark mode instead of a bare
   bright rectangle, and is invisible against a white card in light mode. */
.qrs-plate { background:#fff; border:1px solid var(--border); border-radius:var(--radius-sm);
             padding:9px 10px; margin:2px 0 4px; }
[data-testid="stImage"] img { background:#fff; border-radius:10px; padding:6px; }

/* ====================================================================
   Streamlit controls
   ==================================================================== */
[data-testid="stMain"] .stButton > button,
[data-testid="stMain"] button[kind="secondaryFormSubmit"],
[data-testid="stMain"] button[kind="tertiary"] {
  border-radius:var(--radius-xs) !important; font-weight:650 !important;
  font-size:.865rem !important; padding:.54rem 1.05rem !important;
  border:1px solid var(--border) !important; background:var(--card) !important;
  color:var(--ink) !important; box-shadow:var(--shadow-1) !important;
  transition:border-color .14s ease, color .14s ease, background .14s ease;
}
[data-testid="stMain"] .stButton > button:hover:not(:disabled),
[data-testid="stMain"] button[kind="secondaryFormSubmit"]:hover:not(:disabled),
[data-testid="stMain"] button[kind="tertiary"]:hover:not(:disabled) {
  border-color:var(--brand) !important; color:var(--brand) !important;
}
[data-testid="stMain"] .stButton > button[kind="primary"],
[data-testid="stMain"] button[kind="primaryFormSubmit"],
[data-testid="stMain"] .stDownloadButton > button[kind="primary"] {
  background:linear-gradient(140deg,var(--brand-lt) -25%,var(--brand) 60%) !important;
  border:0 !important; color:#fff !important; font-weight:700 !important;
  box-shadow:0 6px 16px -7px $brand_glow !important;
}
[data-testid="stMain"] .stButton > button[kind="primary"]:hover:not(:disabled),
[data-testid="stMain"] button[kind="primaryFormSubmit"]:hover:not(:disabled) {
  filter:brightness(1.05); color:#fff !important;
}
[data-testid="stMain"] .stButton > button:disabled,
[data-testid="stMain"] .stDownloadButton > button:disabled { opacity:.5; }

[data-testid="stMain"] .stDownloadButton > button {
  border-radius:var(--radius-xs) !important; font-weight:650 !important;
  border:1px solid var(--border) !important; background:var(--card) !important;
  color:var(--ink) !important; box-shadow:var(--shadow-1) !important;
  padding:.54rem 1.05rem !important;
}
[data-testid="stMain"] .stDownloadButton > button:hover:not(:disabled) {
  border-color:var(--brand) !important; color:var(--brand) !important;
}

/* Inputs */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
div[data-baseweb="select"] > div, div[data-baseweb="input"],
[data-testid="stSelectbox"] > div > div,
[data-testid="stMultiSelect"] > div > div,
[data-testid="stTextInput"] > div > div,
[data-testid="stNumberInput"] > div > div,
[data-testid="stDateInput"] > div > div {
  border-radius:var(--radius-xs) !important; border-color:var(--border) !important;
  background:var(--card) !important; color:var(--ink) !important;
  font-family:var(--ui) !important;
}
/* Dropdown menus are portalled out of the widget, so they need naming too. */
[data-baseweb="popover"] [role="listbox"], ul[role="listbox"],
[data-baseweb="menu"], [data-baseweb="popover"] > div > div {
  background:var(--card) !important; color:var(--ink) !important;
  border:1px solid var(--border) !important; border-radius:var(--radius-xs) !important;
}
li[role="option"] { color:var(--ink) !important; }
li[role="option"]:hover, li[role="option"][aria-selected="true"] {
  background:var(--brand-soft) !important; color:var(--brand) !important;
}
.stApp input, .stApp textarea,
[data-testid="stSelectbox"] div, [data-testid="stMultiSelect"] input {
  color:var(--ink) !important;
}
.stApp input::placeholder, .stApp textarea::placeholder {
  color:var(--muted) !important; opacity:1;
}
[data-testid="stFileUploaderDropzoneInstructions"],
[data-testid="stFileUploaderDropzoneInstructions"] * { color:var(--muted) !important; }
[data-testid="stFileUploaderFile"], [data-testid="stFileUploaderFile"] * {
  color:var(--ink) !important;
}
.stTextInput input:focus, .stNumberInput input:focus { border-color:var(--brand) !important; }
div[data-baseweb="select"] > div:focus-within { border-color:var(--brand) !important;
  box-shadow:0 0 0 3px $brand_ring !important; }
.stApp label, .stApp [data-testid="stWidgetLabel"] p {
  font-size:.80rem !important; font-weight:600 !important; color:var(--ink) !important;
}
span[data-baseweb="tag"] { border-radius:7px !important; font-weight:600 !important; }
.stCheckbox [data-testid="stWidgetLabel"] p { font-weight:500 !important; }

/* File uploader as a dropzone card */
[data-testid="stFileUploaderDropzone"], section[data-testid="stFileUploadDropzone"] {
  background:var(--brand-soft) !important;
  border:1.6px dashed $drop_bd !important; border-radius:var(--radius) !important;
  padding:20px 18px !important;
}
[data-testid="stFileUploaderDropzone"]:hover { border-color:var(--brand) !important; }
[data-testid="stFileUploaderDropzone"] button,
section[data-testid="stFileUploadDropzone"] button {
  background:linear-gradient(140deg,var(--brand-lt) -25%,var(--brand) 60%) !important;
  color:#fff !important; border:0 !important; font-weight:700 !important;
  border-radius:var(--radius-xs) !important;
}
[data-testid="stFileUploaderFile"] {
  background:var(--card); border:1px solid var(--border);
  border-radius:var(--radius-xs); padding:8px 11px; margin-top:7px;
}

/* Expanders read as cards, not as grey accordions. */
[data-testid="stExpander"] {
  border:1px solid var(--border) !important; border-radius:var(--radius) !important;
  background:var(--card) !important; box-shadow:var(--shadow-1); overflow:hidden;
  margin-bottom:12px;
}
[data-testid="stExpander"] summary, [data-testid="stExpander"] details > summary {
  font-weight:700 !important; font-size:.885rem !important; padding:13px 17px !important;
  background:var(--card) !important; color:var(--ink) !important;
}
[data-testid="stExpander"] summary:hover { color:var(--brand) !important; }
[data-testid="stExpander"] [data-testid="stExpanderDetails"] { padding:0 17px 14px; }

/* Bordered containers match the panel language. */
[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] { gap:.55rem; }
div[data-testid="stForm"] {
  border:1px solid var(--border) !important; border-radius:var(--radius) !important;
  background:var(--card) !important; padding:19px 21px !important; box-shadow:var(--shadow-1);
}

/* Tabs — light pills with a brand underline. */
.stTabs [data-baseweb="tab-list"] {
  gap:4px; border-bottom:1px solid var(--border); background:transparent; padding-bottom:0;
}
.stTabs [data-baseweb="tab"] {
  background:transparent; border-radius:var(--radius-xs) var(--radius-xs) 0 0;
  padding:10px 17px; font-weight:650; font-size:.86rem; color:var(--muted);
}
.stTabs [data-baseweb="tab"]:hover { color:var(--brand); background:var(--card-2); }
.stTabs [aria-selected="true"] { color:var(--brand) !important; background:var(--card) !important; }
.stTabs [data-baseweb="tab-highlight"] { background:var(--brand) !important; height:2.5px; }
.stTabs [data-baseweb="tab-border"] { background:var(--border); }

/* Streamlit's stock alerts, kept on-palette for the few places they are used. */
[data-testid="stAlert"] { border-radius:var(--radius-sm) !important; border:1px solid var(--border); }

hr, [data-testid="stDivider"] hr { border-color:var(--border) !important; }
[data-testid="stCaptionContainer"] p, .stCaption, .stApp small {
  color:var(--muted) !important; font-size:.765rem !important;
}

/* ====================================================================
   Sticky progress strip
   ====================================================================
   A sticky element can only travel inside its own parent, and st.empty()
   wraps the bar in a container exactly as tall as the bar itself — so
   sticking the bar directly just scrolls it away. The ELEMENT CONTAINER is
   made sticky instead: its parent is the page-length vertical block, which
   gives it the full height of the page to stick against.

   `:has()` scopes the rule to our own bar and never to some other first
   element on the page. */
[data-testid="stMain"] [data-testid="stElementContainer"]:has(.qrs-sticky),
[data-testid="stMain"] .element-container:has(.qrs-sticky),
section.main .element-container:has(.qrs-sticky) {
  position:sticky !important; top:0; z-index:1000001; background:var(--page);
}
.qrs-sticky { background:var(--page); padding:7px 0 9px; margin:0; }

/* Fallback for browsers without :has() — the rule above cannot match there,
   so the bar is pinned with `fixed` instead. The spacer keeps the page from
   sliding underneath it. */
@supports not selector(:has(*)) {
  .qrs-sticky { position:fixed; top:0; left:0; right:0; z-index:1000001; padding:7px 18px; }
  .qrs-spacer { display:block; height:40px; }
}
.qrs-spacer { display:none; }
.qrs-track {
  height:28px; border-radius:var(--radius-xs); background:var(--card-2); overflow:hidden;
  border:1px solid var(--border); position:relative;
}
.qrs-fill {
  height:100%; background:linear-gradient(90deg,var(--brand-lt),var(--brand));
  transition:width .25s ease;
}
.qrs-fill.done { background:linear-gradient(90deg,$ok_lt,var(--ok)); }
.qrs-track span {
  position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
  font-size:.755rem; font-weight:700; letter-spacing:.03em; line-height:1; color:var(--ink);
}
.qrs-track span.on { color:#fff; }

/* ====================================================================
   Responsive
   ==================================================================== */
@media (max-width: 900px) {
  .qrs-hero { padding:22px 20px; }
  .qrs-hero h1 { font-size:1.55rem; }
  .qrs-hero .art { display:none; }
  .block-container { padding-left:1rem !important; padding-right:1rem !important; }
}
</style>
""")


def app_css(dark=False):
    """
    The whole stylesheet, as one <style> block.

    `dark` swaps the surface and ink tokens only. Every accent keeps its hue so
    a green score stays green, and chart plates stay light because the charts
    themselves are matplotlib PNGs drawn on white.
    """
    if dark:
        page, card, card2 = "12141B", "1A1D26", "232733"
        ink, muted, border, grid = "F2F4F8", "9AA3B4", "2C313D", "262B36"
        brand_soft = "2A1C16"
        hero_a, hero_b, hero_c = "231A16", "1E1B20", "1A1D26"
        hero_bd, hero_text = "33261F", "C4CBD8"
        chip_bg, chip_bd = "rgba(255,255,255,.06)", "rgba(255,255,255,.10)"
        blob1, blob2 = rgba(BRAND, .16), rgba(BRAND_LT, .10)
        sh1, sh2 = "rgba(0,0,0,.40)", "rgba(0,0,0,.55)"
        help_to, help_bd = "1E1B20", "33261F"
        tint = 0.78            # accents on a dark surface need a deeper tint
        ink_shift = 0.30       # message text is lightened instead of darkened
    else:
        page, card, card2 = PAGE_BG, CARD_BG, "F7F8FB"
        ink, muted, border, grid = TEXT, TEXT_MUTED, BORDER, GRID
        brand_soft = BRAND_SOFT
        hero_a, hero_b, hero_c = "FFF4EE", "FFF7F2", "FDF6F1"
        hero_bd, hero_text = "FAE3D7", "5C6373"
        chip_bg, chip_bd = "rgba(255,255,255,.72)", "rgba(244,81,30,.16)"
        blob1, blob2 = rgba(BRAND, .13), rgba(BRAND_LT, .10)
        sh1, sh2 = "rgba(16,24,40,.05)", "rgba(16,24,40,.18)"
        help_to, help_bd = "FFFBF8", "FAE3D7"
        tint = 0.90
        ink_shift = 0.0

    def _soft(c):
        return hx(mix(c, page if dark else WHITE, tint))

    def _bd(c):
        return hx(mix(c, page if dark else WHITE, tint - 0.22))

    def _ink(c):
        return hx(mix(c, WHITE if dark else "0B0D12", 0.42 if dark else 0.55)) \
            if ink_shift else hx(mix(c, "0B0D12", 0.45))

    return _CSS.substitute(
        brand=hx(BRAND), brand_dk=hx(BRAND_DK), brand_lt=hx(BRAND_LT),
        brand_soft=hx(brand_soft), brand_glow=rgba(BRAND, .55), brand_ring=rgba(BRAND, .18),
        green=hx(GREEN), red=hx(RED), amber=hx(ORANGE), blue=hx(BLUE),
        teal=hx(TEAL), purple=hx(PURPLE),
        ok_soft=_soft(GREEN), bad_soft=_soft(RED), warn_soft=_soft(ORANGE),
        info_soft=_soft(BLUE),
        ok_bd=_bd(GREEN), warn_bd=_bd(ORANGE), info_bd=_bd(BLUE),
        ok_ink=_ink(GREEN), warn_ink=_ink(ORANGE), info_ink=_ink(BLUE),
        ok_lt=hx(mix(GREEN, WHITE, .28)),
        drop_bd=hx(mix(BRAND, page if dark else WHITE, .55)),
        page=hx(page), card=hx(card), card2=hx(card2),
        ink=hx(ink), muted=hx(muted), border=hx(border), grid=hx(grid),
        sh1=sh1, sh2=sh2,
        hero_a=hx(hero_a), hero_b=hx(hero_b), hero_c=hx(hero_c),
        hero_bd=hx(hero_bd), hero_text=hx(hero_text),
        hero_blob1=blob1, hero_blob2=blob2,
        chip_bg=chip_bg, chip_bd=chip_bd,
        help_card_to=hx(help_to), help_card_bd=hx(help_bd),
        font_ui=FONT_UI,
    )
