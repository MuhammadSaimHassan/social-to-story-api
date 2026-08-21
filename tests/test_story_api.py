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
        # No story_length supplied -> passed through as None (auto/model decides).
        assert kwargs["requested_length"] is None

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


class TestGenerateStoryUserControlledLength:
    """The caller, not the model, now controls whether the story is short or long."""

    @pytest.mark.parametrize("length", ["short", "long"])
    def test_requested_length_is_forwarded_to_llm_service(self, fake_story_data, length):
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(return_value=VALID_TWEET_TEXT),
        ), patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(return_value=fake_story_data),
        ) as mock_generate:
            response = client.post(
                "/api/v1/generate-story",
                json=_valid_payload(story_length=length),
            )

        assert response.status_code == 200
        _, kwargs = mock_generate.call_args
        assert kwargs["requested_length"] == length

    def test_story_length_is_case_insensitive_and_trimmed(self, fake_story_data):
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(return_value=VALID_TWEET_TEXT),
        ), patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(return_value=fake_story_data),
        ) as mock_generate:
            response = client.post(
                "/api/v1/generate-story",
                json=_valid_payload(story_length="  SHORT  "),
            )

        assert response.status_code == 200
        _, kwargs = mock_generate.call_args
        assert kwargs["requested_length"] == "short"

    def test_omitted_story_length_defaults_to_none(self, fake_story_data):
        payload = _valid_payload()
        payload.pop("story_length", None)
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(return_value=VALID_TWEET_TEXT),
        ), patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(return_value=fake_story_data),
        ) as mock_generate:
            response = client.post("/api/v1/generate-story", json=payload)

        assert response.status_code == 200
        _, kwargs = mock_generate.call_args
        assert kwargs["requested_length"] is None

    def test_invalid_story_length_value_rejected(self):
        response = client.post(
            "/api/v1/generate-story",
            json=_valid_payload(story_length="medium"),
        )
        assert response.status_code == 422

    def test_llm_service_forces_story_length_from_caller(self):
        """Even if the model's own output disagrees, the response must
        reflect the caller's requested length, not the model's."""
        from app.services import llm_service

        fake_parsed_dict = {
            "is_sufficient": True,
            "rejection_reason": None,
            "story_length": "long",  # model says long...
            "title": "A Title",
            "subtitle": "A Subtitle",
            "source_context": "Source",
            "summary_table": [],
            "story_markdown": "Body text " * 20,
        }

        class _FakeResponse:
            parsed = fake_parsed_dict
            text = None
            candidates = []

        with patch(
            "app.services.llm_service.settings"
        ) as mock_settings, patch(
            "app.services.llm_service._get_client"
        ) as mock_get_client:
            mock_settings.gemini_api_key = "fake-key"
            mock_settings.default_model = "fake-model"
            mock_client = mock_get_client.return_value
            mock_client.aio.models.generate_content = AsyncMock(return_value=_FakeResponse())

            result = asyncio.run(
                llm_service.generate_story_from_text(
                    content=VALID_TWEET_TEXT,
                    author_handle=VALID_AUTHOR_HANDLE,
                    requested_length="short",  # ...but the caller asked for short
                )
            )

        assert result.story_length == "short"


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


class TestGenerateStoryWithCoverImage:
    """The story router runs image generation concurrently with the text
    story and attaches the result — best-effort, never blocking success."""

    def test_successful_image_is_attached_to_response(self, fake_story_data):
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(return_value=VALID_TWEET_TEXT),
        ), patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(return_value=fake_story_data),
        ), patch(
            "app.routers.story.image_service.generate_story_image",
            new=AsyncMock(return_value=("ZmFrZWJhc2U2NGRhdGE=", "image/png")),
        ) as mock_image:
            response = client.post("/api/v1/generate-story", json=_valid_payload())

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["cover_image_base64"] == "ZmFrZWJhc2U2NGRhdGE="
        assert body["cover_image_mime_type"] == "image/png"

        # Confirm the image call was grounded in the same extracted content.
        mock_image.assert_awaited_once()
        _, kwargs = mock_image.call_args
        assert kwargs["content"] == VALID_TWEET_TEXT
        assert kwargs["author_handle"] == VALID_AUTHOR_HANDLE

    def test_image_failure_does_not_break_story_generation(self, fake_story_data):
        """If image generation fails outright, the story must still succeed
        with null image fields — image generation is best-effort."""
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(return_value=VALID_TWEET_TEXT),
        ), patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(return_value=fake_story_data),
        ), patch(
            "app.routers.story.image_service.generate_story_image",
            new=AsyncMock(side_effect=RuntimeError("image API exploded")),
        ):
            response = client.post("/api/v1/generate-story", json=_valid_payload())

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["cover_image_base64"] is None
        assert body["cover_image_mime_type"] is None
        assert body["title"] == fake_story_data.title

    def test_no_image_generated_returns_null_fields_not_error(self, fake_story_data):
        """generate_story_image() returning (None, None) — its own normal
        best-effort failure path — must not surface as an API error."""
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(return_value=VALID_TWEET_TEXT),
        ), patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(return_value=fake_story_data),
        ), patch(
            "app.routers.story.image_service.generate_story_image",
            new=AsyncMock(return_value=(None, None)),
        ):
            response = client.post("/api/v1/generate-story", json=_valid_payload())

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["cover_image_base64"] is None

    def test_story_rejection_does_not_wait_on_image(self, fake_story_data):
        """If the LLM rejects the content as insufficient, the request should
        still fail with 422 regardless of the image task's outcome."""
        with patch(
            "app.routers.story.extractor.extract_content",
            new=AsyncMock(return_value=VALID_TWEET_TEXT),
        ), patch(
            "app.routers.story.llm_service.generate_story_from_text",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=422,
                    detail="Unable to generate a story from the provided input: too vague.",
                )
            ),
        ), patch(
            "app.routers.story.image_service.generate_story_image",
            new=AsyncMock(return_value=("somebase64", "image/png")),
        ):
            response = client.post("/api/v1/generate-story", json=_valid_payload())

        assert response.status_code == 422


class TestImageServiceUnit:
    """Direct tests of image_service.py's own internal behavior."""

    def test_missing_credentials_returns_none_without_calling_api(self):
        from app.services import image_service

        with patch.object(image_service.settings, "cloudflare_account_id", ""), patch.object(
            image_service.settings, "cloudflare_api_token", "some-token"
        ):
            result = asyncio.run(
                image_service.generate_story_image(VALID_TWEET_TEXT, VALID_AUTHOR_HANDLE)
            )
        assert result == (None, None)

    def test_network_error_returns_none_none(self):
        from app.services import image_service

        class RaisingAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                import httpx

                raise httpx.ConnectError("boom")

        with patch.object(
            image_service.settings, "cloudflare_account_id", "fake-account"
        ), patch.object(
            image_service.settings, "cloudflare_api_token", "fake-token"
        ), patch(
            "app.services.image_service.httpx.AsyncClient", RaisingAsyncClient
        ):
            result = asyncio.run(
                image_service.generate_story_image(VALID_TWEET_TEXT, VALID_AUTHOR_HANDLE)
            )
        assert result == (None, None)

    def test_non_200_response_returns_none_none(self):
        from app.services import image_service

        class FakeResponse:
            status_code = 429
            text = "rate limited"

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                return FakeResponse()

        with patch.object(
            image_service.settings, "cloudflare_account_id", "fake-account"
        ), patch.object(
            image_service.settings, "cloudflare_api_token", "fake-token"
        ), patch(
            "app.services.image_service.httpx.AsyncClient", FakeAsyncClient
        ):
            result = asyncio.run(
                image_service.generate_story_image(VALID_TWEET_TEXT, VALID_AUTHOR_HANDLE)
            )
        assert result == (None, None)

    def test_response_with_no_image_returns_none_none(self):
        from app.services import image_service

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"success": True, "result": {}}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                return FakeResponse()

        with patch.object(
            image_service.settings, "cloudflare_account_id", "fake-account"
        ), patch.object(
            image_service.settings, "cloudflare_api_token", "fake-token"
        ), patch(
            "app.services.image_service.httpx.AsyncClient", FakeAsyncClient
        ):
            result = asyncio.run(
                image_service.generate_story_image(VALID_TWEET_TEXT, VALID_AUTHOR_HANDLE)
            )
        assert result == (None, None)

    def test_response_with_image_returns_base64_and_mime(self):
        from app.services import image_service

        import base64

        fake_b64 = base64.b64encode(b"fake-jpeg-bytes").decode("utf-8")

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"success": True, "result": {"image": fake_b64}}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                return FakeResponse()

        with patch.object(
            image_service.settings, "cloudflare_account_id", "fake-account"
        ), patch.object(
            image_service.settings, "cloudflare_api_token", "fake-token"
        ), patch(
            "app.services.image_service.httpx.AsyncClient", FakeAsyncClient
        ):
            encoded, mime_type = asyncio.run(
                image_service.generate_story_image(VALID_TWEET_TEXT, VALID_AUTHOR_HANDLE)
            )

        assert base64.b64decode(encoded) == b"fake-jpeg-bytes"
        assert mime_type == "image/jpeg"
