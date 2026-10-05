"""
Shared state that flows through every node in the LangGraph.
Each agent reads what it needs and writes its own output back into this.
"""

from typing import TypedDict, Optional


class CampaignState(TypedDict, total=False):
    # input
    user_prompt: str
    business_profile: dict  # name, type, brand colors, tone, etc.
    scheduled_date: str  # ISO date when this work came from the calendar
    auto_publish: bool  # scheduled work creates drafts unless explicitly enabled
    source_image_path: str  # optional user-uploaded photo used instead of AI generation

    # planner output
    campaign_plan: dict  # festival, business, objective, platform, event_name, event_dates, brand_name, main_headline, main_message, cta, offer
    costar_brief: dict  # context, objective, style, tone, audience, response

    # strategist output
    marketing_strategy: dict  # audience, content pieces, visual direction
    design_direction: dict  # selected style, layout, headline and visual story
    rhyming_tagline: str  # short occasion-specific supporting line for the artwork
    creative_concepts: list  # distinct concepts proposed for this campaign
    selected_concept: dict

    # creative director output
    creative_brief: dict  # composition, colors, objects, avoid-list
    image_prompt: str

    # image generator output
    generated_image_path: str
    generated_video_path: str
    source_files_dir: str
    asset_library_id: str
    asset_version: int
    asset_library_path: str

    # quality agent output
    quality_score: float
    quality_approved: bool
    quality_issues: list

    # loop control
    retry_count: int
    max_retries: int

    # content agent output
    caption: str
    hashtags: list

    # publisher output
    published: bool
    publish_platform: str
    publish_id: str
    publish_error: str
    instagram_published: bool
    instagram_post_id: str
    instagram_error: str
    linkedin_published: bool
    linkedin_post_id: str
    linkedin_error: str
