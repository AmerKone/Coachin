"""Pinecone index and LangChain vector store construction."""

from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone

from app.config import get_settings  # noqa: F401


@lru_cache
def get_embeddings() -> OpenAIEmbeddings:
    """Embedding model configured from `OPENAI_EMBEDDING_MODEL`."""
    raise NotImplementedError


def ensure_index(client: Pinecone) -> None:
    """Create the serverless index (cosine, `EMBEDDING_DIMENSIONS`) if it does not exist."""
    raise NotImplementedError


@lru_cache
def get_vector_store() -> PineconeVectorStore:
    """Return a LangChain vector store bound to the configured index and namespace."""
    raise NotImplementedError
