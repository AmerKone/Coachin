"""Frontend configuration read from the environment / root `.env`."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")
API_BASE: str = f"{BACKEND_URL}/api/v1"
REQUEST_TIMEOUT_SECONDS: float = 60.0
