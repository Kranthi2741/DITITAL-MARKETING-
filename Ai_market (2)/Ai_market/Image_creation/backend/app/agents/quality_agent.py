from app.llm import evaluate_image
from app.state import CampaignState

# Single source of truth for the pass/fail cutoff.
QUALITY_THRESHOLD = 75  # background image only; compositor adds the infographic layer

# Layout zones the background image must respect for the compositor overlay
_LAYOUT_ZONES = (
    "The image will have an infographic overlay. Check these layout zones:\n"
    "1. LEFT HALF must be clean and dark enough for white text panels to be legible over it.\n"
    "2. TOP 9% must be a solid dark strip (brand bar area).\n"
    "3. BOTTOM 20% must fade to near-black (hashtag footer area).\n"
    "4. Hero subject should be on the RIGHT half or center-right.\n"
    "Penalise heavily if the left half is busy, bright, or cluttered."
)


def quality_agent_node(state: CampaignState) -> CampaignState:
    profile = state.get("business_profile", {})
    # Use actual brand kit colors for QA — not hardcoded defaults
    brand_colors = [c for c in [
        profile.get("primary_color"),
        profile.get("accent_color"),
        profile.get("cta_color"),
    ] if c]

    requirements = {
        "campaign_plan": state.get("campaign_plan"),
        "design_direction": state.get("design_direction"),
        "creative_brief": {
            **state.get("creative_brief", {}),
            # Override colors with actual brand kit so QA checks the right palette
            **(({"colors": brand_colors}) if brand_colors else {}),
        },
        "approved_brand_logo": True,
        "layout_zones": _LAYOUT_ZONES,
    }

    result = evaluate_image(state["generated_image_path"], requirements)
    score = result.get("score", 0)
    issues = result.get("issues", [])

    # the decision happens here, in code — not inside the AI's response
    # A publish-ready campaign needs a higher bar than a merely usable image.
    approved = score >= QUALITY_THRESHOLD

    return {
        "quality_score": score,
        "quality_approved": approved,
        "quality_issues": issues,
        "retry_count": state.get("retry_count", 0) + 1,
    }


def route_after_quality(state: CampaignState) -> str:
    """Conditional edge: decide where to go after quality check."""
    if state.get("quality_approved"):
        return "publisher"

    # Re-running the generator cannot improve an uploaded photograph, so do
    # not repeatedly review the same source image.
    if state.get("source_image_path"):
        return "end_failed"

    max_retries = state.get("max_retries", 3)
    if state.get("retry_count", 0) >= max_retries:
        # ran out of attempts - stop here rather than looping forever
        return "end_failed"

    return "creative_director"  # loop back with feedback
