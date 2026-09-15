from pydantic_settings import BaseSettings
from pydantic import AliasChoices, Field
from typing import Literal


class Settings(BaseSettings):
    LLM_PROVIDER: Literal["anthropic", "openai", "ollama"] = "openai"

    #ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("openai_key", "OPENAI_API_KEY"),
    )

    #ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    OPENAI_MODEL: str = "gpt-4o"

    OLLAMA_MODEL: str = "gemma3:4b"
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    CHROMA_PERSIST_DIR: str = "./chroma_db"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
