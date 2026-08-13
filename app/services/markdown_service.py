"""
Markdown export service.

Builds an organized Markdown document from generated story data.
"""

from io import BytesIO
import re

from app.schemas.response import StoryData


def _safe_filename(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip().lower()).strip("-")
    return f"{slug[:80] or 'generated-story'}.md"


def build_story_markdown(story: StoryData) -> tuple[BytesIO, str]:
    """Build a complete Markdown export and return it as bytes."""
    lines = [
        f"# {story.title}",
        "",
        f"*{story.subtitle}*",
        "",
        f"**Source:** {story.source_context}",
        "",
        f"**Word count:** {story.word_count}",
        "",
    ]

    if story.summary_table:
        lines.extend(
            [
                "## Key Facts",
                "",
                "| Pillar | Metric | Purpose |",
                "| --- | --- | --- |",
            ]
        )
        for item in story.summary_table:
            lines.append(f"| {item.pillar} | {item.metric} | {item.purpose} |")
        lines.append("")

    lines.extend(["## Story", "", story.story_markdown.strip(), ""])

    output = BytesIO("\n".join(lines).encode("utf-8"))
    output.seek(0)
    return output, _safe_filename(story.title)
