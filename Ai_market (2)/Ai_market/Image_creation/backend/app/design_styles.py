"""A controlled creative vocabulary used to keep campaigns varied but on-brand."""

STYLE_LIBRARY = {
    "editorial_hero": "Premium editorial hero image shot on a professional camera. Real person or real product as the focal subject, cinematic natural lighting, generous negative space, aspirational magazine-quality finish. Looks like a Vogue or Forbes cover shoot.",
    "bold_typography": "High-impact advertising composition designed by a senior agency designer. Strong text-safe area, graphic colour blocking, dramatic visual hierarchy. Looks like a real Nike or Apple campaign — not AI generated.",
    "human_story": "Warm documentary-style photography with real authentic people, genuine candid expressions, natural lighting. Looks like it was shot by a photojournalist — real skin tones, real emotions, real environments.",
    "product_spotlight": "Clean premium product photography with sculptural studio lighting, real physical product as hero, shallow depth of field, restrained supporting details. Looks like a professional product photographer shot it.",
    "celebration": "Energetic achievement photography capturing a real moment of success. Real people celebrating, elegant natural decorative elements, warm ambient lighting. Feels like a genuine human moment, not a staged stock photo.",
    "minimal_healthcare": "Clean modern healthcare photography with real doctors or patients, soft natural clinical lighting, reassuring human warmth. Looks like it was shot for a real hospital or healthcare brand campaign.",
    "future_forward": "Forward-looking technology campaign with real people interacting with real technology. Sophisticated natural lighting, genuine human interaction with devices, confident innovation narrative. Real office or lab environment.",
    "community_collage": "Curated multi-moment editorial collage of real photographs. Feels like a human art director assembled real photos from a brand shoot — authentic, varied, genuine.",
}


def style_choices() -> str:
    return "\n".join(f"- {name}: {description}" for name, description in STYLE_LIBRARY.items())
