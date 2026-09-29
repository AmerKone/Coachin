"""Sync `knowledge_base/` into Pinecone.

Usage: python scripts/ingest_knowledge.py [--dry-run]

Creates the index on first run. Safe to re-run: chunks are upserted under stable IDs and
vectors for deleted files or sections are removed, so Pinecone mirrors the folder.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE = ROOT / "knowledge_base"
sys.path.insert(0, str(ROOT / "backend"))

from app.rag.ingestion import ingest, load_documents, split_documents  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync the knowledge base into Pinecone.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be ingested without calling any API.")
    args = parser.parse_args()

    if args.dry_run:
        chunks = split_documents(load_documents(KNOWLEDGE_BASE))
        for source, count in sorted(Counter(c.metadata["source"] for c in chunks).items()):
            print(f"  {source}: {count} chunks")
        print(f"{len(chunks)} chunks total (dry run, nothing uploaded).")
        return 0

    try:
        result = ingest(KNOWLEDGE_BASE)
    except Exception as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1
    print(f"Synced {result.chunks} chunks from {result.sources} files; removed {result.deleted} stale chunks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
