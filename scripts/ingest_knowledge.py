"""Ingest `knowledge_base/` into Pinecone.

Usage: python scripts/ingest_knowledge.py [--reset]
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rag.ingestion import ingest  # noqa: E402, F401


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Delete the namespace before ingesting.")
    args = parser.parse_args()  # noqa: F841
    raise NotImplementedError


if __name__ == "__main__":
    main()
