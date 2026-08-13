"""
Story generation router.

Exposes POST /api/v1/generate-story, which resolves source content via the
extractor service and passes it to the LLM service to produce a structured
story response.
"""

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from app.schemas.request import StoryRequest
from app.schemas.response import StoryData, StoryResponse
from app.services import docx_service, extractor, llm_service, markdown_service

router = APIRouter(prefix="/api/v1", tags=["story"])


async def _generate_story_data(payload: StoryRequest):
    try:
        content = await extractor.extract_content(
            tweet_text=payload.tweet_text,
            post_url=payload.post_url,
        )
    except HTTPException:
        # Already a well-formed HTTP error (e.g. 400 for bad/unreachable URL) — propagate as-is.
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to extract content from the provided input: {exc}",
        ) from exc

    if not content or not content.strip():
        raise HTTPException(
            status_code=400,
            detail="Resolved source content is empty; cannot generate a story from it.",
        )

    try:
        story_data = await llm_service.generate_story_from_text(
            content=content,
            author_handle=payload.author_handle,
        )
    except HTTPException:
        # Already a well-formed HTTP error (e.g. 502 for LLM provider issues) — propagate as-is.
        raise
    except ValidationError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"LLM output did not match the expected story schema: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error while generating the story: {exc}",
        ) from exc

    return story_data


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
