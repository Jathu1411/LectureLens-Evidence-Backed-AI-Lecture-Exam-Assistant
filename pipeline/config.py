"""
Configuration settings for the Lecture Video to Study Guide pipeline.
Loads from environment variables or .env file with safe local defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(BASE_DIR / "output")))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATES_DIR = Path(os.getenv("TEMPLATES_DIR", str(BASE_DIR / "templates")))

# Database configuration (PostgreSQL default, optional SQLite fallback)
DB_TYPE = os.getenv("DB_TYPE", "postgres").lower()  # "postgres" or "sqlite"
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME = os.getenv("POSTGRES_DB", "lecture_guide")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
DB_URI = os.getenv(
    "DATABASE_URL",
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    if DB_PASSWORD
    else f"postgresql://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)
SQLITE_PATH = Path(os.getenv("SQLITE_PATH", str(BASE_DIR / "output" / "lecture_guide.db")))

# Ollama configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3:latest")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))

# Whisper configuration
# Use large-v3 if CUDA is available, otherwise medium for CPU / Apple Silicon
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")  # "auto", "cpu", "cuda"
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "auto")  # "auto", "int8", "float16", "float32"
WHISPER_LANGUAGE = "en"  # Explicitly required by AGENTS.md
WHISPER_VAD_FILTER = True  # Explicitly required by AGENTS.md

# Video & Slide processing configuration
FRAME_SAMPLE_FPS = float(os.getenv("FRAME_SAMPLE_FPS", "1.0"))  # Sample 1 frame per second
SLIDE_SSIM_THRESHOLD = float(os.getenv("SLIDE_SSIM_THRESHOLD", "0.85"))  # Below this indicates change
MIN_SLIDE_DURATION_SEC = float(os.getenv("MIN_SLIDE_DURATION_SEC", "3.0"))  # Debounce rapid transitions

# OCR & Reliability settings
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "tesseract")
OCR_MIN_CHARS = int(os.getenv("OCR_MIN_CHARS", "15"))
OCR_MIN_ALPHA_RATIO = float(os.getenv("OCR_MIN_ALPHA_RATIO", "0.5"))

# Summarization chunking (in seconds)
# AGENTS.md specifies: Chunk by ~10-15 minute segments, prefer slide boundaries
CHUNK_MIN_SECONDS = int(os.getenv("CHUNK_MIN_SECONDS", "600"))   # 10 minutes
CHUNK_TARGET_SECONDS = int(os.getenv("CHUNK_TARGET_SECONDS", "720")) # 12 minutes
CHUNK_MAX_SECONDS = int(os.getenv("CHUNK_MAX_SECONDS", "900"))   # 15 minutes

# Virtual Windowing configuration (in seconds)
WINDOW_DURATION_SEC = int(os.getenv("WINDOW_DURATION_SEC", "1800"))  # 30 minutes
WINDOW_OVERLAP_SEC = int(os.getenv("WINDOW_OVERLAP_SEC", "180"))     # 3 minutes

# Advanced Visual Filter settings
PHASH_THRESHOLD = int(os.getenv("PHASH_THRESHOLD", "10"))  # Hamming distance <= 10 indicates near-identical
TEMPORAL_PERSISTENCE_SEC = float(os.getenv("TEMPORAL_PERSISTENCE_SEC", "2.5"))  # Minimum stable duration for a slide change
ROI_ANALYSIS_SECONDS = float(os.getenv("ROI_ANALYSIS_SECONDS", "180.0"))  # Seconds of video to inspect for Presentation ROI
ROI_CONFIDENCE_THRESHOLD = float(os.getenv("ROI_CONFIDENCE_THRESHOLD", "0.70"))
OCR_CONFIDENCE_THRESHOLD = float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "45.0"))

# Worker Concurrency settings
MAX_AUDIO_WORKERS = int(os.getenv("MAX_AUDIO_WORKERS", "1"))
MAX_VISUAL_WORKERS = int(os.getenv("MAX_VISUAL_WORKERS", "2"))
MAX_OCR_WORKERS = int(os.getenv("MAX_OCR_WORKERS", "2"))
MAX_LLM_WORKERS = int(os.getenv("MAX_LLM_WORKERS", "1"))

