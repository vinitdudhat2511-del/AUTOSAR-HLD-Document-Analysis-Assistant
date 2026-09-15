import os
from pydantic_settings import BaseSettings

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DEFAULT_DB_PATH = os.path.join(_BACKEND_DIR, "autosar_assistant.db").replace("\\", "/")

class Settings(BaseSettings):
    # Application
    APP_NAME: str = "AUTOSAR HLD Document Analysis Assistant API"
    APP_VERSION: str = "1.3.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
    
    # LLM Configuration (Configurable for any approved LLM: Llama, Mistral, Qwen, DeepSeek)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    
    # Embeddings Configuration (Supports BGE, E5, Sentence Transformers)
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    
    # Vector DB & Storage (Absolute paths to ensure consistency across execution contexts)
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", os.path.join(_BACKEND_DIR, "chroma_db"))
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", os.path.join(_BACKEND_DIR, "uploads"))
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{_DEFAULT_DB_PATH}")
    
    # Security, CORS & Governance
    CORS_ALLOWED_ORIGINS: str = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501")
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50 MB
    
    # Demo Data Seeding Gate (Disabled by default for secure deployment)
    SEED_DEMO_DATA: bool = os.getenv("SEED_DEMO_DATA", "false").lower() in ("true", "1", "yes")
    DEFAULT_ADMIN_PASSWORD: str = os.getenv("DEFAULT_ADMIN_PASSWORD", "Admin@123")
    DEFAULT_ARCHITECT_PASSWORD: str = os.getenv("DEFAULT_ARCHITECT_PASSWORD", "Arch@123")
    DEFAULT_ENGINEER_PASSWORD: str = os.getenv("DEFAULT_ENGINEER_PASSWORD", "Eng@123")
    
    # Session Security
    SESSION_TOKEN_EXPIRE_HOURS: int = int(os.getenv("SESSION_TOKEN_EXPIRE_HOURS", "12"))

settings = Settings()
