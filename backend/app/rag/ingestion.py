"""Load, chunk, and upsert knowledge-base documents into Pinecone."""

from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: F401

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}


def load_documents(root: Path) -> list[Document]:
    """Load every supported file under `root`.

    Each document's metadata records `source` (relative path) and `topic` (the top-level
    folder: exercise_science / nutrition / safety) for filtered retrieval.
    """
    raise NotImplementedError


def split_documents(docs: list[Document]) -> list[Document]:
    """Chunk documents with a recursive character splitter."""
    raise NotImplementedError


def ingest(root: Path, *, reset: bool = False) -> int:
    """Load, split, and upsert documents; returns the number of chunks written.

    Chunk IDs are deterministic (hash of source + chunk index) so re-ingestion is idempotent.
    """
    raise NotImplementedError
