"""Preserve explicit CO-STAR fields and separate subject from communication goals."""
import json
import re
from app.llm import ask_json
from app.state import CampaignState


def parse_costar(prompt):
    matches = list(re.finditer(r"\b(Context|Objective|Style|Tone|Audience|Response)\s*:", prompt, re.I))
    return {m.group(1).lower(): prompt[m.end():matches[i+1].start() if i+1 < len(matches) else len(prompt)].strip()
            for i, m in enumerate(matches)}


def planner_node(state: CampaignState) -> CampaignState:
    prompt = state.get("user_prompt", "")
    explicit = parse_costar(prompt)
    system = """
Interpret the full request, preserving both the occasion and every requested
communication goal. Platform/output instructions are delivery requirements, not
the substantive message. Context may contain several goals joined by 'and'.
Return JSON: {"campaign_plan": {"festival": str, "business": str,
"objective": str, "tone": str, "platform": str, "main_headline": str,
"main_message": str, "communication_goals": [str], "brand_name": str},
"costar": {"context": str, "objective": str, "style": str, "tone": str,
"audience": str, "response": str}}.
communication_goals must cover all substantive clauses, including requested
actions, care, education or risk reduction, not only the occasion or emotion.
Use a descriptive headline of at most 8 words. Preserve sensitive tone.
Do not invent brands, events or claims. Distinguish screening/early detection
from prevention; never promise cures, safety or survival. Avoid blame.
"""
    for _ in range(2):
        result = ask_json(system, json.dumps({"request": prompt, "explicit_costar": explicit,
                         "business_profile": state.get("business_profile", {})}, ensure_ascii=False))
        plan = result.get("campaign_plan", {}) if isinstance(result, dict) else {}
        goals = plan.get("communication_goals") if isinstance(plan, dict) else None
        if isinstance(goals, list) and goals and all(isinstance(g, str) and g.strip() for g in goals):
            break
    else:
        raise ValueError("Could not extract the full campaign goals. Please retry.")
    costar = result.get("costar", {})
    costar = costar if isinstance(costar, dict) else {}
    costar.update(explicit)
    plan["source_context"] = explicit.get("context", prompt)
    plan["cta"], plan["offer"] = "", None
    return {"campaign_plan": plan, "costar_brief": costar}
