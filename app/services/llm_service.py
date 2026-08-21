"""
LLM service.

Wraps the Google GenAI SDK to turn extracted source content into a
structured `StoryData` object, using schema-enforced JSON output so the
model's response can be parsed directly into Pydantic models.
"""

import asyncio
from functools import lru_cache
import json
import random
from typing import List, Optional

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.prompts import build_editorial_prompt
from app.schemas.response import StoryData, TableItem

# Gemini occasionally returns 503 UNAVAILABLE ("high demand") for a moment
# even when the service is generally healthy. These are transient and worth
# a few quick retries with backoff before surfacing an error to the user.
_MAX_RETRIES = 3
_BASE_DELAY_SECONDS = 1.5


class _LLMTableItem(BaseModel):
    """Schema-only mirror of `TableItem`, used solely for the LLM call.

    The GenAI SDK's schema converter rejects JSON Schema `examples` keys
    (which `TableItem`'s Field definitions include for Swagger docs), so a
    separate, examples-free model is used here and mapped back to the real
    `TableItem` afterwards.
    """

    pillar: str = Field(description="Name of the key pillar/aspect being summarized.")
    metric: str = Field(description="Quantified metric or figure associated with the pillar.")
    purpose: str = Field(description="Explanation of why this metric/pillar matters.")


class _LLMStoryOutput(BaseModel):
    """Schema used for the LLM call itself.

    Mirrors StoryData but deliberately omits `word_count` — that value is
    computed locally from the returned `story_markdown` rather than trusted
    from the model, since LLMs are unreliable at self-reported counts. Also
    uses `_LLMTableItem` instead of `TableItem` for the reason described above.

    `is_sufficient` and `rejection_reason` implement a content-gating
    contract: the model judges whether the source material actually
    supports a truthful story before writing one, rather than being forced
    to fabricate content for trivial or empty input (e.g. "hello world").
    The story fields are optional here since they're only populated when
    is_sufficient is true — enforced explicitly in generate_story_from_text.
    """

    is_sufficient: bool = False
    rejection_reason: Optional[str] = None
    story_length: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    source_context: Optional[str] = None
    summary_table: List[_LLMTableItem] = Field(default_factory=list)
    story_markdown: Optional[str] = None


_LLM_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "required": ["is_sufficient"],
    "properties": {
        "is_sufficient": {
            "type": "BOOLEAN",
            "description": (
                "True if the source material contains enough real, substantive "
                "content to write a truthful analytical news story. False if the "
                "input is a greeting, test message, placeholder, or otherwise "
                "lacks any real newsworthy subject matter."
            ),
        },
        "rejection_reason": {
            "type": "STRING",
            "description": (
                "Required and populated only when is_sufficient is false: a "
                "short, clear, user-facing explanation of why a story could not "
                "be generated from this input."
            ),
        },
        "story_length": {
            "type": "STRING",
            "enum": ["short", "long"],
            "description": (
                "Required when is_sufficient is true. 'short' for updates with "
                "a single fact/angle and little surrounding context (~150-300 "
                "word brief); 'long' for updates rich enough in distinct, "
                "substantive angles to support a full feature (~600-800 words). "
                "Prefer 'short' when in doubt — never pad thin material."
            ),
        },
        "title": {
            "type": "STRING",
            "description": "Headline for the generated article.",
        },
        "subtitle": {
            "type": "STRING",
            "description": "Supporting subheading that adds context to the title.",
        },
        "source_context": {
            "type": "STRING",
            "description": "Attribution describing where the original content came from.",
        },
        "summary_table": {
            "type": "ARRAY",
            "description": "Structured breakdown of key facts or figures from the story.",
            "items": {
                "type": "OBJECT",
                "required": ["pillar", "metric", "purpose"],
                "properties": {
                    "pillar": {
                        "type": "STRING",
                        "description": "Name of the key pillar/aspect being summarized.",
                    },
                    "metric": {
                        "type": "STRING",
                        "description": "Quantified metric or figure associated with the pillar.",
                    },
                    "purpose": {
                        "type": "STRING",
                        "description": "Explanation of why this metric/pillar matters.",
                    },
                },
            },
        },
        "story_markdown": {
            "type": "STRING",
            "description": "Full generated article body, formatted in Markdown.",
        },
    },
}


@lru_cache
def _get_client() -> genai.Client:
    """Lazily build and cache the GenAI client.

    Deferred until first use (rather than at import time) so importing this
    module never crashes just because GEMINI_API_KEY isn't set yet — the
    missing-key case is instead handled explicitly in
    `generate_story_from_text`, which returns a clean HTTP 500.
    """
    return genai.Client(api_key=settings.gemini_api_key)


def _count_words(text: str) -> int:
    """Return a simple whitespace-based word count for the story body."""
    if not text:
        return 0
    return len(text.split())


async def generate_story_from_text(
    content: str,
    author_handle: Optional[str] = None,
    requested_length: Optional[str] = None,
) -> StoryData:
    """Generate a structured news story from extracted source content.

    Args:
        content: Cleaned source text (from the extractor service) to base
            the story on.
        author_handle: Optional handle/username used for source attribution.
        requested_length: Optional caller-supplied "short" or "long". When
            given, this is the authoritative length decision — the model is
            instructed to write at this length regardless of how much
            substance the source has, and the returned `story_length` is
            forced to match this value even if the model's own output
            disagrees. When omitted (None), the model decides the length
            itself based on the source content, preserving prior behavior.

    Returns:
        A fully populated `StoryData` instance, with `word_count` computed
        locally from the generated `story_markdown`.

    Raises:
        HTTPException(502): if the LLM API call fails due to connectivity,
            quota/rate-limit, or other upstream errors.
        HTTPException(500): if the model's response cannot be parsed into
            the expected schema.
    """
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is not configured on the server.",
        )

    prompt = build_editorial_prompt(
        input_text=content,
        author_handle=author_handle,
        requested_length=requested_length,
    )

    client = _get_client()
    call_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_LLM_RESPONSE_SCHEMA,
        # Gemini 3 models default to HIGH thinking effort and, per Google's
        # own SDK issue tracker (googleapis/python-genai#2062), thinking
        # tokens are drawn from the SAME budget as max_output_tokens rather
        # than a separate one. Left unset, thinking alone can consume
        # nearly the entire budget (or hang with no cap at all), leaving
        # little/no room for the actual story JSON — which is exactly what
        # produces "is_sufficient: true" with an empty story_markdown.
        # LOW is enough for this classification+writing task and leaves
        # the bulk of the budget for the actual ~600-800 word story output.
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        max_output_tokens=16384,
    )

    response = None
    last_server_error: Optional[genai_errors.ServerError] = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.aio.models.generate_content(
                model=settings.default_model,
                contents=prompt,
                config=call_config,
            )
            break
        except genai_errors.ClientError as exc:
            # Covers 4xx errors from the API: invalid API key, quota/rate-limit
            # exceeded (429), bad request, etc. Not worth retrying.
            status = getattr(exc, "code", None)
            if status == 429:
                raise HTTPException(
                    status_code=502,
                    detail="LLM provider rate limit or quota exceeded. Please try again later.",
                ) from exc
            raise HTTPException(
                status_code=502,
                detail=f"LLM provider rejected the request: {exc}",
            ) from exc
        except genai_errors.ServerError as exc:
            # Covers 5xx errors, including the common 503 "high demand"
            # response, which is usually transient. Retry with backoff
            # before giving up.
            last_server_error = exc
            if attempt < _MAX_RETRIES:
                delay = _BASE_DELAY_SECONDS * (2**attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(delay)
                continue
            raise HTTPException(
                status_code=502,
                detail=(
                    "LLM provider is currently experiencing high demand after "
                    f"{_MAX_RETRIES + 1} attempts. Please try again in a moment. "
                    f"({exc})"
                ),
            ) from exc
        except genai_errors.APIError as exc:
            # Catch-all for any other SDK-level API error.
            raise HTTPException(
                status_code=502,
                detail=f"LLM API error: {exc}",
            ) from exc
        except Exception as exc:
            # Connectivity issues (DNS, timeouts, etc.) and anything unforeseen.
            raise HTTPException(
                status_code=502,
                detail=f"Failed to reach LLM provider: {exc.__class__.__name__}: {exc}",
            ) from exc

    if response is None:
        # Should be unreachable (the loop above always either returns a
        # response or raises), but guards against silent fallthrough.
        raise HTTPException(
            status_code=502,
            detail=f"LLM provider is currently unavailable: {last_server_error}",
        )

    raw_parsed = getattr(response, "parsed", None)

    if raw_parsed is None:
        response_text = getattr(response, "text", None)
        if not response_text:
            raise HTTPException(
                status_code=500,
                detail="LLM response could not be parsed into the expected story schema.",
            )
        try:
            raw_parsed = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=500,
                detail="LLM response was not valid JSON.",
            ) from exc

    try:
        parsed = _LLMStoryOutput.model_validate(raw_parsed)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="LLM response could not be parsed into the expected story schema.",
        ) from exc

    if not parsed.is_sufficient:
        reason = (
            parsed.rejection_reason
            or "The provided content does not contain enough substantive information "
            "to generate a story."
        )
        raise HTTPException(
            status_code=422,
            detail=f"Unable to generate a story from the provided input: {reason}",
        )

    # Defensive check: if the model says is_sufficient=true but didn't
    # actually populate the story fields, treat that as a malformed
    # response rather than silently returning an empty/broken story.
    if not parsed.title or not parsed.story_markdown or not parsed.subtitle:
        finish_reason = None
        try:
            finish_reason = response.candidates[0].finish_reason
        except Exception:
            pass
        detail = (
            "LLM indicated sufficient content but did not return a complete "
            "story. Please try again."
        )
        if finish_reason and str(finish_reason) != "STOP":
            # Most commonly MAX_TOKENS — the model ran out of output budget
            # (often to thinking tokens) before finishing the story.
            detail += f" (finish_reason={finish_reason})"
        raise HTTPException(status_code=500, detail=detail)

    word_count = _count_words(parsed.story_markdown)

    summary_table = [
        TableItem(pillar=item.pillar, metric=item.metric, purpose=item.purpose)
        for item in parsed.summary_table
    ]

    # If the caller explicitly requested a length, that decision is
    # authoritative — it overrides whatever the model reports, even though
    # the prompt already instructs the model to match it. This guarantees
    # the response never contradicts what the user asked for.
    final_story_length = requested_length or parsed.story_length or "long"

    return StoryData(
        story_length=final_story_length,
        title=parsed.title,
        subtitle=parsed.subtitle,
        source_context=parsed.source_context or f"Source: {author_handle}",
        summary_table=summary_table,
        story_markdown=parsed.story_markdown,
        word_count=word_count,
    )
