"""
Response schemas for the Social-to-Story API.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class TableItem(BaseModel):
    """A single row in the story's summary table."""

    pillar: str = Field(
        description="Name of the key pillar/aspect being summarized.",
        examples=["Guaranteed International Bandwidth"],
    )
    metric: str = Field(
        description="Quantified metric or figure associated with the pillar.",
        examples=["17.7+ Tbps"],
    )
    purpose: str = Field(
        description="Explanation of why this metric/pillar matters.",
        examples=["Prevents single-cable outage bottlenecks and lowers latency."],
    )


class StoryData(BaseModel):
    """The generated story content and its structured metadata."""

    story_length: str = Field(
        default="long",
        description=(
            "Whether the model wrote a short brief or a full-length feature, "
            "based on how much substantive content the source actually had."
        ),
        examples=["short", "long"],
    )
    title: str = Field(
        description="Headline for the generated article.",
        examples=["Supercharging Digital Infrastructure: Pakistan Secures Guaranteed 17.7 Tbps Bandwidth"],
    )
    subtitle: str = Field(
        description="Supporting subheading that adds context to the title.",
        examples=["Ministry of IT & Telecom expands international fiber capacity to backstop 5G rollouts and export growth."],
    )
    source_context: str = Field(
        description="Attribution describing where the original content came from.",
        examples=["Official announcement by Ministry of IT & Telecom (@MoitOfficial)"],
    )
    summary_table: List[TableItem] = Field(
        default_factory=list,
        description="Structured breakdown of key facts/figures from the story.",
    )
    story_markdown: str = Field(
        description="Full generated article body, formatted in Markdown.",
    )
    word_count: int = Field(
        description="Word count of the generated story body.",
        ge=0,
        examples=[620],
    )
    cover_image_base64: Optional[str] = Field(
        default=None,
        description=(
            "Base64-encoded cover image generated to be relevant to the "
            "story, or null if image generation was unavailable/failed. "
            "Image generation is best-effort and never blocks story "
            "generation — this field being null does not indicate an error."
        ),
    )
    cover_image_mime_type: Optional[str] = Field(
        default=None,
        description="MIME type of cover_image_base64 (e.g. 'image/png'), or null if no image was generated.",
        examples=["image/png"],
    )


class StoryResponse(BaseModel):
    """Top-level response wrapper returned by POST /api/v1/generate-story."""

    status: str = Field(
        description="Outcome of the request, e.g. 'success' or 'error'.",
        examples=["success"],
    )
    data: StoryData = Field(
        description="Generated story payload and its structured metadata.",
    )
