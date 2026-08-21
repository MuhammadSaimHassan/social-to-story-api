"""
Request schemas for the Social-to-Story API.
"""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# Minimum number of words tweet_text must contain before we'll even attempt
# story generation. This is a cheap, fast rejection of obviously trivial
# input (e.g. "hello world", "test") before spending an LLM call on it.
_MIN_TWEET_WORDS = 8

# Accepted domains for post_url. Restricting to X/Twitter matches the
# project's stated scope and lets us give a precise, useful error message
# instead of a vague "invalid URL".
_ALLOWED_URL_DOMAINS = ("x.com", "twitter.com", "www.x.com", "www.twitter.com")

_URL_PATTERN = re.compile(r"^https?://([^/]+)/.+", re.IGNORECASE)


class StoryRequest(BaseModel):
    """Input payload for POST /api/v1/generate-story.

    All three fields are required. A story is only generated once the
    post's text, its source URL, and the author's handle have all been
    supplied — this lets the extractor confirm the post actually exists
    (via post_url) while using tweet_text as the grounded source content
    for the LLM, with author_handle used for attribution.
    """

    tweet_text: str = Field(
        description=(
            "Raw text content of the social media post. Must contain real, "
            "substantive content (not a greeting or placeholder) — "
            f"at least {_MIN_TWEET_WORDS} words."
        ),
        examples=[
            "To create runway for explosive IT exports growth and domestic economic "
            "activity, Ministry of IT & Telecom aggressively enabled guaranteed 17.7 "
            "Tbps+ bandwidth for Pakistan via additional fiber optic cables."
        ],
    )
    author_handle: str = Field(
        description="Handle/username of the post's author, used for source attribution.",
        examples=["@MoitOfficial"],
    )
    post_url: str = Field(
        description=(
            "URL of the original X/Twitter post. Used to verify the post "
            "actually exists before generating a story from it."
        ),
        examples=["https://x.com/MoitOfficial/status/2085985308718563602"],
    )
    output_format: str = Field(
        default="markdown",
        description="Desired format for the generated story body.",
        examples=["markdown"],
    )
    story_length: Optional[str] = Field(
        default=None,
        description=(
            "Desired length of the generated story: 'short' (~150-300 word "
            "brief) or 'long' (~600-800 word feature). This is the caller's "
            "choice, not the model's — whatever is passed here is what gets "
            "generated, regardless of how much substance the source tweet "
            "has. If omitted (or null), the API falls back to its previous "
            "behavior and decides automatically based on the tweet's content."
        ),
        examples=["short"],
    )

    @field_validator("story_length")
    @classmethod
    def validate_story_length(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not cleaned:
            return None
        if cleaned not in ("short", "long"):
            raise ValueError(
                "story_length must be either 'short' or 'long' (or omitted "
                "to let the API decide automatically)."
            )
        return cleaned

    @field_validator("tweet_text")
    @classmethod
    def validate_tweet_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("tweet_text cannot be empty.")
        word_count = len(cleaned.split())
        if word_count < _MIN_TWEET_WORDS:
            raise ValueError(
                f"tweet_text is too short to generate a story from ({word_count} "
                f"word(s) given, at least {_MIN_TWEET_WORDS} required). Please "
                "provide the full post text with real, substantive content."
            )
        return cleaned

    @field_validator("author_handle")
    @classmethod
    def validate_author_handle(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("author_handle cannot be empty.")
        if not cleaned.startswith("@"):
            cleaned = f"@{cleaned}"
        if not re.match(r"^@[A-Za-z0-9_]{1,15}$", cleaned):
            raise ValueError(
                "author_handle must be a valid handle (letters, digits, "
                "underscores only, e.g. '@MoitOfficial')."
            )
        return cleaned

    @field_validator("post_url")
    @classmethod
    def validate_post_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("post_url cannot be empty.")
        match = _URL_PATTERN.match(cleaned)
        if not match:
            raise ValueError(
                "post_url must be a full, valid URL (e.g. "
                "'https://x.com/handle/status/123456789')."
            )
        domain = match.group(1).lower()
        if domain not in _ALLOWED_URL_DOMAINS:
            raise ValueError(
                "post_url must be a link to an X (Twitter) post — "
                "e.g. 'https://x.com/handle/status/123456789'."
            )
        return cleaned
