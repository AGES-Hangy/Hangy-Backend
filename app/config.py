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
    # Keys the HMAC that offsets each event's approximate point; rotating it
    # only affects points computed afterwards.
    location_obfuscation_secret: str = required_environment_variable(
        "LOCATION_OBFUSCATION_SECRET"
    )
    # Must stay above the largest offset (350 m) so the real address is always
    # inside the area drawn around the approximate point.
    private_event_area_radius_m: int = int(
        os.getenv("PRIVATE_EVENT_AREA_RADIUS_M", "500")
    )
    expo_access_token: str | None = os.getenv("EXPO_ACCESS_TOKEN")
    # How far ahead of starts_at the "event starting" job warns participants.
    starting_soon_window_minutes: int = int(
        os.getenv("STARTING_SOON_WINDOW_MINUTES", "60")
    )
    aws_region: str = os.getenv("AWS_REGION", "us-east-1").strip()
    s3_bucket_name: str = os.getenv("S3_BUCKET_NAME", "").strip()
    aws_s3_bucket: str = os.getenv("AWS_S3_BUCKET", "").strip()
    image_max_size_bytes: int = int(os.getenv("IMAGE_MAX_SIZE_BYTES", "5242880"))
    terms_version: str = os.getenv("TERMS_VERSION", "2026-08-01")
    terms_published_at: str = os.getenv("TERMS_PUBLISHED_AT", "2026-08-01T00:00:00Z")
    terms_url: str = os.getenv("TERMS_URL", "https://hangy.app/termos/2026-08-01")
    terms_summary: str = os.getenv(
        "TERMS_SUMMARY", "Termos de uso e política de privacidade do Hangy."
    )
    # Must not exceed the length of the user.description column (500).
    profile_description_max_length: int = int(
        os.getenv("PROFILE_DESCRIPTION_MAX_LENGTH", "500")
    )

    @property
    def s3_public_base_url(self) -> str:
        if not self.aws_s3_bucket:
            return ""
        return f"https://{self.aws_s3_bucket}.s3.{self.aws_region}.amazonaws.com"


settings = Settings()
