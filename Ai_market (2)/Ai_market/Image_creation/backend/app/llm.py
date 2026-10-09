"""
Single place that handles all AI calls:
- Text reasoning (Planner, Strategist, Creative Director, Content Agent)
  → local Ollama Gemma 3
- Image generation
  → SingularityAPI gpt-image-2
"""

import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
SINGULARITY_BASE_URL = "https://api.singularityapi.dev/v1"
SINGULARITY_MODEL = "gpt-image-2"


def _ollama_generate(prompt: str) -> str:
    """Generate text locally with Ollama and return the model response."""
    response = requests.post(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.4, "num_ctx": 8192},
        },
        timeout=300,
    )
    response.raise_for_status()
    result = response.json()
    text = result.get("response", "")
    if not text:
        raise RuntimeError("Ollama returned an empty response")
    return text


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
    """Ask Ollama for a structured JSON response. Never raises on parse
    errors — returns an empty dict as last resort so the pipeline always continues."""
    full_prompt = (
        system_prompt
        + "\n\nIMPORTANT: Respond ONLY with a single valid JSON object. "
        "Use double quotes for all keys and string values. "
        "No markdown, no code fences, no explanation before or after. "
        "Keep values concise, but fully describe each required scene and action."
        f"\n\n{user_prompt}"
    )

    def _call():
        return _ollama_generate(full_prompt)

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
    """Generate an image via SingularityAPI and save it to output_path."""
    api_key = os.environ.get("SINGULARITY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SINGULARITY_API_KEY not set. Add it to backend/.env")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # gpt-image-2 accepts the same 1024x1024 size used by the connectivity test.
    payload = {
        "model": SINGULARITY_MODEL,
        "prompt": prompt,
        "size": "1024x1024",
        "quality": "low",
        "n": 1,
        "output_format": "png",
    }
    resp = requests.post(
        f"{SINGULARITY_BASE_URL}/images/generations",
        headers=headers,
        json=payload,
        timeout=180,
    )
    resp.raise_for_status()
    try:
        encoded = resp.json()["data"][0]["b64_json"]
        import base64
        image_bytes = base64.b64decode(encoded)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"SingularityAPI returned no valid base64 image: {exc}") from exc

    with open(output_path, "wb") as image_file:
        image_file.write(image_bytes)
    return output_path


def evaluate_image(image_path: str, requirements: dict) -> dict:
    """Review actual pixels locally. Transport/parse failure must never approve."""
    import base64
    from pathlib import Path
    prompt = (
        "Inspect the attached image itself against the campaign requirements. "
        "Return JSON: score (integer 0-100), issues (array of strings), "
        "critical_issues (array of strings). "
        "Minor clutter, slight blur, stylistic preferences and suggestions belong ONLY "
        "in issues and affect score; they are NEVER critical defects. "
        "Check immediate topic recognition, central focal subject, distinct supporting "
        "actions, believable anatomy, plausible equipment and procedures, no misleading "
        "visual claims, and absence of unwanted writing. Report uncertain procedural "
        "accuracy for human review rather than claiming it is correct. "
        "Critical issues include incorrect procedures, misleading meaning, distorted "
        "anatomy and faces or essential actions in reserved copy/logo areas. "
        "Judge requested safe areas using layout_zones. Logo and copy are added later; "
        "do not penalize their absence. Be specific about visible defects and locations. "
        "Judge coverage only against visual_goals. Caption goals such as resources, "
        "links and explanations are fulfilled later and must not cause image rejection. "
        "Delivery requirements are not scene requirements. "
        "Do not assume the image followed its prompt. Requirements: "
        + json.dumps(requirements, ensure_ascii=False)
    )
    response = requests.post(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
        json={"model": os.environ.get("OLLAMA_VISION_MODEL", OLLAMA_MODEL),
              "messages": [{"role": "user", "content": prompt,
                            "images": [base64.b64encode(Path(image_path).read_bytes()).decode("ascii")]}],
              "stream": False, "format": "json", "options": {"temperature": 0}},
        timeout=300,
    )
    response.raise_for_status()
    result = json.loads(response.json()["message"]["content"])
    if (not isinstance(result, dict) or type(result.get("score")) is not int
            or not 0 <= result["score"] <= 100
            or any(not isinstance(result.get(k), list)
                   or not all(isinstance(x, str) for x in result[k])
                   for k in ("issues", "critical_issues"))):
        raise ValueError("Vision review was incomplete; campaign was not approved.")
    # Confirm proposed blockers separately so a stylistic suggestion cannot veto
    # a passing score merely because the first review used the wrong field.
    if result["critical_issues"]:
        confirmation = ask_json(
            "Classify each proposed blocker conservatively. Return JSON: "
            "confirmed_indices (integer array). Confirm only concrete major defects: "
            "clearly incorrect procedures, harmful misinformation, severe anatomy "
            "distortion, wrong campaign subject, or essential faces/actions hidden by "
            "reserved overlay zones. Mild blur, clutter, layout taste or a request for "
            "sharper focus are NOT blockers. Uncertain judgments are not confirmed.",
            json.dumps({"proposed_blockers": result["critical_issues"]}))
        indices = confirmation.get("confirmed_indices") if isinstance(confirmation, dict) else None
        if not isinstance(indices, list) or any(
                type(i) is not int or not 0 <= i < len(result["critical_issues"]) for i in indices):
            raise ValueError("Quality severity review was incomplete; no approval was issued.")
        proposed = result["critical_issues"]
        result["critical_issues"] = [s for i, s in enumerate(proposed) if i in indices]
        result["issues"] += [s for i, s in enumerate(proposed) if i not in indices]
    return result
