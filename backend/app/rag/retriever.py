"""Query-time retrieval of knowledge-base chunks."""

import logging
from typing import Any, Literal, Protocol

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

Topic = Literal["exercise_science", "nutrition", "safety"]


class ScoredSearch(Protocol):
    def similarity_search_with_score(
        self, query: str, k: int = 4, filter: dict[str, Any] | None = None
    ) -> list[tuple[Document, float]]: ...


class KnowledgeRetriever:
    """Similarity search over the Pinecone knowledge base.

    Retrieval is best-effort: if Pinecone or the embedding API is unavailable, `retrieve`
    logs a warning and returns no documents so callers can fall back to built-in guidance.
    """

    # text-embedding-3-small cosine scores for clearly relevant chunks were ~0.33-0.75 on the
    # Coachin knowledge base; 0.25 keeps borderline-but-relevant safety passages.
    def __init__(self, k: int = 4, score_threshold: float = 0.25, store: ScoredSearch | None = None) -> None:
        self.k = k
        self.score_threshold = score_threshold
        self._store = store

    @property
    def store(self) -> ScoredSearch:
        if self._store is None:
            from app.rag.vector_store import get_vector_store

            self._store = get_vector_store()
        return self._store

    def retrieve(self, query: str, topics: list[Topic] | None = None) -> list[Document]:
        """Return the top-`k` chunks with cosine score >= `score_threshold`, optionally
        restricted to `topics`, best match first."""
        search_filter = {"topic": {"$in": list(topics)}} if topics else None
        try:
            results = self.store.similarity_search_with_score(query, k=self.k, filter=search_filter)
        except Exception as exc:
            logger.warning("Knowledge retrieval failed; continuing without it: %s", exc)
            return []
        return [doc for doc, score in results if score >= self.score_threshold]

    @staticmethod
    def format_context(docs: list[Document]) -> str:
        """Render retrieved chunks as a numbered, source-attributed block for prompts."""
        if not docs:
            return ""
        blocks = []
        for i, doc in enumerate(docs, start=1):
            label = doc.metadata.get("section") or doc.metadata.get("source", "unknown")
            blocks.append(f"[{i}] ({label})\n{doc.page_content.strip()}")
        return "\n\n".join(blocks)

    @staticmethod
    def source_ids(docs: list[Document]) -> list[str]:
        return [doc.metadata.get("chunk_id", doc.metadata.get("source", "")) for doc in docs]
