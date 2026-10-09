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
    if not isinstance(scenes, list) or not (3 <= len(scenes) <= 5):
        return False
    for s in scenes:
        if not isinstance(s, dict):
            return False
        for k in ("action", "setting", "meaning", "placement"):
            v = s.get(k)
            if not isinstance(v, str) or not v.strip():
                return False
    avoid = brief.get("avoid")
    # Accept missing or non-list avoid — coerce it rather than reject the whole brief
    if avoid is not None and not isinstance(avoid, list):
        brief["avoid"] = [str(avoid)] if avoid else []
    elif avoid is None:
        brief["avoid"] = []
    return True


def _goal_ids(scene):
    # Accept goal_indices, goal_index, or a bare integer; strings like "0" are fine
    raw = scene.get("goal_indices") or scene.get("goal_index")
    if raw is None:
        return set()
    if not isinstance(raw, list):
        raw = [raw]
    ids = set()
    for x in raw:
        try:
            ids.add(int(x))
        except (TypeError, ValueError):
            pass
    return ids


def _fallback_brief(state: CampaignState) -> dict:
    """Build a safe minimum brief when the LLM cannot return valid JSON.

    This keeps one malformed model response from stopping the whole campaign.
    The scenes are intentionally literal and conservative, especially for
    health-awareness campaigns where the model must not invent procedures or
    claims.
    """
    plan = state.get("campaign_plan", {}) or {}
    request = state.get("user_prompt", "") or ""
    goals = plan.get("visual_goals", plan.get("communication_goals", [])) or []
    goal_text = [str(goal).strip() for goal in goals if str(goal).strip()]
    topic = plan.get("event_name") or plan.get("festival") or request[:120] or "the requested campaign"
    is_health = any(word in f"{request} {topic}".lower() for word in (
        "cancer", "screening", "health", "medical", "disease", "clinic"
    ))

    if is_health:
        scene_actions = [
            ("A person receives clear, respectful guidance from a qualified professional", "A bright, welcoming consultation room", "Taking an informed health step"),
            ("A person schedules or attends an appropriate routine check-up", "A clean, calm healthcare setting", "Supporting awareness and early action"),
            ("People share supportive information and encouragement", "A warm community or family environment", "Building awareness and support"),
        ]
        objects = ["supportive conversation", "calendar", "health information materials"]
    else:
        scene_actions = [
            ("People engage with the campaign topic in a natural, positive way", "A setting relevant to the requested activity", "Making the campaign message understandable"),
            ("A person demonstrates the main requested action", "A realistic environment connected to the activity", "Showing the core benefit or offer"),
            ("People share a positive moment connected to the campaign", "A warm community or customer setting", "Building interest and connection"),
        ]
        objects = ["relevant campaign objects", "natural materials", "supportive human interaction"]

    scenes = [
        {
            "action": scene_actions[0][0],
            "setting": scene_actions[0][1],
            "meaning": goal_text[0] if goal_text else scene_actions[0][2],
            "placement": "Left supporting scene",
            "goal_indices": [0] if goals else [],
        },
        {
            "action": scene_actions[1][0],
            "setting": scene_actions[1][1],
            "meaning": goal_text[1] if len(goal_text) > 1 else scene_actions[1][2],
            "placement": "Right supporting scene",
            "goal_indices": [1] if len(goals) > 1 else [],
        },
        {
            "action": scene_actions[2][0],
            "setting": scene_actions[2][1],
            "meaning": goal_text[2] if len(goal_text) > 2 else scene_actions[2][2],
            "placement": "Lower supporting scene",
            "goal_indices": [2] if len(goals) > 2 else [],
        },
    ]
    return {
        "composition": "One dominant central awareness visual surrounded by three readable supporting photographic moments",
        "topic_visual_direction": f"A professional, respectful visual story about {topic}",
        "central_visual": "A confident person at the center, supported by clear human guidance and community care",
        "scenes": scenes,
        "colors": [],
        "objects": objects,
        "avoid": [
            "gore", "fear-based imagery", "unsupported medical claims", "guaranteed prevention claims",
            "invented procedures", "medical equipment used inaccurately", "text, logos, or watermarks",
        ],
        "layout_notes": "Keep the central subject dominant and reserve the bottom area for application-added copy.",
        "fallback_used": True,
        "fallback_reason": "The language model did not return a structurally valid creative brief after five attempts.",
    }


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
goal_indices is an array of zero-based visual_goals indices illustrated
by that scene. A scene can cover several related goals.
Cover EVERY visual goal in the plan, prioritizing the requested action.
Caption goals are fulfilled later in the caption; do not create scenes or text
for resources, links or further-information requests. Delivery requirements
guide presentation; they do not require scenes.
If campaign_plan.occasion_only is true, depict the named occasion/festival,
its cultural setting, traditions, colours, food, family/community moments or
other clearly relevant celebration details. Do not introduce healthcare,
screening, doctors, patients, medical equipment or disease-awareness imagery.
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

    # Stage 1: get a structurally valid brief (up to 5 attempts)
    brief = {}
    struct_feedback = ""
    for attempt in range(5):
        brief = ask_json(system, context + (
            "\nInclude all required fields and 3-5 complete distinct scenes."
            if attempt else "") + struct_feedback)
        if _valid(brief):
            break
        struct_feedback = (
            "\nRepair the previous JSON: require nonempty composition, topic_visual_direction, "
            "central_visual; 3-5 scenes each with nonempty action, setting, meaning, placement; "
            "avoid must be a string array (empty allowed). Previous response: "
            + json.dumps(brief, ensure_ascii=False))
    else:
        # Do not stop the campaign because the model returned malformed JSON.
        # Use a deterministic, conservative brief so the workflow can continue
        # without restarting the server or asking the user to intervene.
        brief = _fallback_brief(state)

    # Stage 2: ensure every visual goal is covered (up to 3 attempts, reusing brief)
    plan = state.get("campaign_plan", {})
    goals = plan.get("visual_goals", plan.get("communication_goals", []))
    for attempt in range(3):
        covered = set().union(*(_goal_ids(s) for s in brief["scenes"]))
        missing_indices = sorted(set(range(len(goals))) - covered)
        if not goals or not missing_indices:
            break
        missing_desc = ", ".join(str(goals[i]) for i in missing_indices)
        previous_brief = brief
        candidate = ask_json(system, context
            + "\nRepair the brief; scenes may cover multiple goals. "
            + "Uncovered visual goals: " + missing_desc
            + "\nPrevious brief: " + json.dumps(previous_brief, ensure_ascii=False))
        if not _valid(candidate):
            # Structural regression — retain the last known good brief.
            brief = previous_brief
            break
        brief = candidate

    # Stage 3: alignment review — a bad/empty review response does NOT block the brief
    review = ask_json(
        "Review visual alignment against the original request and visual_goals. "
        "Caption goals (resources, links, explanations) will be fulfilled by the caption agent; "
        "their absence in image scenes is correct. Delivery requirements are not scene goals. "
        "Reject omitted visual action goals, unrelated visual metaphors, misleading health claims, "
        "or insensitive tone. Return JSON with approved (boolean) and issues (string array).",
        context + "\nProposed visual brief: " + json.dumps(brief, ensure_ascii=False))
    if isinstance(review, dict) and review.get("approved") is False and review.get("issues"):
        # One repair attempt when the reviewer clearly lists actionable issues
        repaired = ask_json(system, context
            + "\nRevise these alignment issues: " + json.dumps(review, ensure_ascii=False)
            + "\nPrevious brief: " + json.dumps(brief, ensure_ascii=False))
        if _valid(repaired):
            brief = repaired

    # Final guard: every downstream use assumes scenes exists. If a model
    # response regressed during alignment, recover deterministically instead
    # of raising KeyError and stopping the campaign.
    if not _valid(brief):
        brief = _fallback_brief(state)
    brief["alignment_review"] = review if isinstance(review, dict) else {}
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
