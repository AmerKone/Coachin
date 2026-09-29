"""Seed the `exercises` table from a JSON/CSV exercise library.

Usage: python scripts/seed_exercises.py path/to/exercises.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import SessionLocal  # noqa: E402, F401
from app.models import Exercise  # noqa: E402, F401
from app.schemas import ExerciseCreate  # noqa: E402, F401


def main(path: Path) -> None:
    """Validate each record with `ExerciseCreate` and upsert by name."""
    raise NotImplementedError


if __name__ == "__main__":
    main(Path(sys.argv[1]))
