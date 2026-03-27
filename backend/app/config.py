from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # Telegram Bot
    telegram_bot_token: str

    # Database
    database_url: str = "sqlite:///./expense_tracker.db"

    # Application
    app_port: int = 8000
    app_host: str = "0.0.0.0"
    debug: bool = False

    # File Storage
    upload_dir: Path = Path("./uploads")
    ml_model_dir: Path = Path("./ml_models")
    statements_dir: Path = Path("../statements")

    # ML Settings
    ml_confidence_threshold_auto: float = 0.95
    ml_confidence_threshold_suggest: float = 0.50
    ml_min_training_samples: int = 50
    ml_retrain_interval: int = 10

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

# Ensure directories exist
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.ml_model_dir.mkdir(parents=True, exist_ok=True)
