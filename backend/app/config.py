from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        case_sensitive=False,
    )

    # Telegram Bot
    telegram_bot_token: str

    # Database
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'expense_tracker.db').as_posix()}"

    # Application
    app_port: int = 8000
    app_host: str = "0.0.0.0"
    debug: bool = False

    # File Storage
    upload_dir: Path = REPO_ROOT / "uploads"
    ml_model_dir: Path = REPO_ROOT / "ml_models"
    statements_dir: Path = REPO_ROOT / "statements"

    # ML Settings
    ml_confidence_threshold_auto: float = 0.95
    ml_confidence_threshold_suggest: float = 0.50
    ml_min_training_samples: int = 50
    ml_retrain_interval: int = 10

    # Google Sheets bill export
    google_sheets_bill_export_enabled: bool = False
    google_sheets_bill_export_spreadsheet: str = ""
    google_sheets_service_account_json: str = ""


settings = Settings()


def _normalize_sqlite_url(database_url: str) -> str:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return database_url
    raw_path = database_url[len(prefix):]
    if not raw_path:
        return database_url
    if raw_path.startswith("/") or (len(raw_path) > 1 and raw_path[1] == ":"):
        return database_url
    absolute_path = (BACKEND_DIR / raw_path).resolve()
    return f"sqlite:///{absolute_path.as_posix()}"


def _resolve_repo_path(path_value: Path | str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


settings.database_url = _normalize_sqlite_url(settings.database_url)
settings.upload_dir = _resolve_repo_path(settings.upload_dir)
settings.ml_model_dir = _resolve_repo_path(settings.ml_model_dir)
settings.statements_dir = _resolve_repo_path(settings.statements_dir)
if settings.google_sheets_service_account_json:
    settings.google_sheets_service_account_json = str(
        _resolve_repo_path(settings.google_sheets_service_account_json)
    )

# Ensure directories exist
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.ml_model_dir.mkdir(parents=True, exist_ok=True)
