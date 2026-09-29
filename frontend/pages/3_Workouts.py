"""Workout logging and exercise progress.

Pre-fills today's planned workout with progressive-overload targets; the user edits
reps/weight/RPE per set and saves. Below: per-exercise progress charts.
"""

import streamlit as st  # noqa: F401

from components.auth import require_login  # noqa: F401
from components.charts import exercise_progress_chart  # noqa: F401


def main() -> None:
    raise NotImplementedError


main()
