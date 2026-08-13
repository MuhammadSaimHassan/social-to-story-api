"""
Content extractor service.

Resolves the actual source text to feed the LLM: uses `tweet_text` directly
when provided, otherwise fetches `post_url` and attempts to pull post content
from OpenGraph / Twitter meta tags.
"""

import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException

# Standard desktop User-Agent. Many sites (including x.com) return
# stripped-down or bot-blocked markup for unrecognized/empty user agents.
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Meta tags checked, in priority order, for post content.
_META_CANDIDATES = [
    ("property", "og:description"),
    ("name", "twitter:description"),
    ("property", "twitter:description"),
]


def _sanitize_text(text: str) -> str:
    """Normalize whitespace and strip control characters from source text."""
    if not text:
        return ""
    # Collapse runs of whitespace (including newlines/tabs) into single spaces.
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned


def _extract_meta_description(html: str) -> Optional[str]:
    """Parse HTML and return the first matching OpenGraph/Twitter description."""
    soup = BeautifulSoup(html, "html.parser")

    for attr, value in _META_CANDIDATES:
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            content = tag["content"].strip()
            if content:
                return content

    return None


async def _fetch_post_content(post_url: str) -> str:
    """Fetch `post_url` and extract post text from its meta tags.

    Raises:
        HTTPException(400): if the URL cannot be fetched or no usable
            content can be extracted from it.
    """
    try:
        async with httpx.AsyncClient(
            headers=_REQUEST_HEADERS,
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = await client.get(post_url)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Timed out while fetching post_url: {post_url}",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Failed to fetch post_url (status {exc.response.status_code}): {post_url}"
            ),
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not reach post_url: {post_url} ({exc.__class__.__name__})",
        ) from exc

    description = _extract_meta_description(response.text)

    if not description:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not extract post content from post_url. The page may "
                "require authentication, block automated requests, or lack "
                "OpenGraph/Twitter meta tags. Please provide 'tweet_text' directly instead."
            ),
        )

    return description


async def extract_content(
    tweet_text: Optional[str] = None,
    post_url: Optional[str] = None,
) -> str:
    """Resolve the source text for story generation.

    If `tweet_text` is provided, it is sanitized and returned directly
    (no network call is made). Otherwise, `post_url` is fetched and its
    OpenGraph/Twitter description meta tag is used as the source content.

    Args:
        tweet_text: Raw post text, if directly supplied.
        post_url: URL of the original post, used as a fallback source.

    Returns:
        Cleaned source text ready to be passed into the editorial prompt.

    Raises:
        HTTPException(400): if neither input yields usable content.
    """
    if tweet_text and tweet_text.strip():
        return _sanitize_text(tweet_text)

    if post_url and post_url.strip():
        raw_content = await _fetch_post_content(post_url.strip())
        return _sanitize_text(raw_content)

    # Should not normally be reached since StoryRequest already validates
    # that at least one of the two is present, but guarded here defensively
    # in case this service is called directly from elsewhere.
    raise HTTPException(
        status_code=400,
        detail="Either 'tweet_text' or 'post_url' must be provided to extract content.",
    )
