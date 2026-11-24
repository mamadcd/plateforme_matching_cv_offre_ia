from pydantic_settings import BaseSettings
from pydantic import AliasChoices, Field
from typing import Literal


class Settings(BaseSettings):
    LLM_PROVIDER: Literal["anthropic", "openai", "ollama"] = "ollama"

    #ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("openai_key", "OPENAI_API_KEY"),
    )

    #ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    #OPENAI_MODEL: str = "gpt-4o"

    OLLAMA_MODEL: str = "qwen2.5:1.5b"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_VISION_MODEL: str = "granite3.2-vision:2b"
    OLLAMA_TEXT_MODEL: str = "qwen2.5:1.5b"
    OLLAMA_NUM_CTX: int = 3072
    OLLAMA_NUM_THREAD: int = 8
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    CHROMA_PERSIST_DIR: str = "./chroma_db_v2"
    MAX_UPLOAD_SIZE_MB: int = 10
    FRONTEND_ORIGINS: str = "http://localhost:5173"
    DATABASE_URL: str = ""
    AUTH_SECRET_KEY: str = ""
    AUTH_TOKEN_EXPIRE_MINUTES: int = 480
    AUTH_COOKIE_SECURE: bool = True
    MATCH_EVALUATION_DATASET: str = "app/data/evaluation/matching_cases.json"
    MATCH_EVALUATION_REPORT: str = "app/data/evaluation/latest_report.json"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
