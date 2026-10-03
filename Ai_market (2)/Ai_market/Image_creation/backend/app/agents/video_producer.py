import json
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from app.state import CampaignState


def _font(size):
    for path in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def video_producer_node(state: CampaignState) -> CampaignState:
    source = Path(state["generated_image_path"])
    name = str(state.get("campaign_plan", {}).get("festival") or "campaign").lower().replace(" ", "_")
    campaign_dir = Path("generated_campaigns") / f"{name}_{state.get('retry_count', 0)}"
    frames_dir = campaign_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, campaign_dir / "source_image.png")
    (campaign_dir / "prompt.txt").write_text(state.get("image_prompt", ""), encoding="utf-8")
    (campaign_dir / "caption.txt").write_text(state.get("caption", ""), encoding="utf-8")
    (campaign_dir / "metadata.json").write_text(json.dumps({
        "campaign_plan": state.get("campaign_plan", {}),
        "creative_brief": state.get("creative_brief", {}),
        "quality_score": state.get("quality_score"),
        "quality_issues": state.get("quality_issues", []),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    base = Image.open(source).convert("RGB")
    width, height = 1080, 1920
    font = _font(64)
    title = str(state.get("campaign_plan", {}).get("festival") or "Your Special Moment")[:30]
    for index in range(36):
        scale = 1.0 + (index / 35) * 0.10
        crop_w, crop_h = int(base.width / scale), int(base.height / scale)
        left, top = (base.width - crop_w) // 2, (base.height - crop_h) // 2
        frame = base.crop((left, top, left + crop_w, top + crop_h)).resize((width, height), Image.Resampling.LANCZOS)
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((0, 0, width, 150), fill=(0, 0, 0, 100))
        draw.text((55, 45), title, font=font, fill=(255, 255, 255, 255))
        Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB").save(frames_dir / f"frame_{index:04d}.jpg", quality=92)

    output = campaign_dir / "motion_graphic.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "6", "-i", str(frames_dir / "frame_%04d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)], check=True)
    library_path = Path(state.get("asset_library_path", ""))
    if library_path:
        shutil.copy2(output, library_path / "motion_graphic.mp4")
        index_path = library_path.parents[1] / "index.json"
        if index_path.exists():
            records = json.loads(index_path.read_text(encoding="utf-8"))
            for record in records:
                if record.get("campaign_id") == state.get("asset_library_id"):
                    record.setdefault("assets", {})["video"] = str(library_path / "motion_graphic.mp4")
                    record["status"] = "video_created"
            index_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"generated_video_path": str(output), "source_files_dir": str(campaign_dir)}
