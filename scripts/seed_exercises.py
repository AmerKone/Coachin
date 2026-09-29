"""Seed or update the `exercises` table from a JSON exercise library.

Usage: python scripts/seed_exercises.py [path/to/exercises.json]

Defaults to backend/data/exercises.json. Safe to re-run: existing exercises are matched
by name and only updated when their data changed.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from pydantic import ValidationError  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.services.exercise_service import (  # noqa: E402
    DEFAULT_EXERCISE_FILE,
    read_exercise_file,
    upsert_exercises,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the exercise library.")
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_EXERCISE_FILE)
    args = parser.parse_args()

    try:
        exercises = read_exercise_file(args.path)
    except FileNotFoundError:
        print(f"File not found: {args.path}", file=sys.stderr)
        return 1
    except ValidationError as exc:
        print(f"Invalid exercise data in {args.path}:\n{exc}", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        try:
            result = upsert_exercises(db, exercises)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1

    print(
        f"{len(exercises)} exercises in {args.path.name}: "
        f"{result.inserted} inserted, {result.updated} updated, {result.unchanged} unchanged."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
