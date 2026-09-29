# knowledge_base

Source documents the coach retrieves from (RAG). Run `python scripts/ingest_knowledge.py`
after adding or changing files.

| Folder | Topic tag | Examples |
|--------|-----------|----------|
| `exercise_science/` | `exercise_science` | Programming principles, progressive overload, rep ranges, exercise technique, deloads |
| `nutrition/` | `nutrition` | Macro guidelines, protein needs, food composition tables, meal timing |
| `safety/` | `safety` | Red-flag symptoms, when to refer to a professional, PAR-Q style screening, contraindications |

Guidelines:

- Supported formats: `.md`, `.txt`, `.pdf`.
- Prefer reputable, citable sources, and include the source/citation at the top of each file.
- Only add content you have the right to use.
- The folder name becomes the chunk's `topic` metadata, which is used for filtered retrieval.
