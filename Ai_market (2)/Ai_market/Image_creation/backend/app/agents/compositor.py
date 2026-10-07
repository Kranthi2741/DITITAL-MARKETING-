"""Compose readable campaign copy and the original brand logo without distorting artwork."""
import json
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import os
from app.state import CampaignState
from app.agents.asset_library import update_composed_image

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "generated_images"
_SETTINGS_PATH = ROOT / "app_data" / "settings.json"
_DEFAULT_LOGO = ROOT / "assets" / "prorithm_logo.png"


def _load_brand():
    if _SETTINGS_PATH.exists():
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


def logo_file(settings):
    configured = settings.get("brand_logo_path")
    path = Path(configured) if configured else _DEFAULT_LOGO
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise ValueError("Brand logo is missing. Upload your logo in Workspace Settings before generating.")
    try:
        with Image.open(path) as logo:
            logo.verify()
    except Exception as error:
        raise ValueError("Brand logo cannot be read. Upload a PNG, JPG or WebP logo.") from error
    return path


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap(draw, text, font, width):
    lines = []
    for word in text.split():
        if draw.textlength(word, font=font) > width:
            raise ValueError("Campaign copy contains a word too wide to render.")
        if not lines or draw.textlength(lines[-1] + " " + word, font=font) > width:
            lines.append(word)
        else:
            lines[-1] += " " + word
    return lines


def compose(base, heading, slogan, settings):
    base = base.convert("RGBA")
    width, height = base.size
    pad = max(16, int(width * .035))
    with Image.open(logo_file(settings)) as original:
        logo = original.convert("RGBA")
    logo.thumbnail((int(width * .23), int(height * .10)), Image.Resampling.LANCZOS)
    # Original logo is fully opaque/readable; never recreated by the image model.
    card = Image.new("RGBA", (logo.width + 16, logo.height + 16), "white")
    card.alpha_composite(logo, (8, 8))
    base.alpha_composite(card, (pad, pad))

    overlay = Image.new("RGBA", base.size)
    draw = ImageDraw.Draw(overlay)
    font = _font(max(18, int(width * .043)), True)
    small = _font(max(15, int(width * .028)))
    lines = _wrap(draw, heading, font, width - 2 * pad)
    sublines = _wrap(draw, slogan, small, width - 2 * pad)
    if len(lines) > 2 or len(sublines) > 2:
        raise ValueError("Campaign copy is too long. Use a shorter heading and slogan.")
    line_h, sub_h = int(font.size * 1.2), int(small.size * 1.3)
    block_h = len(lines) * line_h + len(sublines) * sub_h + 2 * pad + 10
    top = height - block_h
    if block_h > height * .30:
        raise ValueError("Copy does not fit this aspect ratio. Shorten the heading and slogan.")
    # Fade into the reserved copy zone instead of a large fixed opaque footer.
    for y in range(max(0, top - pad), height):
        alpha = int(215 * min(1, (y - top + pad) / max(1, pad * 2)))
        draw.line((0, y, width, y), fill=(15, 30, 45, alpha))
    y = top + pad
    for line in lines:
        draw.text((pad, y), line, font=font, fill="white")
        y += line_h
    y += 10
    for line in sublines:
        draw.text((pad, y), line, font=small, fill="white")
        y += sub_h
    return Image.alpha_composite(base, overlay).convert("RGB")


def compositor_node(state: CampaignState) -> CampaignState:
    source = Path(state.get("generated_image_path", "")).resolve()
    allowed = [OUTPUT_DIR.resolve(), (ROOT / "uploaded_images").resolve()]
    if not source.is_file() or not any(source.is_relative_to(p) for p in allowed):
        raise ValueError("Campaign image path is invalid.")
    direction = state.get("design_direction", {})
    heading = direction.get("headline") or state.get("campaign_plan", {}).get("main_headline", "")
    slogan = state.get("rhyming_tagline") or direction.get("supporting_copy", "")
    with Image.open(source) as original:
        result = compose(original, heading, slogan, _load_brand())
    OUTPUT_DIR.mkdir(exist_ok=True)
    out = OUTPUT_DIR / (source.stem + "_composed.png")
    result.save(out)
    library = state.get("asset_library_path")
    if library:
        target = Path(library) / "image.png"
        shutil.copy2(out, target)
        if state.get("asset_library_id"):
            update_composed_image(state["asset_library_id"], str(target))
    return {"generated_image_path": str(out)}
