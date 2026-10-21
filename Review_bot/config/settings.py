import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    BASE_DIR = Path(__file__).resolve().parent.parent
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

class Settings:
    """Centralized configuration manager for Review Bot."""
    
    # GitLab Settings
    GITLAB_URL: str = os.getenv("GITLAB_URL", "https://gitlab.com")
    GITLAB_TOKEN: str = os.getenv("GITLAB_TOKEN", "")
    GITLAB_PROJECT_ID: str = os.getenv("GITLAB_PROJECT_ID", "")

    # LLM & Review Provider Settings
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "none").lower()  # Default: none (Static Rules & Laya Engine). Options: openai, gemini, ollama, groq, none
    LLM_MODEL: str = os.getenv("LLM_MODEL", "none")
    
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_API_KEY: str = os.getenv("OLLAMA_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    # Local Repository Path (for cross-file checks without re-downloading)
    LOCAL_REPO_PATH: str = os.getenv("LOCAL_REPO_PATH", os.path.expanduser("~/projects/ivi_features"))

    # Review Settings
    REVIEW_STRICTNESS: str = os.getenv("REVIEW_STRICTNESS", "medium").lower()

    @classmethod
    def get_summary(cls) -> dict:
        return {
            "GitLab URL": cls.GITLAB_URL,
            "GitLab Token Set": bool(cls.GITLAB_TOKEN),
            "LLM Provider": cls.LLM_PROVIDER,
            "LLM Model": cls.LLM_MODEL,
            "OpenAI Key Set": bool(cls.OPENAI_API_KEY),
            "Gemini Key Set": bool(cls.GEMINI_API_KEY),
            "Ollama URL": cls.OLLAMA_BASE_URL,
        }

settings = Settings()
