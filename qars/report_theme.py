"""
The palette of the generated report — the PPTX, the PDF and the charts in them.

White pages, near-black type, hairline rules and one restrained navy accent.
Nothing is a block of brand colour: a report gets forwarded, projected and
printed by people who never see the app, and it should read as a document, not
as a screen. Colour is kept for what it means — green for error free, red for
defects, amber for a score to watch — and is slightly deeper than on screen so
it survives a projector and a black-and-white printer.

Kept apart from theme.py, which styles the app, so the two can change
independently. It exposes the same names, so charts.py draws with either:
`charts.quality_trend(rows, pal=report_theme)`.

Nothing in this module touches the network or the disk.
"""

from . import theme as _app

# Type faces, score bands and the colour helpers are the app's own: only the
# colours differ between the screen and the page.
FONT_HEAD, FONT_BODY = _app.FONT_HEAD, _app.FONT_BODY
BAND_GOOD, BAND_OK = _app.BAND_GOOD, _app.BAND_OK
hx, mix, soft, rgba, score_band = _app.hx, _app.mix, _app.soft, _app.rgba, _app.score_band

# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------
WHITE = "FFFFFF"
PAGE_BG = "FFFFFF"   # the page itself is white, not a tinted canvas
CARD_BG = "FFFFFF"
INK = "111827"   # titles
TEXT = "1F2937"   # body
TEXT_MUTED = "6B7280"
BORDER = "D5DAE3"   # hairlines round panels and tables
GRID = "E9EDF2"
ROW_ALT = "F7F9FB"
FILL = "EEF1F5"   # table header rows and quiet tiles

# --------------------------------------------------------------------------
# The one accent. Used for rules, panel headings and the leading data series.
#
# NAVY / NAVY_DK / BRAND keep the names the builders and the charts already
# use for "the report's own colour", so nothing else has to know it changed.
# --------------------------------------------------------------------------
ACCENT = "1F3A5F"
ACCENT_DK = "16293F"
ACCENT_SOFT = "E8EDF4"
NAVY = ACCENT
NAVY_DK = ACCENT_DK
BRAND = ACCENT
BRAND_DK = ACCENT_DK
BRAND_DP = ACCENT_DK
BRAND_LT = "8FA6C4"
BRAND_SOFT = ACCENT_SOFT

# --------------------------------------------------------------------------
# Data colours
# --------------------------------------------------------------------------
BLUE = "2F5F9E"   # audited volume
BLUE_LT = "8FB0D9"
GREEN = "1E7F4F"   # error free
RED = "B42318"   # defects
ORANGE = "8F6B00"   # amber: observations and scores to watch — a gold, never an orange
PURPLE = "6B4FA3"   # developer counts
TEAL = "0F766E"   # observations / average score
GOLD = "B8860B"   # rank 1
SILVER = "8A94A6"   # rank 2
BRONZE = "8C6239"   # rank 3

ACCENTS = [BLUE, GREEN, RED, ORANGE, ACCENT, PURPLE, TEAL]

# Fixed colour per defect category so a category keeps its colour everywhere.
CATEGORY_COLORS = {
    "Content Related": ACCENT,
    "Design Related": BLUE,
    "Redirect Links": TEAL,
    "Navigation Related": PURPLE,
    "Image Related": "4B9CA6",
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
    "Major": ORANGE,
    "Minor": BLUE,
    "Cosmetic": TEAL,
    "Unspecified": SILVER,
}


def score_color(score):
    """Green at/above 95, amber 90-95, red below 90. `None` -> muted grey."""
    if score is None:
        return TEXT_MUTED
    if score >= BAND_GOOD:
        return GREEN
    if score >= BAND_OK:
        return ORANGE
    return RED
