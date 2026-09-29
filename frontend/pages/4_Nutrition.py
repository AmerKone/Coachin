"""Nutrition logging.

Describe a meal (text or voice) to get LLM macro estimates, review/edit, and save. Shows
today's totals against targets and the day's entries.
"""

import streamlit as st  # noqa: F401

from components.auth import require_login  # noqa: F401
from components.charts import macro_vs_target_chart  # noqa: F401
from components.voice import record_audio  # noqa: F401


def main() -> None:
    raise NotImplementedError


main()
