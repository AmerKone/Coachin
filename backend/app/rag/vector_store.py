"""Pinecone index and LangChain vector store construction."""

from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec

from app.config import get_settings


@lru_cache
def get_embeddings() -> OpenAIEmbeddings:
    """Embedding model configured from `OPENAI_EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS`."""
    settings = get_settings()
    return OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        dimensions=settings.embedding_dimensions,
        api_key=settings.openai_api_key,
    )


@lru_cache
def get_pinecone() -> Pinecone:
    return Pinecone(api_key=get_settings().pinecone_api_key)


def ensure_index(client: Pinecone | None = None) -> None:
    """Create the serverless index (cosine, `EMBEDDING_DIMENSIONS`) if it does not exist.

    Raises:
        ValueError: the index exists with a different dimension than the embedding model.
    """
    settings = get_settings()
    client = client or get_pinecone()
    if not client.has_index(settings.pinecone_index_name):
        client.create_index(
            name=settings.pinecone_index_name,
            dimension=settings.embedding_dimensions,
            metric="cosine",
            spec=ServerlessSpec(cloud=settings.pinecone_cloud, region=settings.pinecone_region),
        )
        return
    dimension = client.describe_index(settings.pinecone_index_name).dimension
    if dimension != settings.embedding_dimensions:
        raise ValueError(
            f"Pinecone index {settings.pinecone_index_name!r} has dimension {dimension}, but "
            f"EMBEDDING_DIMENSIONS is {settings.embedding_dimensions}. Use a new index name or "
            "delete the old index."
        )


@lru_cache
def get_vector_store() -> PineconeVectorStore:
    """Return a LangChain vector store bound to the configured index and namespace."""
    settings = get_settings()
    return PineconeVectorStore(
        index=get_pinecone().Index(settings.pinecone_index_name),
        embedding=get_embeddings(),
        namespace=settings.pinecone_namespace,
    )
