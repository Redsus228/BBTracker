from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+asyncpg://Redsus:1147@cnpg-db-set-rw:5432/BBTDbase"
    jwt_secret: str = "8f3b2a9c1d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a"
    jwt_expires_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()