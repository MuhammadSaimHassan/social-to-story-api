"""
Story generation router.

Exposes POST /api/v1/generate-story, which resolves source content via the
extractor service and passes it to the LLM service to produce a structured
story response.
"""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from app.schemas.request import StoryRequest
from app.schemas.response import StoryData, StoryResponse
from app.services import docx_service, extractor, image_service, llm_service, markdown_service

router = APIRouter(prefix="/api/v1", tags=["story"])


async def _generate_story_data(payload: StoryRequest):
    try:
        content = await extractor.extract_content(
            tweet_text=payload.tweet_text,
            post_url=payload.post_url,
        )
    except HTTPException:
        # Already a well-formed HTTP error (e.g. 400 for a post that can't be
        # found/reached) — propagate as-is.
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to extract content from the provided input: {exc}",
        ) from exc

    # Kick off image generation concurrently with the text story rather
    # than waiting for it to finish first — both are grounded in the same
    # extracted content, so there's no need to serialize them, and doing
    # so avoids stacking image latency on top of the story call's own
    # retry/backoff logic (relevant given hosting platforms' request
    # timeouts, e.g. Vercel's 60s limit).
    image_task = asyncio.create_task(
        image_service.generate_story_image(
            content=content,
            author_handle=payload.author_handle,
        )
    )

    try:
        story_data = await llm_service.generate_story_from_text(
            content=content,
            author_handle=payload.author_handle,
            requested_length=payload.story_length,
        )
    except HTTPException:
        # Already a well-formed HTTP error (e.g. 502 for LLM provider issues) — propagate as-is.
        image_task.cancel()
        raise
    except ValidationError as exc:
        image_task.cancel()
        raise HTTPException(
            status_code=500,
            detail=f"LLM output did not match the expected story schema: {exc}",
        ) from exc
    except Exception as exc:
        image_task.cancel()
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error while generating the story: {exc}",
        ) from exc

    # Image generation is best-effort: generate_story_image() already
    # catches its own failures internally and returns (None, None) rather
    # than raising, but this except is a defensive backstop in case a
    # cancellation or other asyncio-level issue surfaces here instead.
    try:
        cover_image_base64, cover_image_mime_type = await image_task
    except Exception:
        cover_image_base64, cover_image_mime_type = None, None

    return story_data.model_copy(
        update={
            "cover_image_base64": cover_image_base64,
            "cover_image_mime_type": cover_image_mime_type,
        }
    )


@router.post(
    "/generate-story",
    response_model=StoryResponse,
    summary="Generate a publication-ready story from a social media post",
)
async def generate_story(payload: StoryRequest) -> StoryResponse:
    """Convert a short social media post into a structured JSON story."""
    story_data = await _generate_story_data(payload)
    return StoryResponse(status="success", data=story_data)


@router.post(
    "/generate-story-docx",
    summary="Generate a downloadable Word document from a social media post",
    response_class=StreamingResponse,
)
async def generate_story_docx(payload: StoryRequest) -> StreamingResponse:
    """Generate a story and return it as a downloadable .docx file."""
    story_data = await _generate_story_data(payload)
    file_stream, filename = docx_service.build_story_docx(story_data)

    return StreamingResponse(
        file_stream,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/export-story-docx",
    summary="Export an existing generated story as a Word document",
    response_class=StreamingResponse,
)
async def export_story_docx(story_data: StoryData) -> StreamingResponse:
    """Return an already generated story as a downloadable .docx file."""
    file_stream, filename = docx_service.build_story_docx(story_data)

    return StreamingResponse(
        file_stream,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/export-story-markdown",
    summary="Export an existing generated story as a Markdown file",
    response_class=StreamingResponse,
)
async def export_story_markdown(story_data: StoryData) -> StreamingResponse:
    """Return an already generated story as a downloadable .md file."""
    file_stream, filename = markdown_service.build_story_markdown(story_data)

    return StreamingResponse(
        file_stream,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
