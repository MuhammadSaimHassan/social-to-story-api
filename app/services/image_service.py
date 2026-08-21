"""
Image generation service.

Produces a relevant editorial cover image for a generated story, using
Cloudflare Workers AI (FLUX.1 Schnell by Black Forest Labs) rather than
Gemini. Google's free tier does not currently include quota for Gemini's
image-generation models — as of mid-2026 they are paid-only — so this uses
Cloudflare Workers AI instead, which has a genuine free tier: 10,000
"neurons"/day, no credit card required, enough for roughly 200+ images/day
on FLUX.1 Schnell.

Image generation is treated as best-effort: any failure here (safety
block, quota, network issue, missing credentials) returns (None, None)
rather than raising, so a broken image call never blocks story
generation — the written story is this API's primary deliverable, the
image is a bonus.
"""

import base64
import binascii
import logging
from typing import Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4/accounts"
_REQUEST_TIMEOUT_SECONDS = 30.0


def _build_image_prompt(content: str, author_handle: Optional[str]) -> str:
    """Build an image prompt grounded in the source post, deliberately
    steered toward abstract/symbolic editorial illustration rather than a
    literal depiction — this avoids ever attempting to render a specific
    real, identifiable person (the stories are frequently about named
    government officials and agencies)."""
    attribution = f" from {author_handle}" if author_handle else ""

    return (
        "Professional editorial news illustration relevant to the "
        f"following announcement{attribution}: \"{content}\". "
        "Clean, modern flat-design editorial illustration suitable as a "
        "header image for a technology/policy news article. Abstract, "
        "symbolic, conceptual imagery — network lines, data visualization, "
        "infrastructure or government iconography, city skylines, abstract "
        "technology motifs — rather than a literal photo or any specific "
        "real person. No readable text, logos, watermarks, or flags of a "
        "specific country. Landscape composition, 16:9."
    )


async def generate_story_image(
    content: str, author_handle: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Generate a cover image relevant to the source content, via
    Cloudflare Workers AI (FLUX.1 Schnell).

    Best-effort: any failure results in (None, None). Errors are logged
    but never raised — the caller (the story router) proceeds with a
    story that simply has no cover image rather than failing the whole
    request over an image generation hiccup.

    Args:
        content: The same grounded source text passed to the story LLM
            call, used as the basis for the image prompt.
        author_handle: Optional handle used for attribution context in
            the prompt.

    Returns:
        A (base64_image_data, mime_type) tuple, or (None, None) if
        generation wasn't possible for any reason.
    """
    if not settings.cloudflare_account_id or not settings.cloudflare_api_token:
        logger.info(
            "Cover image generation skipped: CLOUDFLARE_ACCOUNT_ID/"
            "CLOUDFLARE_API_TOKEN not configured."
        )
        return None, None

    prompt = _build_image_prompt(content, author_handle)
    url = (
        f"{_CLOUDFLARE_API_BASE}/{settings.cloudflare_account_id}/ai/run/"
        f"{settings.cloudflare_image_model}"
    )

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.cloudflare_api_token}",
                    "Content-Type": "application/json",
                },
                json={"prompt": prompt},
            )
    except httpx.HTTPError as exc:
        logger.warning("Cover image generation failed (network error): %s", exc)
        return None, None

    if response.status_code != 200:
        # Never raise on a bad status — just log enough to diagnose (e.g.
        # 401 = bad token, 429 = neuron budget exhausted for the day) and
        # treat it the same as "no image".
        logger.warning(
            "Cover image generation failed (HTTP %s): %s",
            response.status_code,
            response.text[:500],
        )
        return None, None

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("Cover image generation failed (invalid JSON): %s", exc)
        return None, None

    if not payload.get("success", False):
        logger.warning(
            "Cover image generation failed (API reported failure): %s",
            payload.get("errors"),
        )
        return None, None

    image_b64 = (payload.get("result") or {}).get("image")
    if not image_b64:
        logger.warning("Cover image generation failed (no image in response).")
        return None, None

    # Cloudflare returns the image already base64-encoded — validate it
    # decodes cleanly before handing it back, rather than trusting it blind.
    try:
        base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        logger.warning("Cover image generation failed (invalid base64): %s", exc)
        return None, None

    return image_b64, "image/jpeg"
