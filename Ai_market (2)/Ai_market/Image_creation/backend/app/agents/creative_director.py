"""Topic-derived photographic storytelling; no activity lookup tables."""
import json
from app.llm import ask_json
from app.state import CampaignState


def _valid(brief):
    if not isinstance(brief, dict):
        return False
    if not all(isinstance(brief.get(k), str) and brief[k].strip()
               for k in ("composition", "topic_visual_direction", "central_visual")):
        return False
    scenes = brief.get("scenes")
    return (isinstance(scenes, list) and 3 <= len(scenes) <= 5
            and all(isinstance(s, dict) and all(
                isinstance(s.get(k), str) and s[k].strip()
                for k in ("action", "setting", "meaning", "placement")) for s in scenes)
            and isinstance(brief.get("avoid"), list)
            and all(isinstance(s, str) for s in brief["avoid"]))


def _goal_ids(scene):
    raw = scene.get("goal_indices", [scene.get("goal_index")])
    if not isinstance(raw, list):
        raw = [raw]
    return {int(x) for x in raw
            if type(x) is int or (isinstance(x, str) and x.isdigit())}


def creative_director_node(state: CampaignState) -> CampaignState:
    system = """
You are a photographic campaign art director. Interpret the supplied activity
dynamically. Create a rich photographic montage whose message is understandable
without reading words. Do not substitute a generic portrait.
Return JSON with composition (overall arrangement), topic_visual_direction
(the specific message), central_visual (one recognizable focal subject or symbol),
scenes (3-5 objects each containing action, setting, meaning, placement, goal_indices),
colors (string array), objects (string array), avoid (string array), layout_notes.
Each scene must show a different concrete action supporting the requested message.
goal_indices is an array of zero-based communication_goals indices illustrated
by that scene. A scene can cover several related goals.
Cover EVERY communication goal in the plan, prioritizing the requested action.
Use recognizable subject-specific symbols and literal actions. Avoid decorative
stones, feathers or abstract objects when they obscure the subject. Supporting
lifestyle scenes must not replace the requested care or educational action.
Arrange scenes around the central visual with soft photographic blends, consistent
lighting, believable anatomy, natural skin and fabric textures.
The central subject must dominate, with 2-4 smaller supporting moments. Choose
flowing blends, layered photography or a shared environment dynamically; do not
default to a grid of equal circular cutouts. Prefer recognizable literal subjects.
Depict procedures and equipment only when confidently plausible; use consultation
or supportive interactions if uncertain. Never invent a machine or procedure.
Meaning comes from actions and objects, not labels or dashboards.
Relevant symbolic objects and tasteful anatomical illustrations are allowed;
people and environments remain photographic. Symbols must not imply unsupported
treatments, cures, transmission routes or guaranteed protection.
Do not invent organizations, products, facts or campaign claims.
Use a respectful constructive mood; exclude gore and stigmatizing imagery.
No writing, signs, lettering, logos or watermarks. Reserve a quiet shallow bottom
strip for application-added copy; keep faces and focal objects above it.
"""
    context = json.dumps({
        "request": state.get("user_prompt", ""),
        "campaign": state.get("campaign_plan", {}),
        "message": state.get("costar_brief", {}),
        "feedback": state.get("quality_issues", []),
    }, ensure_ascii=False)
    feedback = ""
    for attempt in range(3):
        brief = ask_json(system, context + (
            "\nInclude all required fields and 3-5 complete distinct scenes."
            if attempt else "") + feedback)
        if not _valid(brief):
            feedback = (
                "\nRepair the previous JSON: require nonempty composition, topic_visual_direction, "
                "central_visual; 3-5 scenes each with nonempty action, setting, meaning, placement; "
                "avoid must be a string array (empty allowed). Previous response: "
                + json.dumps(brief, ensure_ascii=False))
            failure = "missing or invalid required scene fields"
            continue
        goals = state.get("campaign_plan", {}).get("communication_goals", [])
        covered = set().union(*(_goal_ids(s) for s in brief["scenes"]))
        if goals and not set(range(len(goals))).issubset(covered):
            missing = sorted(set(range(len(goals))) - covered)
            failure = "uncovered campaign goals: " + ", ".join(str(goals[i]) for i in missing)
            feedback = "\nRepair the brief; scenes may cover multiple goals. " + failure + "\nPrevious brief: " + json.dumps(brief)
            continue
        review = ask_json(
            "Review semantic alignment against the ORIGINAL request, including all Context clauses. "
            "Reject omitted action goals, unrelated visual metaphors, misleading health claims, "
            "or insensitive tone. Return JSON with approved (boolean) and issues (string array).",
            context + "\nProposed visual brief: " + json.dumps(brief, ensure_ascii=False))
        if isinstance(review, dict) and review.get("approved") is True:
            brief["alignment_review"] = review
            break
        feedback = "\nRevise these alignment issues: " + json.dumps(review, ensure_ascii=False)
        failure = "relevance review did not approve: " + json.dumps(review, ensure_ascii=False)
    else:
        raise ValueError("Creative brief could not pass after 3 attempts: " + failure
                         + ". Image generation was not started.")
    profile = state.get("business_profile", {})
    colors = brief.get("colors", [])
    colors = [c for c in colors if isinstance(c, str)] if isinstance(colors, list) else []
    accents = [profile.get("primary_color"), profile.get("accent_color")]
    palette = ", ".join(colors + [c for c in accents if isinstance(c, str) and c])
    scenes = "\n".join(
        f"{i+1}. {s['placement']}: {s['action']}. Setting: {s['setting']}. "
        f"Visual meaning: {s['meaning']}." for i, s in enumerate(brief["scenes"]))
    request = state.get("user_prompt", "").lower()
    ratio = "9:16" if "9:16" in request else "16:9" if "16:9" in request or "landscape" in request else "1:1"
    prompt = f"""Create a premium photographic campaign montage.
MESSAGE TO COMMUNICATE WITHOUT WORDS: {brief['topic_visual_direction']}
CENTRAL FOCAL VISUAL: {brief['central_visual']}
COMPOSITION: {brief['composition']}
REQUIRED CONNECTED SCENES (include every scene):
{scenes}
LAYOUT: {brief.get('layout_notes', '')}
PALETTE: {palette}. Preserve natural skin tones.
Photorealistic people, authentic actions, detailed real materials, coherent natural
light, polished photographic compositing. One dominant focal visual; secondary
scenes clearly readable at social-post size. Soft transitions, no crowded grid.
Relevant nonverbal symbols are allowed. No text, letters, numbers, labels, signs,
captions, logos, watermarks, fake writing or interface panels.
Keep the bottom 25 percent quiet for copy added later; keep faces unobstructed.
Reserve the upper-left 28 percent width and 14 percent height for the brand logo.
Avoid: {', '.join(brief['avoid'])}.
FORMAT: {ratio}
"""
    return {"creative_brief": brief, "image_prompt": prompt.strip(),
            "selected_concept": {"visual_story": brief["topic_visual_direction"]}}
