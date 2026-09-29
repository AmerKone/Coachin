"""Exercise library: loading from JSON, bulk upsert, and search."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models import Exercise
from app.models.enums import Equipment, ExerciseCategory, MuscleGroup
from app.schemas import ExerciseCreate

DEFAULT_EXERCISE_FILE = Path(__file__).resolve().parents[2] / "data" / "exercises.json"

_exercise_list = TypeAdapter(list[ExerciseCreate])


@dataclass
class UpsertResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


def read_exercise_file(path: Path = DEFAULT_EXERCISE_FILE) -> list[ExerciseCreate]:
    """Parse and validate a JSON array of exercises."""
    return _exercise_list.validate_json(path.read_bytes())


def upsert_exercises(db: Session, items: Iterable[ExerciseCreate]) -> UpsertResult:
    """Insert new exercises and update changed ones, matching by case-insensitive name.

    Idempotent: re-running with the same data reports everything as unchanged.
    Exercises in the database but not in `items` are left alone (they may be referenced
    by programs and logged sets).

    Raises:
        ValueError: `items` contains the same name twice.
    """
    existing = {exercise.name.lower(): exercise for exercise in db.scalars(select(Exercise))}
    seen: set[str] = set()
    result = UpsertResult()

    for item in items:
        key = item.name.lower()
        if key in seen:
            raise ValueError(f"Duplicate exercise name: {item.name!r}")
        seen.add(key)

        data = item.model_dump()
        current = existing.get(key)
        if current is None:
            db.add(Exercise(**data))
            result.inserted += 1
            continue

        changes = {field: value for field, value in data.items() if getattr(current, field) != value}
        for field, value in changes.items():
            setattr(current, field, value)
        if changes:
            result.updated += 1
        else:
            result.unchanged += 1

    db.commit()
    return result


def search_exercises(
    db: Session,
    *,
    q: str | None = None,
    muscle: MuscleGroup | None = None,
    category: ExerciseCategory | None = None,
    equipment: Sequence[Equipment] | None = None,
    no_equipment: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Exercise], int]:
    """Filter the library; returns (page of exercises ordered by name, total matches).

    `equipment` is what the user *has*: only exercises whose required equipment is a
    subset of it are returned. `no_equipment` restricts to exercises needing nothing.
    """
    stmt = select(Exercise)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Exercise.name.ilike(f"%{escaped}%", escape="\\"))
    if muscle is not None:
        stmt = stmt.where(Exercise.primary_muscle == muscle)
    if category is not None:
        stmt = stmt.where(Exercise.category == category)
    if no_equipment:
        stmt = stmt.where(func.jsonb_array_length(cast(Exercise.equipment, JSONB)) == 0)
    elif equipment is not None:
        stmt = stmt.where(cast(Exercise.equipment, JSONB).contained_by([str(e) for e in equipment]))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Exercise.name).limit(limit).offset(offset)).all()
    return list(items), total


def find_exercise(db: Session, name: str) -> tuple[Exercise | None, list[str]]:
    """Resolve a spoken/typed exercise name: exact (case-insensitive) match first, then a
    unique match containing every word. Returns (exercise, []) or (None, candidate names)."""
    cleaned = " ".join(name.split())
    exact = db.scalar(select(Exercise).where(func.lower(Exercise.name) == cleaned.lower()))
    if exact is not None:
        return exact, []
    stmt = select(Exercise)
    for word in cleaned.split():
        escaped = word.replace("\\", "\\\\").replace("%", "\%").replace("_", "\_")
        stmt = stmt.where(Exercise.name.ilike(f"%{escaped}%", escape="\\"))
    matches = list(db.scalars(stmt.order_by(func.length(Exercise.name)).limit(6)))
    if len(matches) == 1:
        return matches[0], []
    return None, [m.name for m in matches]
