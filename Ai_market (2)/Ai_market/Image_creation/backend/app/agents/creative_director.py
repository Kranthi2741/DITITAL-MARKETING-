"""
Creative Director — builds a rich, structured kie.ai-style image prompt.

Instead of a generic art-direction description, this agent assembles the same
kind of detailed, section-by-section prompt that produces great results on
kie.ai (event posters, awareness campaigns, sports achievements, etc.).
"""

from app.design_styles import STYLE_LIBRARY
from app.llm import ask_json
from app.state import CampaignState


# ── campaign type detection ───────────────────────────────────────────────────

def _detect_campaign_type(state: CampaignState) -> str:
    prompt  = (state.get("user_prompt") or "").lower()
    festival = (state.get("campaign_plan", {}).get("festival") or "").lower()
    combined = prompt + " " + festival

    if any(k in combined for k in ("conference", "summit", "expo", "imc", "event",
                                    "participation", "booth", "demo", "launch", "meetup",
                                    "congress", "convention", "fair", "exhibition")):
        return "event"
    if any(k in combined for k in ("cricket", "football", "sport", "match",
                                    "tournament", "team", "player", "prize", "winner")):
        return "sports"
    if any(k in combined for k in ("birthday", "anniversary", "congratulation", "wedding",
                                    "celebration", "achievement", "milestone")):
        return "celebration"
    if any(k in combined for k in ("day", "health", "awareness", "world", "cancer",
                                    "heart", "lung", "liver", "kidney", "diabetes",
                                    "mental", "pharmacy", "pharmacist")):
        return "awareness"
    return "generic"


# ── visual theme builder ──────────────────────────────────────────────────────

_VISUAL_THEMES = {
    "event": (
        "modern conference hall with large LED screens, professional stage lighting, "
        "networking professionals, digital innovation atmosphere, futuristic technology "
        "exhibition environment, subtle crowd silhouettes, premium corporate event setup"
    ),
    "awareness": (
        "clean modern healthcare environment, medical professionals, soft clinical lighting, "
        "subtle anatomical or health-related visuals, reassuring and informative atmosphere, "
        "digital health interfaces, premium medical photography"
    ),
    "sports": (
        "dramatic sports stadium with floodlights, dynamic action photography, "
        "celebratory atmosphere, confetti, trophy, team energy, "
        "professional sports event lighting, crowd atmosphere"
    ),
    "celebration": (
        "elegant celebratory setting, warm golden lighting, premium event atmosphere, "
        "tasteful decorative elements, sophisticated festive design, "
        "professional corporate celebration photography"
    ),
    "generic": (
        "premium corporate environment, clean modern aesthetic, professional lighting, "
        "sophisticated business atmosphere, polished commercial photography"
    ),
}

_COLOR_THEMES = {
    "event": "deep navy blue, electric blue, white, subtle cyan accents, premium corporate gradients",
    "awareness": "clean blue, white, soft cyan, teal, gentle gradients, medical professional palette",
    "sports": "dynamic blue, black, gold, white, energetic high-contrast palette",
    "celebration": "warm gold, deep navy, white, elegant festive tones",
    "generic": "professional blue, white, clean gradients, corporate palette",
}

_INDUSTRY_VISUALS = {
    "healthcare": (
        "healthcare technology, remote patient monitoring, connected medical devices, "
        "AI-powered health dashboards, digital patient monitoring interfaces, "
        "real-time vital signs displays, modern hospital technology, "
        "wearable health devices, telemedicine interfaces"
    ),
    "coffee": (
        "premium coffee cup with steam, coffee beans, barista craft, "
        "warm café atmosphere, artisan coffee preparation"
    ),
    "pharmacy": (
        "pharmacy setting, medicine, healthcare professionals, "
        "pharmaceutical products, clinical environment"
    ),
    "default": (
        "professional business environment, modern technology, "
        "corporate innovation, digital interfaces"
    ),
}


def _get_industry_visuals(state: CampaignState) -> str:
    plan = state.get("campaign_plan", {})
    business = (plan.get("business") or "").lower()
    prompt = (state.get("user_prompt") or "").lower()
    combined = business + " " + prompt

    if any(k in combined for k in ("health", "medical", "hospital", "patient",
                                    "clinic", "pharma", "prorithm", "monitoring")):
        return _INDUSTRY_VISUALS["healthcare"]
    if any(k in combined for k in ("coffee", "café", "cafe", "barista")):
        return _INDUSTRY_VISUALS["coffee"]
    if any(k in combined for k in ("pharmacy", "pharmacist", "drug", "medicine")):
        return _INDUSTRY_VISUALS["pharmacy"]
    return _INDUSTRY_VISUALS["default"]


# ── text hierarchy builder ────────────────────────────────────────────────────

def _build_text_hierarchy(state: CampaignState, campaign_type: str) -> str:
    plan      = state.get("campaign_plan", {})
    direction = state.get("design_direction", {})
    costar    = state.get("costar_brief", {})

    brand      = plan.get("brand_name") or plan.get("business") or ""
    event      = plan.get("event_name") or plan.get("festival") or ""
    dates      = plan.get("event_dates") or plan.get("scheduled_date") or ""
    headline   = plan.get("main_headline") or direction.get("headline") or f"{brand} at {event}" if (brand and event) else (brand or event)
    message    = plan.get("main_message") or plan.get("objective") or costar.get("objective") or ""
    cta        = plan.get("cta") or direction.get("cta") or costar.get("response") or ""
    offer      = plan.get("offer") or ""
    supporting = direction.get("supporting_copy") or costar.get("context") or ""

    lines = []

    if campaign_type == "event":
        lines.append(f'MAIN HEADLINE (largest, most prominent): "{headline}"')
        if dates:
            lines.append(f'DATE (clearly visible): "{dates}"')
        if brand:
            lines.append(f'BRAND NAME: "{brand}"')
        if event:
            lines.append(f'EVENT NAME: "{event}"')
        if message:
            lines.append(f'MAIN MESSAGE: "{message}"')
        if cta:
            lines.append(f'CALL TO ACTION (highly prominent): "{cta}"')
        if supporting:
            lines.append(f'SUPPORTING TEXT: "{supporting}"')

    elif campaign_type == "awareness":
        festival_upper = event.upper() if event else headline.upper()
        lines.append(f'MAIN HEADLINE (largest): "{festival_upper}"')
        if message:
            lines.append(f'MAIN MESSAGE: "{message}"')
        if supporting:
            lines.append(f'SUPPORTING MESSAGE: "{supporting}"')
        if cta:
            lines.append(f'CALL TO ACTION: "{cta}"')

    elif campaign_type == "sports":
        achievement = offer or message or "1st Prize Winners"
        lines.append(f'MAIN HEADLINE (largest, most prominent): "{headline or achievement}"')
        if offer:
            lines.append(f'ACHIEVEMENT BADGE (very prominent, bold): "{offer}"')
        if dates:
            lines.append(f'DATE: "{dates}"')
        if brand:
            lines.append(f'TEAM / BRAND NAME: "{brand}"')
        if message:
            lines.append(f'MAIN MESSAGE: "{message}"')
        if supporting:
            lines.append(f'SUPPORTING TEXT: "{supporting}"')
        if cta:
            lines.append(f'CALL TO ACTION: "{cta}"')

    else:
        lines.append(f'MAIN HEADLINE: "{headline}"')
        if offer:
            lines.append(f'OFFER (most prominent): "{offer}"')
        if message:
            lines.append(f'MAIN MESSAGE: "{message}"')
        if cta:
            lines.append(f'CALL TO ACTION: "{cta}"')
        if supporting:
            lines.append(f'SUPPORTING TEXT: "{supporting}"')

    return "\n".join(lines)


# ── aspect ratio ──────────────────────────────────────────────────────────────

def _aspect_ratio(state: CampaignState, campaign_type: str) -> str:
    prompt = (state.get("user_prompt") or "").lower()
    if "16:9" in prompt or "landscape" in prompt or campaign_type == "sports":
        return "16:9 landscape"
    return "1:1 square"


# ── main node ─────────────────────────────────────────────────────────────────

def creative_director_node(state: CampaignState) -> CampaignState:
    """Build a rich kie.ai-style image prompt from the campaign plan."""
    previous_issues = state.get("quality_issues", [])
    previous_brief  = state.get("creative_brief", {})
    concepts        = state.get("creative_concepts", [])
    concept_index   = min(state.get("retry_count", 0), max(len(concepts) - 1, 0))
    selected_concept = concepts[concept_index] if concepts else {}
    direction       = state.get("design_direction", {})
    style           = direction.get("style", "editorial_hero")
    plan            = state.get("campaign_plan", {})
    profile         = state.get("business_profile", {})

    campaign_type    = _detect_campaign_type(state)
    visual_theme     = _VISUAL_THEMES[campaign_type]
    color_theme      = _COLOR_THEMES[campaign_type]
    industry_visuals = _get_industry_visuals(state)
    text_hierarchy   = _build_text_hierarchy(state, campaign_type)
    aspect_ratio     = _aspect_ratio(state, campaign_type)

    # Brand kit overrides — use saved settings colors if provided
    brand_primary = profile.get("primary_color", "")
    brand_accent  = profile.get("accent_color", "")
    brand_cta     = profile.get("cta_color", "")
    brand_font    = profile.get("font", "")
    brand_name    = profile.get("name", "") or plan.get("brand_name", "")
    brand_tagline = profile.get("tagline", "")

    # Build color palette — brand kit takes priority over campaign defaults
    if brand_primary and brand_accent:
        color_theme = (
            f"Primary brand color: {brand_primary}, "
            f"Accent color: {brand_accent}, "
            f"CTA color: {brand_cta or brand_accent}, "
            f"Use these EXACT brand colors prominently throughout the design."
        )
    font_instruction = f"Typography: {brand_font} — use this font style for all text in the design." if brand_font else "Clean modern professional typography."
    brand_instruction = ""
    if brand_name:
        brand_instruction = f"Brand name '{brand_name}' must appear prominently."
    if brand_tagline:
        brand_instruction += f" Brand tagline: '{brand_tagline}'."

    # Ask Gemini to enrich the brief with composition details and fill any gaps
    system_prompt = (
        "You are an award-winning art director. Given the campaign details, "
        "produce a detailed image generation brief. "
        "Return JSON: {\"composition\": str, \"colors\": [str], \"objects\": [str], "
        "\"avoid\": [str], \"layout_notes\": str, \"supporting_copy\": str}. "
        "composition: describe the exact visual scene in 2-3 sentences. "
        "objects: list 6-10 specific visual elements that must appear. "
        "avoid: list things that must NOT appear (fake logos, unrelated text, etc.). "
        "Do NOT include an image_prompt field — that is built separately."
    )
    user_input = (
        f"Campaign plan: {plan}\n"
        f"Strategy: {state.get('marketing_strategy')}\n"
        f"Chosen style: {style} — {STYLE_LIBRARY.get(style)}\n"
        f"Selected concept: {selected_concept}\n"
        f"Previous QA issues to fix: {previous_issues}\n"
        f"Campaign type: {campaign_type}"
    )
    brief = ask_json(system_prompt, user_input)

    # ── assemble the final kie.ai-style prompt ────────────────────────────────
    avoid_list = brief.get("avoid", [])
    avoid_block = "\n".join(f"- {a}" for a in avoid_list) if avoid_list else "- No fake logos\n- No unrelated text\n- No fake contact information"

    image_prompt = f"""Create a premium professional social media promotional poster.

CAMPAIGN TYPE: {campaign_type.upper()}

{text_hierarchy}

{brand_instruction}

VISUAL SCENE:
{brief.get("composition") or visual_theme}

INDUSTRY-SPECIFIC VISUAL ELEMENTS:
{industry_visuals}

ADDITIONAL VISUAL ELEMENTS:
{chr(10).join(f"- {o}" for o in brief.get("objects", []))}

VISUAL STYLE:
{STYLE_LIBRARY.get(style, "")}
{visual_theme}

COLOR PALETTE (STRICTLY FOLLOW THESE COLORS):
{color_theme}

TYPOGRAPHY:
{font_instruction}

PHOTOGRAPHY & REALISM STYLE:
- Shot on Canon EOS R5 or Sony A7R IV professional camera
- Natural ambient lighting mixed with professional studio lighting
- Real human hands, real faces, authentic expressions — not CGI or 3D rendered
- Genuine candid moments, not posed stock-photo stiffness
- Slight natural depth of field blur on background
- Real textures: fabric, skin, metal, glass — not synthetic or plastic-looking
- Subtle natural imperfections that make it feel real and human
- Color grading like a professional photographer's edit — warm, rich, not oversaturated
- Looks like it was shot by a professional photographer and designed by a senior graphic designer
- NOT a 3D render, NOT CGI, NOT AI-generated looking, NOT stock photo generic
- Real people, real environments, real lighting — authentic and trustworthy

DESIGN REQUIREMENTS:
- Looks like it was designed by a senior human graphic designer at a top agency
- Professional editorial quality — like you would see in Forbes, Wired, or a premium brand campaign
- Clean typographic hierarchy with intentional whitespace
- Balanced composition with clear visual flow
- Suitable for LinkedIn, Instagram, and professional social media
- Trustworthy, credible, human — not futuristic AI fantasy

DO NOT INCLUDE:
{avoid_block}
- No glowing neon sci-fi effects
- No floating holographic UI elements
- No obviously AI-generated synthetic faces
- No plastic-looking 3D renders
- No generic stock photo poses

FORMAT: {aspect_ratio}
"""

    # On retry, append the QA feedback so kie.ai avoids the same issues
    if previous_issues:
        image_prompt += f"\nPREVIOUS ISSUES TO FIX:\n" + "\n".join(f"- {i}" for i in previous_issues)

    return {
        "creative_brief": brief,
        "image_prompt": image_prompt.strip(),
        "selected_concept": selected_concept,
    }
