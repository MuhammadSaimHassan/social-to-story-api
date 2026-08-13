"""
LLM service.

Wraps the Google GenAI SDK to turn extracted source content into a
structured `StoryData` object, using schema-enforced JSON output so the
model's response can be parsed directly into Pydantic models.
"""

from functools import lru_cache
import json
from typing import List, Optional

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.prompts import build_editorial_prompt
from app.schemas.response import StoryData, TableItem


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
    """

    title: str
    subtitle: str
    source_context: str
    summary_table: List[_LLMTableItem]
    story_markdown: str


_LLM_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "required": ["title", "subtitle", "source_context", "summary_table", "story_markdown"],
    "properties": {
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
) -> StoryData:
    """Generate a structured news story from extracted source content.

    Args:
        content: Cleaned source text (from the extractor service) to base
            the story on.
        author_handle: Optional handle/username used for source attribution.

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

    prompt = build_editorial_prompt(input_text=content, author_handle=author_handle)

    try:
        client = _get_client()
        response = await client.aio.models.generate_content(
            model=settings.default_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_LLM_RESPONSE_SCHEMA,
            ),
        )
    except genai_errors.ClientError as exc:
        # Covers 4xx errors from the API: invalid API key, quota/rate-limit
        # exceeded (429), bad request, etc.
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
        # Covers 5xx errors: the LLM provider is down or overloaded.
        raise HTTPException(
            status_code=502,
            detail=f"LLM provider is currently unavailable: {exc}",
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

    word_count = _count_words(parsed.story_markdown)

    summary_table = [
        TableItem(pillar=item.pillar, metric=item.metric, purpose=item.purpose)
        for item in parsed.summary_table
    ]

    return StoryData(
        title=parsed.title,
        subtitle=parsed.subtitle,
        source_context=parsed.source_context,
        summary_table=summary_table,
        story_markdown=parsed.story_markdown,
        word_count=word_count,
    )
