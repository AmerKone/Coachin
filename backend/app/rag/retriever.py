"""Query-time retrieval of knowledge-base chunks."""

from typing import Literal

from langchain_core.documents import Document

Topic = Literal["exercise_science", "nutrition", "safety"]


class KnowledgeRetriever:
    """Similarity search over the Pinecone knowledge base."""

    def __init__(self, k: int = 4, score_threshold: float = 0.3) -> None:
        self.k = k
        self.score_threshold = score_threshold

    def retrieve(self, query: str, topics: list[Topic] | None = None) -> list[Document]:
        """Return the top-`k` chunks above `score_threshold`, optionally filtered by topic."""
        raise NotImplementedError

    @staticmethod
    def format_context(docs: list[Document]) -> str:
        """Render retrieved chunks as a numbered, source-attributed block for prompts."""
        raise NotImplementedError
