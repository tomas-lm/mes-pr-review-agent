from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    github_app_id: str | None = Field(default=None, alias="GITHUB_APP_ID")
    github_app_private_key: str | None = Field(default=None, alias="GITHUB_APP_PRIVATE_KEY")
    github_webhook_secret: str = Field(default="change-me", alias="GITHUB_WEBHOOK_SECRET")
    github_api_base_url: str = Field(default="https://api.github.com", alias="GITHUB_API_BASE_URL")
    llm_api_base_url: str = Field(default="https://api.telnyx.com/v2/ai", alias="LLM_API_BASE_URL")
    llm_model: str = Field(default="moonshotai/Kimi-K2.6", alias="LLM_MODEL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    agent_max_turns: int = Field(default=12, alias="AGENT_MAX_TURNS")
    review_notes_dir: str = Field(default="review_runs", alias="REVIEW_NOTES_DIR")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
