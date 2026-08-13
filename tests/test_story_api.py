"""
Tests for the Social-to-Story API.

Run with: pytest
The LLM service call is mocked in all tests so no live Gemini API access
or API key is required to run this suite.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.response import StoryData, TableItem

client = TestClient(app)


@pytest.fixture
def fake_story_data() -> StoryData:
    """A representative, schema-valid StoryData instance for mocking the LLM service."""
    return StoryData(
        title="Supercharging Digital Infrastructure: Pakistan Secures Guaranteed 17.7 Tbps Bandwidth",
        subtitle="Ministry of IT & Telecom expands international fiber capacity to backstop 5G rollouts and export growth.",
        source_context="Official announcement by Ministry of IT & Telecom (@MoitOfficial)",
        summary_table=[
            TableItem(
                pillar="Guaranteed International Bandwidth",
                metric="17.7+ Tbps",
                purpose="Prevents single-cable outage bottlenecks and lowers latency.",
            )
        ],
        story_markdown="# Supercharging Digital Infrastructure\n\n### 1. The Hook\n\nBody text here.",
        word_count=620,
    )


class TestHealthCheck:
    def test_health_check_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestGenerateStoryValidPayload:
    def test_generate_story_with_tweet_text(self, fake_story_data):
        """A valid payload with tweet_text should return a 200 with a well-formed StoryResponse."""
        with patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(return_value=fake_story_data),
        ) as mock_generate:
            response = client.post(
                "/api/v1/generate-story",
                json={
                    "tweet_text": (
                        "Ministry of IT & Telecom aggressively enabled guaranteed 17.7 "
                        "Tbps+ bandwidth for Pakistan via additional fiber optic cables."
                    ),
                    "author_handle": "@MoitOfficial",
                    "output_format": "markdown",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["title"] == fake_story_data.title
        assert body["data"]["word_count"] == 620
        assert len(body["data"]["summary_table"]) == 1
        assert body["data"]["summary_table"][0]["pillar"] == "Guaranteed International Bandwidth"

        # Ensure the LLM service was actually invoked with the extracted content and author handle.
        mock_generate.assert_awaited_once()
        _, kwargs = mock_generate.call_args
        assert "Ministry of IT" in kwargs["content"]
        assert kwargs["author_handle"] == "@MoitOfficial"

    def test_generate_story_without_author_handle(self, fake_story_data):
        """author_handle is optional; the request should still succeed without it."""
        with patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(return_value=fake_story_data),
        ):
            response = client.post(
                "/api/v1/generate-story",
                json={"tweet_text": "A short update with no author handle provided."},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_generate_story_docx_returns_download(self, fake_story_data):
        """The DOCX endpoint should return a downloadable Word file."""
        with patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(return_value=fake_story_data),
        ):
            response = client.post(
                "/api/v1/generate-story-docx",
                json={
                    "tweet_text": "A short update for a generated story document.",
                    "author_handle": "@MoitOfficial",
                },
            )

        assert response.status_code == 200
        assert (
            response.headers["content-type"]
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert "attachment;" in response.headers["content-disposition"]
        assert response.headers["content-disposition"].endswith(".docx\"")
        assert response.content.startswith(b"PK")

    def test_export_story_docx_returns_download(self, fake_story_data):
        """An existing generated story should be exportable as a Word file."""
        response = client.post(
            "/api/v1/export-story-docx",
            json=fake_story_data.model_dump(),
        )

        assert response.status_code == 200
        assert (
            response.headers["content-type"]
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert response.content.startswith(b"PK")

    def test_export_story_markdown_returns_download(self, fake_story_data):
        """An existing generated story should be exportable as organized Markdown."""
        response = client.post(
            "/api/v1/export-story-markdown",
            json=fake_story_data.model_dump(),
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert response.headers["content-disposition"].endswith(".md\"")
        assert b"# Supercharging Digital Infrastructure" in response.content
        assert b"## Key Facts" in response.content


class TestGenerateStoryInvalidPayload:
    def test_generate_story_missing_both_text_and_url(self):
        """Omitting both tweet_text and post_url should fail validation before
        reaching the extractor or LLM service."""
        response = client.post(
            "/api/v1/generate-story",
            json={"output_format": "markdown"},
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert any("tweet_text" in str(err) or "post_url" in str(err) for err in detail)

    def test_generate_story_empty_payload(self):
        """A completely empty JSON body should also fail validation."""
        response = client.post("/api/v1/generate-story", json={})
        assert response.status_code == 422

    def test_generate_story_unreachable_post_url(self):
        """A post_url that cannot be fetched should surface as a 400, not a 500."""
        response = client.post(
            "/api/v1/generate-story",
            json={"post_url": "https://this-domain-does-not-exist-xyz123.invalid/post/1"},
        )
        assert response.status_code == 400
        assert "post_url" in response.json()["detail"]

    def test_generate_story_llm_failure_propagates_status_code(self, fake_story_data):
        """If the LLM service raises an HTTPException, its status code should
        propagate unchanged rather than being flattened into a generic 500."""
        from fastapi import HTTPException

        with patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=502, detail="LLM provider is currently unavailable"
                )
            ),
        ):
            response = client.post(
                "/api/v1/generate-story",
                json={"tweet_text": "Some update text here."},
            )

        assert response.status_code == 502
