from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
import os


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    model_provider: str
    database_path: Path
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:2b"
    groq_model: str = "openai/gpt-oss-20b"
    groq_api_key: str | None = field(default=None, repr=False)


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    database_path = Path(os.getenv("BUSINESS_AGENT_DB", "data/business.db"))
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    return Settings(
        model_provider=os.getenv("MODEL_PROVIDER", "groq").strip().lower(),
        database_path=database_path,
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3.5:2b"),
        groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
    )
