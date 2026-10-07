import os
import uuid
from pathlib import Path
from PIL import Image
from app.llm import generate_image
from app.state import CampaignState

OUTPUT_DIR = "generated_images"
LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "prorithm_logo.png"

# Canonical proRiTHM lockup: every generated image uses this same proportion,
# top-left placement, and clear space. Keeping these values here (rather than
# in prompts) makes branding deterministic.
LOGO_WIDTH_RATIO = 0.12
HORIZONTAL_INSET_RATIO = 0.035
VERTICAL_INSET_RATIO = 0.03


def add_brand_logo(image_path: str) -> None:
    """Apply the canonical proRiTHM logo lockup to every generated image."""
    if not LOGO_PATH.exists():
        raise FileNotFoundError(f"Brand logo not found: {LOGO_PATH}")
    base = Image.open(image_path).convert("RGBA")
    logo = Image.open(LOGO_PATH).convert("RGBA")
    # The logo is normalized to the same proportion on every canvas; scale it
    # in both directions so portrait and square assets retain the same look.
    max_width = max(64, int(base.width * LOGO_WIDTH_RATIO))
    scale = max_width / logo.width
    logo = logo.resize((int(logo.width * scale), int(logo.height * scale)), Image.Resampling.LANCZOS)
    margin_x = max(28, int(base.width * HORIZONTAL_INSET_RATIO))
    margin_y = max(24, int(base.height * VERTICAL_INSET_RATIO))
    # Preserve the PNG alpha: no opaque card or recreated logo is added.
    # The mark is deliberately small enough to stay clear of faces and copy.
    base.alpha_composite(logo, (margin_x, margin_y))
    base.convert("RGB").save(image_path, format="PNG")


def image_generator_node(state: CampaignState) -> CampaignState:
    from app.agents.compositor import logo_file, _load_brand
    logo_file(_load_brand())  # Validate branding before a paid generation request.
    # A real photo supplied by the user is the campaign creative.
    source_image = state.get("source_image_path")
    if source_image:
        return {"generated_image_path": source_image}

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    attempt = state.get("retry_count", 0)
    output_path = os.path.join(OUTPUT_DIR, f"campaign_{uuid.uuid4().hex[:10]}_concept_{attempt + 1}.png")

    generate_image(state["image_prompt"], output_path)
    # Do NOT stamp a logo — kie.ai generates a complete designed poster;
    # adding a logo on top would overlap the existing design.

    return {"generated_image_path": output_path}
