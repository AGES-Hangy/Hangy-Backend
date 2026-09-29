import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def required_environment_variable(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = required_environment_variable("DATABASE_URL")
    jwt_secret_key: str = required_environment_variable("JWT_SECRET_KEY")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    access_token_expire_minutes: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    )
    password_reset_token_expire_minutes: int = int(
        os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "10")
    )
    cors_origins: tuple[str, ...] = tuple(
        os.getenv("CORS_ORIGINS", "http://localhost:8081").split(",")
    )
    invite_link_base_url: str = os.getenv("INVITE_LINK_BASE_URL", "hangy://invite/")
    frontend_base_url: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:8081")
    expo_access_token: str | None = os.getenv("EXPO_ACCESS_TOKEN")
    terms_version: str = os.getenv("TERMS_VERSION", "2026-08-01")
    terms_published_at: str = os.getenv("TERMS_PUBLISHED_AT", "2026-08-01T00:00:00Z")
    terms_url: str = os.getenv("TERMS_URL", "https://hangy.app/termos/2026-08-01")
    terms_summary: str = os.getenv(
        "TERMS_SUMMARY", "Termos de uso e política de privacidade do Hangy."
    )


settings = Settings()
