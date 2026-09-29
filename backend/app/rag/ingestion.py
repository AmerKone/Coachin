"""Load, chunk, and upsert knowledge-base documents into Pinecone."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.config import get_settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}
MARKDOWN_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]


class VectorStoreLike(Protocol):
    def add_documents(self, documents: list[Document], *, ids: list[str]) -> Any: ...


class IndexLike(Protocol):
    def list(self, **kwargs: Any) -> Any: ...
    def delete(self, **kwargs: Any) -> Any: ...


@dataclass
class IngestResult:
    sources: int
    chunks: int
    deleted: int


def _topic(relative: Path) -> str:
    return relative.parts[0] if len(relative.parts) > 1 else "general"


def load_documents(root: Path) -> list[Document]:
    """Load every supported file under `root` (one Document per file, or per page for PDFs).

    Metadata: `source` (path relative to `root`, forward slashes) and `topic` (top-level
    folder: exercise_science / nutrition / safety) for filtered retrieval.
    """
    docs: list[Document] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES):
        relative = path.relative_to(root)
        if relative.name.lower() == "readme.md":
            continue
        meta = {"source": relative.as_posix(), "topic": _topic(relative)}
        if path.suffix.lower() == ".pdf":
            from langchain_community.document_loaders import PyPDFLoader

            for page in PyPDFLoader(str(path)).load():
                page.metadata = {**meta, "page": page.metadata.get("page", 0) + 1}
                docs.append(page)
        else:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                docs.append(Document(page_content=text, metadata=meta))
    return docs


def split_documents(docs: list[Document]) -> list[Document]:
    """Chunk documents, keeping Markdown sections together and recording the section title.

    Each chunk gets a deterministic `chunk_id` (`<source>#<n>`) so re-ingestion overwrites
    instead of duplicating.
    """
    header_splitter = MarkdownHeaderTextSplitter(MARKDOWN_HEADERS, strip_headers=False)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

    chunks: list[Document] = []
    counters: dict[str, int] = {}
    for doc in docs:
        if doc.metadata["source"].endswith(".md"):
            sections = header_splitter.split_text(doc.page_content)
        else:
            sections = [Document(page_content=doc.page_content)]
        for section in sections:
            headers = [section.metadata[key] for _, key in MARKDOWN_HEADERS if key in section.metadata]
            for piece in text_splitter.split_text(section.page_content):
                source = doc.metadata["source"]
                n = counters.get(source, 0)
                counters[source] = n + 1
                meta = {**doc.metadata, "chunk_id": f"{source}#{n:04d}"}
                if headers:
                    meta["title"] = headers[0]
                    meta["section"] = " > ".join(headers)
                chunks.append(Document(page_content=piece, metadata=meta))
    return chunks


def _existing_ids(index: IndexLike, namespace: str) -> set[str]:
    try:
        return {vector_id for page in index.list(namespace=namespace) for vector_id in page}
    except Exception as exc:  # namespace doesn't exist yet on first ingest
        logger.info("Could not list existing vectors (%s); assuming none.", exc)
        return set()


def ingest(
    root: Path,
    *,
    store: VectorStoreLike | None = None,
    index: IndexLike | None = None,
) -> IngestResult:
    """Sync the knowledge base into Pinecone.

    Upserts every chunk under its deterministic ID, then deletes vectors whose IDs no longer
    exist (removed files or sections), so the index mirrors `root` exactly.

    `store` / `index` default to the configured Pinecone index; tests pass fakes.
    """
    namespace = get_settings().pinecone_namespace
    if store is None or index is None:
        from app.rag.vector_store import ensure_index, get_pinecone, get_vector_store

        ensure_index()
        store = store or get_vector_store()
        index = index or get_pinecone().Index(get_settings().pinecone_index_name)

    chunks = split_documents(load_documents(root))
    ids = [chunk.metadata["chunk_id"] for chunk in chunks]
    stale = _existing_ids(index, namespace) - set(ids)

    if chunks:
        store.add_documents(chunks, ids=ids)
    if stale:
        index.delete(ids=sorted(stale), namespace=namespace)

    return IngestResult(
        sources=len({c.metadata["source"] for c in chunks}), chunks=len(chunks), deleted=len(stale)
    )
