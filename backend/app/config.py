"""
Configuration — every value comes from the environment (.env).
No service in this codebase knows where it is running; it only
knows hostnames and keys given to it here.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Node identity
    node_name: str = "local-1"

    # API security (stopgap until Phase 3 JWT auth)
    api_key: str = "change-me"

    # Auth (Phase 3)
    jwt_secret: str = ""              # empty -> falls back to api_key
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    # Brain — OpenRouter
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    model_fast: str = "openrouter/free"
    model_smart: str = "openrouter/free"

    # Brain — local fallback (Ollama, OpenAI-compatible)
    ollama_base_url: str = ""
    ollama_model: str = "qwen2.5"

    # Memory (Phase 2)
    embedding_model: str = "BAAI/bge-small-en-v1.5"   # 384-dim, matches the facts table
    memory_top_k: int = 5
    memory_min_similarity: float = 0.45
    memory_dedup_similarity: float = 0.90
    distill_enabled: bool = True
    distill_interval_hours: float = 6

    # Generation
    max_tokens: int = 1024
    max_history_messages: int = 30
    max_tool_rounds: int = 6

    # Persona
    assistant_name: str = "Jarvis"
    user_title: str = "sir"

    # Data layer
    database_url: str = "postgresql+asyncpg://jarvis:jarvis@postgres:5432/jarvis"
    redis_url: str = "redis://redis:6379/0"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
