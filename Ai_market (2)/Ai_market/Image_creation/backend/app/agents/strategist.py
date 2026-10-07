import json
from pathlib import Path

from app.design_styles import STYLE_LIBRARY, style_choices
from app.llm import ask_json
from app.state import CampaignState


ASSET_INDEX_PATH = Path("asset_library") / "index.json"


def recent_styles() -> list[str]:
    """Tell the strategist what was recently used so it can avoid repetition."""
    try:
        records = json.loads(ASSET_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [record.get("design_direction", {}).get("style") for record in records[-12:] if record.get("design_direction", {}).get("style")]


def recent_taglines() -> list[str]:
    """Give the model recent taglines so it does not repeat a campaign phrase."""
    try:
        records = json.loads(ASSET_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [record.get("rhyming_tagline") for record in records[-20:] if record.get("rhyming_tagline")]


def _fallback_rhyme(state: CampaignState) -> str:
    """Safe, useful fallback when the strategy model omits the short tagline."""
    return ""


def strategist_node(state: CampaignState) -> CampaignState:
    system_prompt = (
        "You are a senior social-campaign strategist and art director. Plan an "
        "original, publish-ready campaign—not a generic AI scene. Choose exactly one "
        "style from the allowed style library. Prefer community_collage for a rich "
        "photographic story with a central visual and distinct supporting actions. Avoid styles used recently when a "
        "suitable alternative exists. Then propose three clearly different visual "
        "concepts for the same message. Each concept must have a different composition "
        "and visual story, not merely different colours. "
        "IMPORTANT: Never use placeholder text like [Product Name], [Your Website], "
        "[Number], [Location], [Brand] in any field — always use real specific content. "
        "Do not add sales or retail text: no discounts, offers, shopping, buying, collections, prices, or calls to action. "
        "Return JSON exactly as: "
        '{"target_audience": str, "content_type": str, "visual_direction": [str], "offer": str|null, '
        '"design_direction": {"style": str, "layout": str, "headline": str, "supporting_copy": str, "cta": str, "text_safe_area": str}, '
        '"rhyming_tagline": str, '
        '"creative_concepts": [{"name": str, "visual_story": str, "composition": str, "palette": [str], "hero_subject": str, "mood": str}, '
        '{"name": str, "visual_story": str, "composition": str, "palette": [str], "hero_subject": str, "mood": str}, '
        '{"name": str, "visual_story": str, "composition": str, "palette": [str], "hero_subject": str, "mood": str}]}.\n\n'
        f"Allowed style library:\n{style_choices()}"
    )
    strategy = ask_json(
        system_prompt,
        "Create a short descriptive headline of at most 8 words and one meaningful supporting line. "
        "Respect the requested tone and sensitivity; do not force rhyme, celebration or cheer. "
        "It must be 2-7 words, use plain language, suit the campaign, avoid medical or performance claims, "
        "and not duplicate any recent tagline.\n"
        f"Campaign plan: {state['campaign_plan']}\nRecently used styles: {recent_styles()}\n"
        f"Recently used taglines: {recent_taglines()}",
    )
    # Fallback if model returned empty/bad JSON
    if not strategy:
        strategy = {
            "target_audience": "General audience",
            "content_type": "Social media post",
            "visual_direction": ["Professional photography", "Clean composition"],
            "offer": None,
            "design_direction": {"style": "editorial_hero", "layout": "centered", "headline": "", "supporting_copy": "", "cta": "Learn More", "text_safe_area": "left"},
            "rhyming_tagline": _fallback_rhyme(state),
            "creative_concepts": [],
        }
    direction = strategy.get("design_direction") or {}
    if direction.get("style") not in STYLE_LIBRARY:
        direction["style"] = "editorial_hero"
    direction["cta"] = ""
    strategy["offer"] = None
    tagline = str(strategy.get("rhyming_tagline") or "").strip()
    # Review copy separately: do not let a catchy rhyme override the actual message.
    for _ in range(2):
        copy = ask_json(
            "Write accurate, sensitive campaign copy. Return JSON: headline, slogan. "
            "Headline must explicitly name the campaign subject or occasion from the plan, "
            "not a generic motivational phrase. Headline: at most 8 words and 64 characters. Slogan: at most 8 words "
            "and 70 characters. No forced rhyme, guarantees, blame or unsupported "
            "claims. Preserve all requested meaning; distinguish early detection "
            "from prevention. Respect grief and serious subjects.",
            json.dumps({"plan": state["campaign_plan"], "costar": state.get("costar_brief", {})}))
        headline = copy.get("headline", "") if isinstance(copy, dict) else ""
        slogan = copy.get("slogan", "") if isinstance(copy, dict) else ""
        if (isinstance(headline, str) and isinstance(slogan, str)
                and 0 < len(headline) <= 64 and 0 < len(slogan) <= 70
                and len(headline.split()) <= 8 and len(slogan.split()) <= 8):
            direction["headline"], direction["supporting_copy"] = headline, slogan
            tagline = slogan
            break
    else:
        raise ValueError("Could not prepare concise campaign copy. Please retry.")
    return {
        "marketing_strategy": strategy,
        "design_direction": direction,
        "rhyming_tagline": tagline,
        "creative_concepts": strategy.get("creative_concepts", []),
    }
