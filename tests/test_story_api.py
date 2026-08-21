"""
Tests for the Social-to-Story API.

Run with: pytest
The LLM service and extractor's network calls are mocked in all tests so no
live Gemini API access or network access is required to run this suite.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.response import StoryData, TableItem
from app.services import extractor

client = TestClient(app)

VALID_TWEET_TEXT = (
    "Pakistan has launched a new digital skills initiative to train 100,000 "
    "young people in cloud computing, artificial intelligence, cybersecurity, "
    "and software development."
)
VALID_AUTHOR_HANDLE = "@MoitOfficial"
VALID_POST_URL = "https://x.com/MoitOfficial/status/2085985308718563602"


def _valid_payload(**overrides) -> dict:
    payload = {
        "tweet_text": VALID_TWEET_TEXT,
        "author_handle": VALID_AUTHOR_HANDLE,
        "post_url": VALID_POST_URL,
        "output_format": "markdown",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def fake_story_data() -> StoryData:
    """A representative, schema-valid StoryData instance for mocking the LLM service."""
    return StoryData(
        title="Pakistan Launches Digital Skills Push to Train 100,000 Youth",
        subtitle="New initiative targets cloud, AI, cybersecurity, and software skills.",
        source_context=f"Official announcement ({VALID_AUTHOR_HANDLE})",
        summary_table=[
            TableItem(
                pillar="Digital Skills Training",
                metric="100,000 trainees",
                purpose="Builds a larger domestic tech workforce.",
            )
        ],
        story_markdown="# Pakistan Launches Digital Skills Push\n\n### 1. The Hook\n\nBody text here.",
        word_count=420,
    )


class TestHealthCheck:
    def test_health_check_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestGenerateStoryValidPayload:
    def test_generate_story_with_all_required_fields(self, fake_story_data):
        """A complete, valid payload should return 200 with a well-formed StoryResponse."""
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(return_value=VALID_TWEET_TEXT),
        ), patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(return_value=fake_story_data),
        ) as mock_generate:
            response = client.post("/api/v1/generate-story", json=_valid_payload())

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["title"] == fake_story_data.title

        mock_generate.assert_awaited_once()
        _, kwargs = mock_generate.call_args
        assert kwargs["author_handle"] == VALID_AUTHOR_HANDLE

    def test_author_handle_without_at_prefix_is_normalized(self, fake_story_data):
        """author_handle supplied without '@' should be accepted and normalized."""
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(return_value=VALID_TWEET_TEXT),
        ), patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(return_value=fake_story_data),
        ):
            response = client.post(
                "/api/v1/generate-story",
                json=_valid_payload(author_handle="MoitOfficial"),
            )

        assert response.status_code == 200


class TestGenerateStoryMissingFields:
    """All three fields (tweet_text, author_handle, post_url) are now required."""

    def test_missing_tweet_text(self):
        payload = _valid_payload()
        del payload["tweet_text"]
        response = client.post("/api/v1/generate-story", json=payload)
        assert response.status_code == 422

    def test_missing_author_handle(self):
        payload = _valid_payload()
        del payload["author_handle"]
        response = client.post("/api/v1/generate-story", json=payload)
        assert response.status_code == 422

    def test_missing_post_url(self):
        payload = _valid_payload()
        del payload["post_url"]
        response = client.post("/api/v1/generate-story", json=payload)
        assert response.status_code == 422

    def test_empty_payload(self):
        response = client.post("/api/v1/generate-story", json={})
        assert response.status_code == 422


class TestGenerateStoryInvalidInput:
    """The exact bug reported: trivial/junk input should never reach the LLM."""

    def test_trivial_tweet_text_rejected_before_llm(self):
        """'hello world.' (2 words) must fail validation immediately, matching
        the original bug report where this produced a fabricated story."""
        with patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(),
        ) as mock_generate:
            response = client.post(
                "/api/v1/generate-story",
                json=_valid_payload(tweet_text="hello world."),
            )

        assert response.status_code == 422
        assert "too short" in str(response.json()["detail"]).lower()
        # Critically: the LLM must never have been called for this input.
        mock_generate.assert_not_called()

    def test_invalid_post_url_domain_rejected(self):
        """A post_url that isn't an X/Twitter link should be rejected with a clear message."""
        response = client.post(
            "/api/v1/generate-story",
            json=_valid_payload(post_url="https://example.com/some-post"),
        )
        assert response.status_code == 422

    def test_malformed_post_url_rejected(self):
        response = client.post(
            "/api/v1/generate-story",
            json=_valid_payload(post_url="not-a-url"),
        )
        assert response.status_code == 422

    def test_invalid_author_handle_rejected(self):
        response = client.post(
            "/api/v1/generate-story",
            json=_valid_payload(author_handle="not a valid handle!!"),
        )
        assert response.status_code == 422


class TestGenerateStoryLLMRejectsInsufficientContent:
    """Even valid-shaped input can still be judged insufficient by the LLM itself."""

    def test_llm_is_sufficient_false_returns_422(self):
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(return_value=VALID_TWEET_TEXT),
        ), patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=422,
                    detail=(
                        "Unable to generate a story from the provided input: "
                        "The provided post text does not contain a specific "
                        "announcement, event, or claim that can be reported on."
                    ),
                )
            ),
        ):
            response = client.post("/api/v1/generate-story", json=_valid_payload())

        assert response.status_code == 422
        assert "unable to generate" in response.json()["detail"].lower()


class TestGenerateStoryPostNotFound:
    def test_unreachable_post_url_returns_400(self):
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=400,
                    detail="The post at the given post_url could not be found.",
                )
            ),
        ):
            response = client.post("/api/v1/generate-story", json=_valid_payload())

        assert response.status_code == 400
        assert "could not be found" in response.json()["detail"].lower()

    def test_llm_failure_status_code_propagates(self, fake_story_data):
        """If the LLM service raises an HTTPException, its status code should
        propagate unchanged rather than being flattened into a generic 500."""
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(return_value=VALID_TWEET_TEXT),
        ), patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=502, detail="LLM provider is currently unavailable"
                )
            ),
        ):
            response = client.post("/api/v1/generate-story", json=_valid_payload())

        assert response.status_code == 502


class TestExtractorPostVerification:
    """Direct tests of extractor.py's post-existence verification logic."""

    def test_404_raises_400(self):
        mock_response = httpx.Response(status_code=404, request=httpx.Request("GET", VALID_POST_URL))
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(return_value=mock_response),
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(extractor.extract_content(VALID_TWEET_TEXT, VALID_POST_URL))
        assert exc_info.value.status_code == 400
        assert "could not be found" in exc_info.value.detail.lower()

    def test_200_allows_extraction_to_proceed(self):
        mock_response = httpx.Response(
            status_code=200,
            request=httpx.Request("GET", VALID_POST_URL),
            content=b"<html></html>",
        )
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(return_value=mock_response),
        ):
            result = asyncio.run(extractor.extract_content(VALID_TWEET_TEXT, VALID_POST_URL))
        assert result == VALID_TWEET_TEXT

    def test_403_from_bot_blocking_still_allows_extraction(self):
        """X frequently returns 401/403 to automated clients for perfectly
        real, public posts — this must NOT be treated as 'post doesn't exist'."""
        mock_response = httpx.Response(status_code=403, request=httpx.Request("GET", VALID_POST_URL))
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(return_value=mock_response),
        ):
            result = asyncio.run(extractor.extract_content(VALID_TWEET_TEXT, VALID_POST_URL))
        assert result == VALID_TWEET_TEXT

    def test_connection_error_raises_400(self):
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(side_effect=httpx.ConnectError("connection failed")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(extractor.extract_content(VALID_TWEET_TEXT, VALID_POST_URL))
        assert exc_info.value.status_code == 400
