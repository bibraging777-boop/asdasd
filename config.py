"""Application settings, loaded from the environment / a local ``.env`` file."""
from __future__ import annotations

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    BOT_TOKEN: SecretStr
    DATABASE_URL: str = "sqlite+aiosqlite:///./dating_bot.db"
    # Optional: persistent FSM storage. Falls back to in-memory storage.
    REDIS_URL: str | None = None
    LOG_LEVEL: str = "INFO"

    # Sponsor channel (numeric id such as -1001234567890 or @username).
    # The bot must be an administrator of the channel. Empty disables the check.
    SPONSOR_CHANNEL_ID: str | None = None
    SPONSOR_CHANNEL_URL: str | None = None
    SUBSCRIPTION_CACHE_TTL: int = 300

    # --- Monetization -----------------------------------------------------
    STARTING_BALANCE: int = 30
    PRICE_VIEW_PHOTOS_ONLY: int = 2
    PRICE_VIEW_BIO_ONLY: int = 1
    PRICE_VIEW_FULL_PROFILE: int = 3
    PRICE_SEND_ANON_MSG: int = 5
    PRICE_SEND_NAMED_MSG: int = 3
    PRICE_REQUEST_PM: int = 15
    REFUND_ON_PM_REJECT: bool = True
    # (coins, price in Telegram Stars); env value is JSON: [[50,25],[150,65]]
    COIN_PACKAGES: list[tuple[int, int]] = [(50, 25), (150, 65), (500, 200)]
    # When true, purchases are credited instantly without a real payment.
    # Never enable in production.
    PAYMENTS_MOCK: bool = False

    # --- Profile limits ---------------------------------------------------
    MIN_AGE: int = 18
    MAX_AGE: int = 99
    MAX_PHOTOS: int = 5
    BIO_MIN_LENGTH: int = 10
    BIO_MAX_LENGTH: int = 800
    CITY_MAX_LENGTH: int = 64
    MESSAGE_MAX_LENGTH: int = 1000

    @field_validator("SPONSOR_CHANNEL_ID", "SPONSOR_CHANNEL_URL", "REDIS_URL", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def sponsor_chat_id(self) -> int | str | None:
        raw = self.SPONSOR_CHANNEL_ID
        if raw is None:
            return None
        return int(raw) if raw.lstrip("-").isdigit() else raw

    @property
    def sponsor_url(self) -> str | None:
        if self.SPONSOR_CHANNEL_URL:
            return self.SPONSOR_CHANNEL_URL
        raw = self.SPONSOR_CHANNEL_ID
        if raw and raw.startswith("@"):
            return f"https://t.me/{raw[1:]}"
        return None


settings = Settings()  # type: ignore[call-arg]
