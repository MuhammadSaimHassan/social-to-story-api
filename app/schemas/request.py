"""
Request schemas for the Social-to-Story API.
"""

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class StoryRequest(BaseModel):
    """Input payload for POST /api/v1/generate-story.

    Either `tweet_text` or `post_url` must be provided. If both are given,
    `tweet_text` is treated as the primary source and `post_url` is kept
    only for attribution/context.
    """

    tweet_text: Optional[str] = Field(
        default=None,
        description="Raw text content of the social media post. Required if post_url is not provided.",
        examples=[
            "To create runway for explosive IT exports growth and domestic economic "
            "activity, Ministry of IT & Telecom aggressively enabled guaranteed 17.7 "
            "Tbps+ bandwidth for Pakistan via additional fiber optic cables."
        ],
    )
    author_handle: Optional[str] = Field(
        default=None,
        description="Handle/username of the post's author, used for source attribution.",
        examples=["@MoitOfficial"],
    )
    post_url: Optional[str] = Field(
        default=None,
        description=(
            "URL of the original post. Required if tweet_text is not provided; "
            "used by the extractor service to fetch content when text isn't supplied directly."
        ),
        examples=["https://x.com/MoitOfficial/status/2085985308718563602"],
    )
    output_format: str = Field(
        default="markdown",
        description="Desired format for the generated story body.",
        examples=["markdown"],
    )

    @model_validator(mode="after")
    def check_tweet_text_or_post_url(self) -> "StoryRequest":
        """Ensure at least one content source is provided."""
        if not self.tweet_text and not self.post_url:
            raise ValueError("Either 'tweet_text' or 'post_url' must be provided.")
        return self
