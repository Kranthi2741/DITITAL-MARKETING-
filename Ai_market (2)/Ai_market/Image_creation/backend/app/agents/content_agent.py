import re
from app.llm import ask_json
from app.state import CampaignState


def _strip_placeholders(text: str) -> str:
    """Remove LLM placeholder brackets like [Product Name], [Your Website], [Number]."""
    return re.sub(r"\[.*?\]", "", text).strip(" .,|")


def content_agent_node(state: CampaignState) -> CampaignState:
    system_prompt = (
        "You are a social media copywriter. Given the campaign plan and strategy, "
        "write an Instagram caption and hashtags. "
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
    fallback_caption = plan.get("main_message") or plan.get("objective") or state.get("user_prompt", "")[:200]
    return {
        "caption": _strip_placeholders(result.get("caption") or fallback_caption),
        "hashtags": [_strip_placeholders(h) for h in result.get("hashtags", []) if h] or ["#campaign", "#socialmedia"],
    }
