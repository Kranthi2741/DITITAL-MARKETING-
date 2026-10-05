"""
Compositor agent — overlays a structured infographic layout on the AI-generated
background image, producing a publish-ready social post.

Key fixes:
- No emoji (PIL can't render them) — uses clean text bullet symbols instead
- Strips LLM placeholder text like [Product Name], [Number], [Website]
- Clips all text to canvas width — no overflow
- Skips overlay for prompts that don't need infographic layout (sports, celebrations, etc.)
- No duplicate tagline
"""

import os
import re
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.state import CampaignState
from app.agents.asset_library import update_composed_image

OUTPUT_DIR    = Path("generated_images")
_SETTINGS_PATH = Path("app_data") / "settings.json"
_DEFAULT_LOGO  = Path("assets") / "prorithm_logo.png"


def _load_brand() -> dict:
    """Load brand kit from saved settings, falling back to proRITHM defaults."""
    try:
        if _SETTINGS_PATH.exists():
            return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}

# Prompts that produce great standalone photos — skip infographic overlay
_SKIP_OVERLAY_KEYWORDS = (
    "cricket", "football", "sport", "match", "tournament", "team", "player",
    "birthday", "anniversary", "celebration", "congratulation", "wedding",
    "festival photo", "diwali photo", "holi photo",
)

# Bullet symbols PIL can render with standard fonts
BULLET  = "+"
DOT     = "*"
ARROW   = ">"
DIAMOND = "#"


# ── font helpers ──────────────────────────────────────────────────────────────

def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ── colour helpers ───────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str, fallback: tuple) -> tuple:
    """Convert #RRGGBB to (R, G, B), returning fallback on any error."""
    try:
        h = hex_color.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        return fallback


def _build_palette(settings: dict) -> dict:
    """Build the colour palette from saved brand settings."""
    primary  = _hex_to_rgb(settings.get("brand_primary_color", ""), (40, 62, 83))
    accent   = _hex_to_rgb(settings.get("brand_accent_color",  ""), (237, 50, 55))
    cta      = _hex_to_rgb(settings.get("brand_cta_color",     ""), (197, 34, 43))
    white    = (255, 255, 255)
    off_white = (230, 245, 255)
    light_blue = (180, 220, 255)
    slate    = (83, 103, 121)
    return {
        "NAVY":       primary,
        "RED":        accent,
        "ACTION_RED": cta,
        "WHITE":      white,
        "OFF_WHITE":  off_white,
        "LIGHT_BLUE": light_blue,
        "ACCENT_BLUE": accent,
        "PANEL_BG":   (*primary, 220),
        "DIVIDER":    (*slate, 180),
        "DARK_BAR":   (max(0, primary[0]-20), max(0, primary[1]-27), max(0, primary[2]-33), 240),
    }


# ── logo helper ──────────────────────────────────────────────────────────────

def _paste_logo(base: Image.Image, settings: dict, campaign_type: str, is_overlay: bool) -> Image.Image:
    """
    Composite the brand logo onto base (RGBA).

    Sizing rules (adaptive):
      - overlay images  : logo in top-bar area, right-aligned, height=70px
      - standalone photo: logo bottom-right corner, height=90px, semi-transparent
      - awareness       : logo top-right, height=80px
    """
    logo_path = settings.get("brand_logo_path", "")
    candidates = [logo_path, str(_DEFAULT_LOGO)]
    logo_file  = next((p for p in candidates if p and Path(p).exists()), None)
    if not logo_file:
        return base

    SIZE = base.width  # always 1080
    PAD  = 36

    try:
        with Image.open(logo_file) as raw:
            logo = raw.convert("RGBA")
    except Exception:
        return base

    # Choose target height based on context
    if is_overlay and campaign_type == "event":
        target_h = 64
    elif is_overlay:
        target_h = 70
    else:
        target_h = 90   # standalone photo — bigger, bottom-right

    # Scale preserving aspect ratio
    aspect   = logo.width / logo.height
    target_w = int(target_h * aspect)
    logo     = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Opacity: full for overlay images, 80% for standalone photos
    if not is_overlay:
        alpha = logo.split()[3].point(lambda p: int(p * 0.82))
        logo.putalpha(alpha)

    # Position
    if is_overlay:
        # Right side of the top bar, vertically centred in 90px bar
        x = SIZE - target_w - PAD
        y = (90 - target_h) // 2
    else:
        # Bottom-right corner for standalone photos
        x = SIZE - target_w - PAD
        y = SIZE - target_h - PAD

    base.paste(logo, (x, y), logo)
    return base


# ── helpers ───────────────────────────────────────────────────────────────────

def _rrect(draw: ImageDraw.ImageDraw, xy, radius: int, fill, outline=None, width=2):
    draw.rounded_rectangle(list(xy), radius=radius, fill=fill, outline=outline, width=width)


def _clean(text: str, max_len: int = 999) -> str:
    """Strip LLM placeholder brackets like [Product Name], [Number], [Website]."""
    text = re.sub(r"\[.*?\]", "", text).strip(" .,|")
    return text[:max_len]


def _fit(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    """Truncate text with ellipsis so it never exceeds max_width pixels."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "...", font=font) > max_width:
        text = text[:-1]
    return text + "..."


# ── campaign type detection ───────────────────────────────────────────────────

def _needs_overlay(state: CampaignState) -> bool:
    """Return False for prompts that produce great standalone photos."""
    prompt   = (state.get("user_prompt") or "").lower()
    festival = (state.get("campaign_plan", {}).get("festival") or "").lower()
    combined = prompt + " " + festival
    return not any(k in combined for k in _SKIP_OVERLAY_KEYWORDS)


def _campaign_type(state: CampaignState) -> str:
    prompt   = (state.get("user_prompt") or "").lower()
    festival = (state.get("campaign_plan", {}).get("festival") or "").lower()
    combined = prompt + " " + festival
    if any(k in combined for k in ("conference", "summit", "expo", "imc", "event",
                                    "participation", "booth", "demo", "launch", "meetup")):
        return "event"
    if any(k in combined for k in ("day", "health", "awareness", "world", "cancer",
                                    "heart", "lung", "liver", "kidney", "diabetes", "mental")):
        return "awareness"
    return "generic"


# ── dynamic content extractors ────────────────────────────────────────────────

def _brand_tagline(state: CampaignState) -> str:
    profile = state.get("business_profile", {})
    raw = (profile.get("tagline") or profile.get("slogan")
           or state.get("campaign_plan", {}).get("objective", ""))
    return _clean(raw, 55)


def _event_details(state: CampaignState) -> list[tuple[str, str]]:
    plan      = state.get("campaign_plan", {})
    costar    = state.get("costar_brief", {})
    strategy  = state.get("marketing_strategy", {})
    scheduled = _clean(state.get("scheduled_date") or "")

    # Extract a real location word from context — skip generic words
    context  = _clean(costar.get("context", "") or plan.get("objective", ""))
    skip     = {"This", "That", "With", "From", "Join", "The", "Our", "Your",
                "Announce", "Participation", "Invite", "Attendees"}
    location = next((w for w in context.split()
                     if w.istitle() and len(w) > 3 and w not in skip), "")

    cta_detail = _clean(strategy.get("content_type", "") or "Celebrate together", 35)

    details = []
    if scheduled:
        details.append((BULLET, scheduled))
    if location:
        details.append((DOT, location[:30]))
    details.append((ARROW, cta_detail))

    while len(details) < 3:
        details.append((DIAMOND, _clean(plan.get("objective", "Learn more"), 30)))
    return details[:3]


def _feature_items(state: CampaignState, campaign_type: str) -> list[tuple[str, str]]:
    strategy = state.get("marketing_strategy", {})
    brief    = state.get("creative_brief", {})

    visual_dirs = [_clean(v, 30) for v in strategy.get("visual_direction", []) if v]
    objects     = [_clean(o, 30) for o in brief.get("objects", []) if o]
    raw_items   = [x for x in (visual_dirs + objects) if x][:4]

    keyword_labels = {
        "monitor": "Live\nMonitoring", "track": "Live\nTracking",
        "continuous": "Continuous\nCare", "real-time": "Real-Time\nData",
        "care": "Better\nCare", "coordinat": "Care\nCoordination",
        "collaborat": "Collaboration", "connect": "Connected\nCare",
        "insight": "Clinical\nInsights", "data": "Data\nDriven",
        "analytic": "Analytics", "report": "Reporting",
        "support": "Full\nSupport", "protect": "Protection",
        "innovat": "Innovation", "future": "Future\nReady",
        "health": "Health\nFocus", "heart": "Heart\nHealth",
        "lung": "Lung\nHealth", "liver": "Liver\nHealth",
        "kidney": "Kidney\nHealth", "global": "Global\nImpact",
        "award": "Award\nWinning", "product": "Product\nExcellence",
        "growth": "Growth", "scale": "Scalable",
        "people": "People\nFirst", "community": "Community",
    }

    def _label(text: str) -> str:
        t = text.lower()
        for k, v in keyword_labels.items():
            if k in t:
                return v
        words = text.strip().split()
        if len(words) <= 2:
            return text.strip()[:18]
        return words[0].capitalize() + "\n" + " ".join(words[1:3])

    if raw_items:
        return [(BULLET, _label(item)) for item in raw_items[:4]]

    if campaign_type == "event":
        return [(BULLET, "Live\nDemo"), (DOT, "Connect\nWith Us"),
                (ARROW, "See\nInsights"), (DIAMOND, "Future\nReady")]
    if campaign_type == "awareness":
        return [(BULLET, "Raise\nAwareness"), (DOT, "Global\nImpact"),
                (ARROW, "Better\nCare"), (DIAMOND, "Take\nAction")]
    return [(BULLET, "Innovate"), (DOT, "Precision"), (ARROW, "Connect"), (DIAMOND, "Grow")]


def _audience_items(state: CampaignState) -> list[tuple[str, str, str]]:
    strategy = state.get("marketing_strategy", {})
    raw      = _clean(strategy.get("target_audience", ""))
    items    = [a.strip() for a in raw.replace(" and ", ",").split(",") if a.strip()][:5]
    while len(items) < 3:
        items.append("Partners")

    def _desc(label: str) -> str:
        l = label.lower()
        if any(k in l for k in ("ceo", "founder", "executive", "director")):
            return "Strategic\ngrowth"
        if any(k in l for k in ("investor", "vc", "fund")):
            return "Scalable\nimpact"
        if any(k in l for k in ("engineer", "developer", "technical")):
            return "Build &\ninnovate"
        if any(k in l for k in ("cfo", "finance")):
            return "Operational\nefficiency"
        if any(k in l for k in ("doctor", "physician", "clinician", "medical")):
            return "Better\npatient care"
        if any(k in l for k in ("partner", "industry", "connect")):
            return "Collaborate\n& grow"
        return "Drive\nimpact"

    return [(BULLET, item[:14], _desc(item)) for item in items]


# ── section renderers ─────────────────────────────────────────────────────────

def _draw_top_bar(draw: ImageDraw.ImageDraw, state: CampaignState,
                  SIZE: int, PAD: int, fonts: dict, P: dict, settings: dict):
    plan      = state.get("campaign_plan", {})
    direction = state.get("design_direction", {})
    profile   = state.get("business_profile", {})

    _rrect(draw, (0, 0, SIZE, 90), radius=0, fill=P["DARK_BAR"])

    # Only draw text brand name if no logo file is configured
    has_logo = bool(
        (settings.get("brand_logo_path") and Path(settings["brand_logo_path"]).exists())
        or _DEFAULT_LOGO.exists()
    )
    if not has_logo:
        brand_name = _clean(settings.get("brand_name") or profile.get("name") or "proRITHM", 30)
        tagline    = _brand_tagline(state) or settings.get("brand_tagline") or "Connected Care. Real Impact."
        draw.text((PAD, 20), brand_name, font=fonts["brand"], fill=P["WHITE"])
        first_word = brand_name.split()[0] if brand_name else brand_name
        fw = int(draw.textlength(first_word, font=fonts["brand"]))
        draw.rectangle([PAD, 54, PAD + fw, 57], fill=P["RED"])
        if tagline:
            draw.text((PAD, 56), _fit(draw, tagline, fonts["tiny"], SIZE // 2 - PAD), font=fonts["tiny"], fill=P["LIGHT_BLUE"])
    else:
        # Draw tagline only (logo image will be pasted to the right by _paste_logo)
        tagline = _brand_tagline(state) or settings.get("brand_tagline") or "Connected Care. Real Impact."
        if tagline:
            draw.text((PAD, 32), _fit(draw, tagline, fonts["small"], SIZE // 2 - PAD), font=fonts["small"], fill=P["LIGHT_BLUE"])

    badge_raw = plan.get("festival") or direction.get("headline") or "Campaign"
    badge     = _clean(badge_raw, 28).upper()
    badge_w   = int(draw.textlength(badge, font=fonts["small"])) + 28
    bx        = SIZE - badge_w - PAD - (180 if has_logo else 0)  # shift badge left to make room for logo
    _rrect(draw, (bx, 14, bx + badge_w, 72), radius=8, fill=P["NAVY"], outline=P["RED"], width=2)
    draw.text((bx + 14, 26), badge, font=fonts["small"], fill=P["WHITE"])


def _fit_headline(draw: ImageDraw.ImageDraw, headline: str, fonts: dict,
                  max_width: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size_key in ("hero", "heading", "sub"):
        font  = fonts[size_key]
        words = headline.split()
        mid   = max(1, len(words) // 2)
        line1 = " ".join(words[:mid])
        line2 = " ".join(words[mid:])
        if draw.textlength(line1, font=font) <= max_width and draw.textlength(line2, font=font) <= max_width:
            return font, [line1, line2]
    font = fonts["sub"]
    return font, [headline[:40], headline[40:80]]


def _draw_hero_headline(draw: ImageDraw.ImageDraw, state: CampaignState,
                        SIZE: int, PAD: int, fonts: dict, P: dict) -> int:
    direction = state.get("design_direction", {})
    plan      = state.get("campaign_plan", {})
    brief     = state.get("creative_brief", {})
    raw       = direction.get("headline") or plan.get("festival") or plan.get("objective") or "Campaign"
    headline  = _clean(raw)

    font, lines = _fit_headline(draw, headline, fonts, SIZE - PAD * 2)
    line_h = int(font.size * 1.2)
    y = 110
    for i, line in enumerate(lines):
        if line:
            draw.text((PAD, y + i * line_h), line, font=font, fill=P["WHITE"] if i == 0 else P["ACCENT_BLUE"])
    y += len(lines) * line_h + 14

    tagline_raw = state.get("rhyming_tagline") or direction.get("supporting_copy") or brief.get("composition") or ""
    tagline     = _clean(tagline_raw, 80)
    if tagline:
        draw.text((PAD, y), _fit(draw, tagline, fonts["sub"], SIZE - PAD * 2), font=fonts["sub"], fill=P["OFF_WHITE"])
        y += 40
    return y + 10


def _draw_event_strip(draw: ImageDraw.ImageDraw, state: CampaignState,
                      SIZE: int, PAD: int, fonts: dict, y: int, P: dict) -> int:
    details = _event_details(state)
    _rrect(draw, (PAD, y, SIZE - PAD, y + 110), radius=12, fill=P["PANEL_BG"], outline=P["DIVIDER"], width=1)
    col_w = (SIZE - PAD * 2) // len(details)
    for i, (bullet, text) in enumerate(details):
        cx = PAD + i * col_w + 18
        draw.text((cx, y + 30), bullet, font=fonts["heading"], fill=P["ACCENT_BLUE"])
        draw.text((cx + 32, y + 34), _fit(draw, text, fonts["body"], col_w - 50), font=fonts["body"], fill=P["WHITE"])
        if i < len(details) - 1:
            lx = PAD + (i + 1) * col_w
            draw.line([(lx, y + 18), (lx, y + 90)], fill=P["DIVIDER"], width=1)
    return y + 126


def _draw_feature_strip(draw: ImageDraw.ImageDraw, state: CampaignState,
                        SIZE: int, PAD: int, fonts: dict, y: int,
                        campaign_type: str, P: dict) -> int:
    features = _feature_items(state, campaign_type)
    feat_w   = (SIZE - PAD * 2) // len(features)
    icon_fill = (*P["NAVY"], 200)
    for i, (bullet, label) in enumerate(features):
        fx = PAD + i * feat_w
        _rrect(draw, (fx + 10, y, fx + 70, y + 60), radius=12, fill=icon_fill)
        draw.text((fx + 24, y + 14), bullet, font=fonts["heading"], fill=P["WHITE"])
        for j, line in enumerate(label.split("\n")):
            draw.text((fx + 6, y + 68 + j * 26),
                      _fit(draw, line, fonts["small"], feat_w - 12),
                      font=fonts["small"], fill=P["LIGHT_BLUE"])
    return y + 120


def _draw_audience_section(draw: ImageDraw.ImageDraw, state: CampaignState,
                            SIZE: int, PAD: int, fonts: dict, y: int, P: dict) -> int:
    plan     = state.get("campaign_plan", {})
    audience = _audience_items(state)
    _rrect(draw, (PAD, y, SIZE - PAD, y + 160), radius=12, fill=P["PANEL_BG"], outline=P["DIVIDER"], width=1)

    obj   = _clean(plan.get("objective", "our audience"), 40)
    label = _fit(draw, f"Creating impact for {obj}", fonts["small"], SIZE - PAD * 2 - 32)
    draw.text((PAD + 16, y + 12), label, font=fonts["small"], fill=P["LIGHT_BLUE"])

    col_w = (SIZE - PAD * 2) // len(audience)
    for i, (bullet, name, desc) in enumerate(audience):
        ax = PAD + i * col_w + 8
        draw.text((ax + 18, y + 44), bullet, font=fonts["heading"], fill=P["ACCENT_BLUE"])
        draw.text((ax + 4, y + 90), _fit(draw, name, fonts["small"], col_w - 8), font=fonts["small"], fill=P["WHITE"])
        for j, line in enumerate(desc.split("\n")):
            draw.text((ax + 4, y + 116 + j * 18),
                      _fit(draw, line, fonts["tiny"], col_w - 8),
                      font=fonts["tiny"], fill=P["LIGHT_BLUE"])
    return y + 176


def _draw_cta(draw: ImageDraw.ImageDraw, state: CampaignState,
              SIZE: int, PAD: int, fonts: dict, y: int, P: dict) -> int:
    direction = state.get("design_direction", {})
    costar    = state.get("costar_brief", {})
    raw_cta   = direction.get("cta") or costar.get("response") or "Learn more"
    cta       = _clean(raw_cta, 60)
    if not cta:
        cta = "Learn more"
    _rrect(draw, (PAD, y, SIZE - PAD, y + 64), radius=32, fill=P["ACTION_RED"])
    cta_fitted = _fit(draw, cta, fonts["heading"], SIZE - PAD * 4)
    cta_w      = int(draw.textlength(cta_fitted, font=fonts["heading"]))
    draw.text(((SIZE - cta_w) // 2, y + 12), cta_fitted, font=fonts["heading"], fill=P["WHITE"])
    return y + 80


def _draw_hashtag_footer(draw: ImageDraw.ImageDraw, state: CampaignState,
                          SIZE: int, PAD: int, fonts: dict, y: int, P: dict):
    hashtags = state.get("hashtags", [])
    _rrect(draw, (0, y, SIZE, SIZE), radius=0, fill=(5, 15, 40, 220))
    tag_line = "  ".join(f"#{_clean(h.lstrip('#'), 20)}" for h in hashtags[:8] if h)
    draw.text((PAD, y + 18), _fit(draw, tag_line, fonts["small"], SIZE - PAD * 2),
              font=fonts["small"], fill=P["ACCENT_BLUE"])


# ── main compositor ───────────────────────────────────────────────────────────

def compositor_node(state: CampaignState) -> CampaignState:
    source_path = state.get("generated_image_path", "")
    if not source_path:
        return {}

    resolved     = Path(source_path).resolve()
    allowed_dirs = [OUTPUT_DIR.resolve(), Path("uploaded_images").resolve()]
    if not any(str(resolved).startswith(str(d)) for d in allowed_dirs):
        return {}
    if not resolved.exists():
        return {}

    # kie.ai generates complete designed posters — skip overlay for all AI-generated images.
    # Only apply the overlay to user-uploaded photos which have no design on them.
    if not state.get("source_image_path"):
        # Still paste the logo onto AI-generated images
        settings = _load_brand()
        ctype    = _campaign_type(state)
        with Image.open(resolved) as src:
            base = src.convert("RGBA").resize((1080, 1080), Image.Resampling.LANCZOS)
        base     = _paste_logo(base, settings, ctype, is_overlay=False)
        out_path = OUTPUT_DIR / f"{resolved.stem}_composed.png"
        base.convert("RGB").save(out_path, format="PNG")
        campaign_id  = state.get("asset_library_id", "")
        library_path = state.get("asset_library_path", "")
        if library_path:
            final_copy = Path(library_path) / "image.png"
            shutil.copy2(out_path, final_copy)
            if campaign_id:
                update_composed_image(campaign_id, str(final_copy))
        return {"generated_image_path": str(out_path)}

    # Skip full overlay for prompts that produce great standalone photos,
    # but still paste the logo.
    if not _needs_overlay(state):
        settings = _load_brand()
        ctype    = _campaign_type(state)
        with Image.open(resolved) as src:
            base = src.convert("RGBA").resize((1080, 1080), Image.Resampling.LANCZOS)
        base     = _paste_logo(base, settings, ctype, is_overlay=False)
        out_path = OUTPUT_DIR / f"{resolved.stem}_composed.png"
        base.convert("RGB").save(out_path, format="PNG")
        campaign_id  = state.get("asset_library_id", "")
        library_path = state.get("asset_library_path", "")
        if library_path:
            final_copy = Path(library_path) / "image.png"
            shutil.copy2(out_path, final_copy)
            if campaign_id:
                update_composed_image(campaign_id, str(final_copy))
        return {"generated_image_path": str(out_path)}

    SIZE, PAD = 1080, 36

    fonts = {
        "tiny":    _font(18),
        "small":   _font(22),
        "body":    _font(26),
        "sub":     _font(30),
        "heading": _font(42, bold=True),
        "hero":    _font(58, bold=True),
        "brand":   _font(34, bold=True),
    }

    ctype    = _campaign_type(state)
    settings = _load_brand()
    P        = _build_palette(settings)

    with Image.open(resolved) as src:
        base = src.convert("RGBA").resize((SIZE, SIZE), Image.Resampling.LANCZOS)

    base    = Image.alpha_composite(base, Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 110)))
    overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    _draw_top_bar(draw, state, SIZE, PAD, fonts, P, settings)
    y = _draw_hero_headline(draw, state, SIZE, PAD, fonts, P)

    if ctype == "event":
        y = _draw_event_strip(draw, state, SIZE, PAD, fonts, y, P)

    y = _draw_feature_strip(draw, state, SIZE, PAD, fonts, y, ctype, P)

    if ctype == "event":
        y = _draw_audience_section(draw, state, SIZE, PAD, fonts, y, P)

    _draw_hashtag_footer(draw, state, SIZE, PAD, fonts, max(y, SIZE - 156), P)

    result   = Image.alpha_composite(base, overlay).convert("RGB").convert("RGBA")
    result   = _paste_logo(result, settings, ctype, is_overlay=True)
    out_path = OUTPUT_DIR / f"{resolved.stem}_composed.png"
    result.convert("RGB").save(out_path, format="PNG")

    campaign_id  = state.get("asset_library_id", "")
    library_path = state.get("asset_library_path", "")
    if library_path:
        final_copy = Path(library_path) / "image.png"
        shutil.copy2(out_path, final_copy)
        if campaign_id:
            update_composed_image(campaign_id, str(final_copy))

    return {"generated_image_path": str(out_path)}
