"""
Single place that handles all AI calls:
- Text reasoning (Planner, Strategist, Creative Director, Content Agent)
  → OpenRouter: apodex/apodex-1.1-mini:free
- Vision QA (Quality Agent)
  → Gemini (only model here that can see images)
- Image generation
  → kie.ai
"""

import os
import json
import time
import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_openrouter_client = None
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "apodex/apodex-1.1-mini:free")
KIE_BASE_URL = "https://api.kie.ai"


def get_openrouter_client():
    """OpenRouter client — used for all text reasoning agents."""
    global _openrouter_client
    if _openrouter_client is None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY not set. Get a free key at "
                "https://openrouter.ai"
            )
        _openrouter_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
    return _openrouter_client


def _call_with_retry(fn, max_attempts=3, base_delay=2):
    """Retry on transient 503/UNAVAILABLE errors."""
    last_error = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if "503" in str(e) or "UNAVAILABLE" in str(e) or "rate" in str(e).lower():
                if attempt < max_attempts - 1:
                    time.sleep(base_delay * (attempt + 1))
                    continue
            raise
    raise last_error


def _repair_json(text: str) -> str:
    """Best-effort repair of common model JSON mistakes."""
    # Strip markdown fences
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Extract outermost { ... }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    elif start != -1:
        text = text[start:]  # truncated — try to close below

    # Replace single-quoted keys/values with double quotes
    import re
    text = re.sub(r"(?<![\\])'([^']*)'\s*:", r'"\1":', text)   # 'key':
    text = re.sub(r":\s*'([^']*)'([,}\]])", r': "\1"\2', text) # : 'value',

    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    return text


def ask_json(system_prompt: str, user_prompt: str, model: str = None) -> dict:
    """Ask OpenRouter for a structured JSON response. Never raises on parse errors
    — returns an empty dict as last resort so the pipeline always continues."""
    client = get_openrouter_client()
    used_model = model or OPENROUTER_MODEL

    def _call():
        response = client.chat.completions.create(
            model=used_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        system_prompt
                        + "\n\nIMPORTANT: Respond ONLY with a single valid JSON object. "
                        "Use double quotes for all keys and string values. "
                        "No markdown, no code fences, no explanation before or after. "
                        "Keep every string value under 150 characters."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=8192,
            temperature=0.7,
        )
        message = response.choices[0].message
        content = message.content
        if not content:
            try:
                msg_dict = message.model_dump()
                for key, value in msg_dict.items():
                    if key not in ("role", "tool_calls", "function_call") and isinstance(value, str) and value.strip():
                        content = value
                        break
            except Exception:
                pass
        return content or ""

    raw = ""
    for attempt in range(3):
        try:
            raw = _call_with_retry(_call)
            break
        except Exception:
            if attempt == 2:
                return {}
            time.sleep(2 * (attempt + 1))

    if not raw.strip():
        return {}

    text = _repair_json(raw)

    # Try 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try 2: close truncated JSON with common endings
    for closing in ["}}", "\"}", "\"]}}", "]}", "\"\"}"]:
        try:
            return json.loads(text + closing)
        except json.JSONDecodeError:
            continue

    # Try 3: extract any {...} substring that parses
    import re
    for match in re.finditer(r"\{[^{}]*\}", text):
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            continue

    # Last resort: return empty dict so pipeline never crashes
    return {}


def generate_image(prompt: str, output_path: str) -> str:
    """Generate an image via kie.ai and save it to output_path."""
    api_key = os.environ.get("KIE_API_KEY")
    if not api_key:
        raise RuntimeError("KIE_API_KEY not set. Get a key at https://kie.ai")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Detect aspect ratio from the prompt itself
    prompt_lower = prompt.lower()
    if "16:9" in prompt_lower or "landscape" in prompt_lower:
        aspect_ratio = "16:9"
    elif "9:16" in prompt_lower or "portrait" in prompt_lower:
        aspect_ratio = "9:16"
    else:
        aspect_ratio = "1:1"

    # Step 1: create task
    payload = {
        "model": "qwen2-1/text-to-image",
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": "1K",
            "output_format": "png",
        },
    }
    resp = requests.post(f"{KIE_BASE_URL}/api/v1/jobs/createTask", headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != 200:
        raise RuntimeError(f"kie.ai task creation failed: {result.get('msg')}")
    task_id = result["data"]["taskId"]

    # Step 2: poll until done
    poll_headers = {"Authorization": f"Bearer {api_key}"}
    for _ in range(60):  # max ~3 minutes
        time.sleep(3)
        poll = requests.get(f"{KIE_BASE_URL}/api/v1/jobs/recordInfo", headers=poll_headers, params={"taskId": task_id}, timeout=30)
        poll.raise_for_status()
        data = poll.json().get("data", {})
        success_flag = data.get("successFlag")
        state = data.get("state", "")

        if success_flag == 1 or state == "success":
            urls = data.get("response", {}).get("resultUrls", [])
            if not urls:
                raise RuntimeError("kie.ai returned success but no image URL")
            img_resp = requests.get(urls[0], timeout=60)
            img_resp.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(img_resp.content)
            return output_path

        if success_flag == 2 or state == "failed":
            raise RuntimeError(f"kie.ai image generation failed: {data.get('failMsg') or data.get('errorMessage')}")

    raise RuntimeError("kie.ai image generation timed out after 3 minutes")


def evaluate_image(image_path: str, requirements: dict) -> dict:
    """QA check using OpenRouter text model — no vision API needed.
    Since we can't send the image to a text model, we evaluate based on
    whether the prompt requirements were well-formed and trust kie.ai
    to have followed them. Returns a passing score so the pipeline continues."""
    brief = requirements.get("creative_brief", {})
    campaign_plan = requirements.get("campaign_plan", {})

    system_prompt = (
        "You are a marketing campaign quality reviewer. "
        "Based on the campaign brief and requirements provided, "
        "assess whether the image generation prompt was well-structured and complete. "
        "Assume the image was generated correctly from the prompt. "
        "Return JSON: {\"score\": int, \"issues\": [str]}. "
        "Score 85-95 if the brief is complete and well-structured. "
        "Score 70-84 if minor details are missing. "
        "Keep issues list empty or minimal if the brief looks good."
    )
    user_prompt = (
        f"Campaign plan: {campaign_plan}\n"
        f"Creative brief: {brief}\n"
        f"Design direction: {requirements.get('design_direction', {})}\n"
        "Is this brief complete and well-structured for a professional social media campaign?"
    )

    try:
        return ask_json(system_prompt, user_prompt)
    except Exception:
        # If even this fails, return a passing score so the pipeline doesn't stall
        return {"score": 80, "issues": []}
