import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


def _units() -> list[str]:
    raw = os.environ.get("RANGKON_UNITS", "MK Rej,Bn 1,Bn 2,Bn 3")
    return [u.strip() for u in raw.split(",") if u.strip()]


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get("DATABASE_URL", "sqlite:///./data/rangkon.db")
    )
    admin_password: str = field(
        default_factory=lambda: os.environ.get("RANGKON_ADMIN_PASSWORD", "admin")
    )
    secret_key: str = field(
        default_factory=lambda: os.environ.get("RANGKON_SECRET_KEY", "dev-secret-change-me")
    )
    public_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "RANGKON_PUBLIC_BASE_URL", "http://localhost:8000"
        ).rstrip("/")
    )
    timezone: ZoneInfo = field(
        default_factory=lambda: ZoneInfo(os.environ.get("RANGKON_TIMEZONE", "Asia/Kuala_Lumpur"))
    )
    units: list[str] = field(default_factory=_units)
    checkin_opens_minutes_before: int = field(
        default_factory=lambda: int(os.environ.get("RANGKON_CHECKIN_OPENS_MINUTES", "120"))
    )
    whatsapp_provider: str = field(
        default_factory=lambda: os.environ.get("RANGKON_WHATSAPP_PROVIDER", "simulate")
    )
    whatsapp_token: str = field(default_factory=lambda: os.environ.get("WHATSAPP_TOKEN", ""))
    whatsapp_phone_number_id: str = field(
        default_factory=lambda: os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    )
    whatsapp_verify_token: str = field(
        default_factory=lambda: os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    )
    whatsapp_app_secret: str = field(
        default_factory=lambda: os.environ.get("WHATSAPP_APP_SECRET", "")
    )
    whatsapp_template_name: str = field(
        default_factory=lambda: os.environ.get("WHATSAPP_TEMPLATE_NAME", "")
    )
    whatsapp_template_lang: str = field(
        default_factory=lambda: os.environ.get("WHATSAPP_TEMPLATE_LANG", "ms")
    )
    whatsapp_api_version: str = field(
        default_factory=lambda: os.environ.get("WHATSAPP_API_VERSION", "v21.0")
    )


settings = Settings()
