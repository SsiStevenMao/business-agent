from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    ollama_host: str
    ollama_model: str
    database_path: Path


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    database_path = Path(os.getenv("BUSINESS_AGENT_DB", "data/business.db"))
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    return Settings(
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3.5:2b"),
        database_path=database_path,
    )
