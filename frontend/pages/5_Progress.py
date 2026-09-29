"""Body metrics and monthly progress reports.

Record weight/measurements, view trend charts, and generate or read monthly reports.
"""

import streamlit as st  # noqa: F401

from components.auth import require_login  # noqa: F401
from components.charts import body_weight_trend_chart  # noqa: F401


def main() -> None:
    require_login()
    st.title("Progress")
    st.info("Body metrics and monthly progress reports are coming soon.")


main()
