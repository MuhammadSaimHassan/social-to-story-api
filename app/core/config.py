"""
Application configuration.

Loads settings from environment variables (and a local .env file, if present)
using pydantic-settings. Import the shared `settings` instance anywhere in
the app rather than reading os.environ directly.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- LLM configuration ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    default_model: str = Field(default="gemini-3.6-flash", alias="DEFAULT_MODEL")

    # --- Image generation (Cloudflare Workers AI) ---
    # Google's free tier does not currently include quota for Gemini's
    # image-generation models (confirmed: paid-only as of mid-2026), so
    # cover images are generated via Cloudflare Workers AI instead, which
    # has a genuine free tier (10,000 neurons/day, no credit card) that
    # includes FLUX.1 Schnell for text-to-image.
    cloudflare_account_id: str = Field(default="", alias="CLOUDFLARE_ACCOUNT_ID")
    cloudflare_api_token: str = Field(default="", alias="CLOUDFLARE_API_TOKEN")
    cloudflare_image_model: str = Field(
        default="@cf/black-forest-labs/flux-1-schnell",
        alias="CLOUDFLARE_IMAGE_MODEL",
    )

    # --- App configuration ---
    app_env: str = Field(default="development", alias="APP_ENV")
    port: int = Field(default=8000, alias="PORT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so the .env file is only parsed once."""
    return Settings()


settings = get_settings()
