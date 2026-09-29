"""Tests for knowledge-base ingestion and retrieval (no Pinecone or OpenAI calls)."""

from pathlib import Path

from langchain_core.documents import Document

from app.rag.ingestion import ingest, load_documents, split_documents
from app.rag.retriever import KnowledgeRetriever

KB_ROOT = Path(__file__).resolve().parents[2] / "knowledge_base"


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FakeStore:
    def __init__(self) -> None:
        self.added: dict[str, Document] = {}

    def add_documents(self, documents, *, ids):
        self.added.update(zip(ids, documents))


class FakeIndex:
    def __init__(self, existing: set[str]) -> None:
        self.existing = set(existing)
        self.deleted: list[str] = []

    def list(self, namespace):
        yield sorted(self.existing)

    def delete(self, ids, namespace):
        self.deleted += ids


def test_load_documents_sets_topic_and_skips_readme(tmp_path: Path) -> None:
    write(tmp_path, "README.md", "# Index\nignore me")
    write(tmp_path, "nutrition/protein.md", "# Protein\nEat enough.")
    write(tmp_path, "safety/notes.txt", "Stop if it hurts.")
    write(tmp_path, "nutrition/empty.md", "   ")
    write(tmp_path, "nutrition/image.png", "not text")

    docs = load_documents(tmp_path)
    assert [(d.metadata["source"], d.metadata["topic"]) for d in docs] == [
        ("nutrition/protein.md", "nutrition"),
        ("safety/notes.txt", "safety"),
    ]


def test_split_documents_keeps_sections_and_numbers_chunks(tmp_path: Path) -> None:
    long_section = "Squat deep with control. " * 80  # ~2000 chars -> several chunks
    write(tmp_path, "exercise_science/guide.md", f"# Guide\n## Squats\n{long_section}\n## Rest\nRest 2 minutes.")
    chunks = split_documents(load_documents(tmp_path))

    ids = [c.metadata["chunk_id"] for c in chunks]
    assert ids == [f"exercise_science/guide.md#{i:04d}" for i in range(len(chunks))]
    assert len(chunks) >= 3
    assert all(len(c.page_content) <= 1000 for c in chunks)
    assert chunks[0].metadata["section"] == "Guide > Squats"
    assert chunks[-1].metadata["section"] == "Guide > Rest"
    assert "Rest 2 minutes." in chunks[-1].page_content


def test_ingest_upserts_and_removes_stale_chunks(tmp_path: Path) -> None:
    write(tmp_path, "nutrition/protein.md", "# Protein\nEat 1.6 g/kg.")
    store, index = FakeStore(), FakeIndex({"nutrition/protein.md#0000", "nutrition/old_file.md#0000"})

    result = ingest(tmp_path, store=store, index=index)

    assert list(store.added) == ["nutrition/protein.md#0000"]
    assert index.deleted == ["nutrition/old_file.md#0000"]
    assert (result.sources, result.chunks, result.deleted) == (1, 1, 1)


def test_real_knowledge_base_splits_cleanly() -> None:
    chunks = split_documents(load_documents(KB_ROOT))
    topics = {c.metadata["topic"] for c in chunks}
    assert topics == {"exercise_science", "nutrition", "safety"}
    ids = [c.metadata["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(c.metadata.get("section") for c in chunks)


def test_retriever_filters_by_score_and_topic() -> None:
    class Store:
        def similarity_search_with_score(self, query, k=4, filter=None):
            self.args = (query, k, filter)
            return [
                (Document(page_content="relevant", metadata={"section": "A > B", "chunk_id": "a#0"}), 0.8),
                (Document(page_content="weak", metadata={"source": "b.md"}), 0.1),
            ]

    store = Store()
    retriever = KnowledgeRetriever(k=3, store=store)
    docs = retriever.retrieve("protein needs", topics=["nutrition"])

    assert [d.page_content for d in docs] == ["relevant"]
    assert store.args == ("protein needs", 3, {"topic": {"$in": ["nutrition"]}})
    assert KnowledgeRetriever.format_context(docs) == "[1] (A > B)\nrelevant"
    assert KnowledgeRetriever.source_ids(docs) == ["a#0"]


def test_retriever_returns_nothing_when_store_fails() -> None:
    class Broken:
        def similarity_search_with_score(self, *args, **kwargs):
            raise TimeoutError("Pinecone timeout")

    assert KnowledgeRetriever(store=Broken()).retrieve("anything") == []
    assert KnowledgeRetriever.format_context([]) == ""
