from app.llm import ask_json
from app.state import CampaignState


def planner_node(state: CampaignState) -> CampaignState:
    system_prompt = (
        "You are a marketing campaign planner for a social media agency. "
        "Your job is to turn ANY user input into a compelling social media campaign — "
        "even if the user is sharing a personal story, achievement, or anecdote. "
        "NEVER say 'no campaign requested' or treat input as non-actionable. "
        "Personal stories = achievement posts. News = announcement posts. Events = event posts. "
        "Always extract or CREATE: a strong headline, a main message, and a CTA. "
        "For personal achievements like winning prizes, meeting VIPs, or sports wins: "
        "  - headline = the achievement (e.g. '1st Prize Winners!') "
        "  - main_message = the story in one punchy sentence "
        "  - cta = celebratory CTA (e.g. 'Congratulations to our team!') "
        "  - festival = the event/occasion (e.g. 'Cricket Tournament 2025') "
        "  - offer = the prize or achievement (e.g. '1st Prize - Rs. 1,00,000') "
        "Extract ALL specific details: brand name, event name, dates, prize amounts, "
        "VIP names, locations, team names, offers, CTAs. "
        "Return JSON with this exact structure: "
        '{"campaign_plan": {"festival": str, "business": str, "objective": str, "tone": str, "platform": str, '
        '"event_name": str or null, "event_dates": str or null, "brand_name": str or null, '
        '"main_headline": str, "main_message": str, "cta": str, '
        '"offer": str or null, "product_name": str or null}, '
        '"costar": {"context": str, "objective": str, "style": str, "tone": str, "audience": str, "response": str}}. '
        "Preserve every detail from the user including names, amounts, locations, dates."
    )
    business = state.get("business_profile", {})
    user_input = f"Request: {state['user_prompt']}\nBusiness profile: {business}"

    result = ask_json(system_prompt, user_input)
    prompt = state.get("user_prompt", "")
    plan = result.get("campaign_plan") or result or {}
    # Fallback: if model returned empty/bad JSON, build a minimal plan from the raw prompt
    if not plan.get("objective"):
        plan = {
            "festival": prompt[:60],
            "business": (state.get("business_profile") or {}).get("name", "Brand"),
            "objective": prompt[:100],
            "tone": "celebratory",
            "platform": "Instagram",
            "main_headline": prompt[:50],
            "main_message": prompt[:100],
            "cta": "Share and celebrate with us!",
            "offer": None,
        }
    return {
        "campaign_plan": plan,
        "costar_brief": result.get("costar", {}),
    }
