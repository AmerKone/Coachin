"""Create all database tables from the ORM models (development convenience).

Usage: python scripts/init_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import engine  # noqa: E402
from app.models import Base  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print(f"Created {len(Base.metadata.tables)} tables.")


if __name__ == "__main__":
    main()
