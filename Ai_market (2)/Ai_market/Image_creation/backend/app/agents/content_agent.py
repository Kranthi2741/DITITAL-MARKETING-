import re
from app.llm import ask_json
from app.state import CampaignState


def _strip_placeholders(text: str) -> str:
    """Remove LLM placeholder brackets like [Product Name], [Your Website], [Number]."""
    return re.sub(r"\[.*?\]", "", text).strip(" .,|")


def content_agent_node(state: CampaignState) -> CampaignState:
    system_prompt = (
        "You are a social media copywriter. Given the campaign plan and strategy, "
        "write a social caption and hashtags suitable for the requested platforms. "
        "Fulfill every caption_goals item, including requested resources or next steps. "
        "Use only URLs and resource names supplied in the request; never invent links. "
        "If no specific resource was supplied, give an honest general next step, "
        "without claiming to provide a link or a verified resource. "
        "IMPORTANT: Never use placeholder text like [Product Name], [Your Website], "
        "[Number], [Location] — always use real specific content from the campaign. "
        'Return JSON: {"caption": str, "hashtags": [str, ...]}'
    )
    user_input = (
        f"Campaign: {state.get('campaign_plan')}\n"
        f"Strategy: {state.get('marketing_strategy')}"
    )
    result = ask_json(system_prompt, user_input)
    plan = state.get("campaign_plan", {})
    # A generic fallback would silently discard explicit caption requirements.
    if plan.get("caption_goals"):
        for attempt in range(2):
            caption = result.get("caption") if isinstance(result, dict) else None
            review = ask_json(
                "Check that the caption fulfills all caption goals. General resource guidance "
                "is acceptable when no URL was supplied; fabricated resources or URLs are not. "
                "Return JSON: approved (boolean), issues (string array).",
                f"Request: {state.get('user_prompt', '')}\nGoals: {plan['caption_goals']}\nCaption: {caption}"
            ) if isinstance(caption, str) and caption.strip() else {}
            if review.get("approved") is True:
                break
            if attempt == 1:
                raise ValueError("Caption requirements could not be fulfilled; campaign was not published.")
            result = ask_json(system_prompt, user_input + f"\nRepair caption issues: {review}")
    fallback_caption = plan.get("main_message") or plan.get("objective") or state.get("user_prompt", "")[:200]
    return {
        "caption": _strip_placeholders(result.get("caption") or fallback_caption),
        "hashtags": [_strip_placeholders(h) for h in result.get("hashtags", []) if h] or ["#campaign", "#socialmedia"],
    }
