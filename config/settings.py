import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Data paths
INPUT_DIR = PROJECT_ROOT / "data" / "input"
PDF_DIR = PROJECT_ROOT / "data" / "pdfs"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"

# Ensure directories exist
PDF_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
INPUT_DIR.mkdir(parents=True, exist_ok=True)

# LLM settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Scholar API keys (comma-separated in .env)
SCRAPINGDOG_KEYS = [k.strip() for k in os.getenv("SCRAPINGDOG_KEYS", "").split(",") if k.strip()]
SERPAPI_KEYS = [k.strip() for k in os.getenv("SERPAPI_KEYS", "").split(",") if k.strip()]

# PDF parser: "firered" (default), "mineru", or "pymupdf"
PDF_PARSER = os.getenv("PDF_PARSER", "firered")

# FireRed-OCR settings
FIRERED_MODEL_DIR = os.getenv("FIRERED_MODEL_DIR", "FireRedTeam/FireRed-OCR")
FIRERED_OCR_DIR = Path(os.getenv("FIRERED_OCR_DIR", str(Path.home() / "code" / "FireRed-OCR")))

# Parser settings
CONTEXT_SENTENCES = 3  # sentences around citation to capture

# Download settings
MAX_DOWNLOAD_RETRIES = 3
DOWNLOAD_TIMEOUT = 30
