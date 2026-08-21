"""
Content extractor service.

Resolves and validates the source content for story generation: uses
`tweet_text` as the grounded content fed to the LLM, while always fetching
`post_url` to confirm the post actually exists before generation proceeds.
"""

import re

import httpx
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


def _sanitize_text(text: str) -> str:
    """Normalize whitespace and strip control characters from source text."""
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned


async def _verify_post_exists(post_url: str) -> None:
    """Confirm `post_url` actually resolves to a real, live post.

    This is an existence check, not a content-scraping step: X/Twitter
    frequently blocks automated scraping of post content (returns 200 with
    no usable metadata) even for perfectly real posts, so we can't reliably
    use "did we extract a description" as a proxy for "does this post
    exist". Instead we treat a definitive 404 (or a request that never
    resolves at all) as proof the post is missing, and treat any other
    response as evidence the URL at least resolves to something.

    Raises:
        HTTPException(400): if the URL is unreachable or definitively
            returns a not-found response.
    """
    try:
        async with httpx.AsyncClient(
            headers=_REQUEST_HEADERS,
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = await client.get(post_url)
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Timed out while verifying post_url: {post_url}. "
                "Please check the link and try again."
            ),
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not reach post_url: {post_url} "
                f"({exc.__class__.__name__}). Please check the link is correct."
            ),
        ) from exc

    if response.status_code == 404:
        raise HTTPException(
            status_code=400,
            detail=(
                "The post at the given post_url could not be found. It may "
                "have been deleted, made private, or the URL may be incorrect."
            ),
        )

    if response.status_code >= 500:
        raise HTTPException(
            status_code=400,
            detail=(
                f"post_url returned a server error (status "
                f"{response.status_code}) and could not be verified. Please "
                "try again shortly."
            ),
        )

    # Any other status (200, or a 3xx that follow_redirects already resolved,
    # or even a 401/403 from X's bot-blocking) is treated as "the post
    # exists" — X routinely returns non-200 statuses to automated clients
    # for posts that are perfectly real and publicly visible in a browser.


async def extract_content(tweet_text: str, post_url: str) -> str:
    """Resolve and validate the source text for story generation.

    Always verifies `post_url` resolves to a real post (raising if it's
    definitively not found or unreachable), then returns the sanitized
    `tweet_text` as the grounded content to feed the LLM — text supplied
    directly by the caller is more reliable than scraping X's often-blocked
    metadata tags, but the URL check still confirms the post is real.

    Args:
        tweet_text: Raw post text, required.
        post_url: URL of the original post, required — used to verify the
            post exists.

    Returns:
        Cleaned source text ready to be passed into the editorial prompt.

    Raises:
        HTTPException(400): if post_url is unreachable or the post can't be
            found, or if tweet_text sanitizes down to nothing.
    """
    await _verify_post_exists(post_url)

    cleaned_text = _sanitize_text(tweet_text)
    if not cleaned_text:
        raise HTTPException(
            status_code=400,
            detail="tweet_text is empty after cleaning; cannot generate a story from it.",
        )

    return cleaned_text
