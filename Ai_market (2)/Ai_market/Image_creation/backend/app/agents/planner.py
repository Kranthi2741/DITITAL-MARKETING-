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
"main_message": str, "visual_goals": [str], "caption_goals": [str],
"delivery_requirements": [str], "brand_name": str},
"costar": {"context": str, "objective": str, "style": str, "tone": str,
"audience": str, "response": str},
"campaign_type": "healthcare" | "occasion" | "business"}.
Classify campaign_type from the user's request, not from the business profile.
Use healthcare only when the requested subject is medical, health, wellness,
patient-care, disease-awareness or a health-related awareness day/event.
Use occasion for cultural festivals, national days, religious celebrations and
other occasions where the requested creative is about the occasion itself.
Use business for product, service, employer, brand, event or community campaigns
that are not healthcare. Never make a business campaign healthcare merely because
the business profile belongs to a healthcare company.
Classify every requested requirement by where it can be fulfilled.
visual_goals: nonempty list of subjects, actions and messages that can be conveyed
through people, objects or scenes without words.
caption_goals: explanations, resources, further information, links, next steps and
details requiring words. Do not turn resource requests into image-scene requirements.
delivery_requirements: platforms, branding, tone, audience and output format.
Preserve all substantive clauses across these lists. Empty caption/delivery lists
are allowed. Do not invent extra goals. Related visual goals can share a scene.
Use a descriptive headline of at most 8 words. Preserve sensitive tone.
Do not invent brands, events or claims. Distinguish screening/early detection
from prevention; never promise cures, safety or survival. Avoid blame.
"""
    request_data = {
        "request": prompt,
        "explicit_costar": explicit,
        "business_profile": state.get("business_profile", {}),
        "classification_rule": "Classify the request semantically as healthcare, occasion, or business. Do not infer healthcare from the business profile.",
    }
    for _ in range(2):
        result = ask_json(system, json.dumps(request_data, ensure_ascii=False))
        plan = result.get("campaign_plan", {}) if isinstance(result, dict) else {}
        groups = [plan.get(k) for k in ("visual_goals", "caption_goals", "delivery_requirements")] if isinstance(plan, dict) else []
        if (len(groups) == 3 and groups[0]
                and all(isinstance(group, list) and all(isinstance(g, str) and g.strip()
                        for g in group) for group in groups)):
            break
    else:
        raise ValueError("Could not extract the full campaign goals. Please retry.")
    costar = result.get("costar", {})
    costar = costar if isinstance(costar, dict) else {}
    costar.update(explicit)
    # Some model responses omit one or more CO-STAR fields even though the
    # campaign plan is valid. Keep the live UI from showing a misleading
    # "Preparing..." brief by deriving safe fallbacks from the plan/request.
    costar.setdefault("context", plan.get("source_context") or prompt)
    costar.setdefault("objective", plan.get("objective", ""))
    costar.setdefault("style", plan.get("style", ""))
    costar.setdefault("tone", plan.get("tone", ""))
    costar.setdefault("audience", plan.get("audience", ""))
    costar.setdefault("response", plan.get("response", ""))
    plan["source_context"] = explicit.get("context", prompt)
    campaign_type = result.get("campaign_type", "business") if isinstance(result, dict) else "business"
    if campaign_type not in {"healthcare", "occasion", "business"}:
        campaign_type = "business"
    plan["campaign_type"] = campaign_type
    plan["occasion_only"] = campaign_type == "occasion"
    # Retain the aggregate for strategy/history consumers; image coverage uses
    # only visual_goals, never this aggregate.
    plan["communication_goals"] = plan["visual_goals"] + plan["caption_goals"]
    plan["cta"], plan["offer"] = "", None
    return {"campaign_plan": plan, "costar_brief": costar}
