from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_NAME: str = "智慧实验室危险化学品监管系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    SECRET_KEY: str = "your-secret-key-change-in-production-2024"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    DATABASE_URL: str = "sqlite:///./chemical_lab.db"

    CORS_ORIGINS: List[str] = ["*"]

    DAILY_REPORT_HOUR: int = 0
    DAILY_REPORT_MINUTE: int = 0

    class Config:
        env_file = ".env"


settings = Settings()
