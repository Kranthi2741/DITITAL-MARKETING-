import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.state import CampaignState


LIBRARY_ROOT = Path("asset_library")
INDEX_PATH = LIBRARY_ROOT / "index.json"


def _load_records() -> list:
    if not INDEX_PATH.exists():
        return []
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save_records(records: list) -> None:
    LIBRARY_ROOT.mkdir(exist_ok=True)
    INDEX_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


def update_composed_image(campaign_id: str, composed_path: str) -> None:
    """Called by the compositor to record the final composited image path."""
    records = _load_records()
    for record in records:
        if record.get("campaign_id") == campaign_id:
            record["assets"]["image"] = composed_path
            record["assets"]["composed_image"] = composed_path
            break
    _save_records(records)


def asset_library_node(state: CampaignState) -> CampaignState:
    """Persist campaign inputs and outputs as a versioned asset-library record."""
    plan = state.get("campaign_plan", {})
    activity = state.get("user_prompt", "campaign")
    slug = "_".join("".join(ch for ch in word if ch.isalnum()) for word in activity.lower().split()[:6]).strip("_") or "campaign"
    campaign_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{slug}"
    version = 1
    campaign_dir = LIBRARY_ROOT / campaign_id / f"v{version:03d}"
    campaign_dir.mkdir(parents=True, exist_ok=True)

    image_path = state.get("generated_image_path")
    if image_path:
        shutil.copy2(image_path, campaign_dir / "image.png")
    (campaign_dir / "prompt.txt").write_text(state.get("image_prompt", ""), encoding="utf-8")
    (campaign_dir / "caption.txt").write_text(state.get("caption", ""), encoding="utf-8")

    record = {
        "campaign_id": campaign_id,
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "activity": activity,
        "scheduled_date": state.get("scheduled_date"),
        "campaign_plan": plan,
        "design_direction": state.get("design_direction", {}),
        "selected_concept": state.get("selected_concept", {}),
        "creative_brief": state.get("creative_brief", {}),
        "image_prompt": state.get("image_prompt", ""),
        "quality_score": state.get("quality_score"),
        "quality_approved": state.get("quality_approved"),
        "quality_issues": state.get("quality_issues", []),
        "caption": state.get("caption", ""),
        "hashtags": state.get("hashtags", []),
        "assets": {"image": str(campaign_dir / "image.png")},
        "status": "draft",
    }
    records = _load_records()
    records.append(record)
    _save_records(records)
    return {
        "asset_library_id": campaign_id,
        "asset_version": version,
        "asset_library_path": str(campaign_dir),
    }
