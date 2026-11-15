import os
from dataclasses import dataclass

from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    api_id: int = int(os.getenv("API_ID", "0"))
    api_hash: str = os.getenv("API_HASH", "")
    mongo_uri: str = os.getenv("MONGO_URI", "")
    db_name: str = os.getenv("DB_NAME") or "flexible_vc"
    session_encryption_key: str = os.getenv("SESSION_ENCRYPTION_KEY", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


config = Config()


def validate_config() -> None:
    missing = []
    for key, value in (
        ("BOT_TOKEN", config.bot_token),
        ("API_ID", config.api_id),
        ("API_HASH", config.api_hash),
        ("MONGO_URI", config.mongo_uri),
        ("SESSION_ENCRYPTION_KEY", config.session_encryption_key),
    ):
        if not value:
            missing.append(key)
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
    try:
        Fernet(config.session_encryption_key.encode())
    except Exception as exc:
        raise RuntimeError("SESSION_ENCRYPTION_KEY is invalid. Generate a Fernet key and save it as a GitHub secret.") from exc
