import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:opspilot@localhost:5432/opspilot")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Agents' vote weights for the confidence score (sum = 1.0)
SOURCE_WEIGHTS = {"logs": 0.30, "health": 0.25, "deployments": 0.20, "rag": 0.25}
LOW_CONFIDENCE_THRESHOLD = 0.50   # below this, approval needs an explicit acknowledgement
DEPLOY_WINDOW_MINUTES = 120       # a deployment this close before the incident start is suspicious
