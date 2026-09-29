"""The viewer's local timezone (from the browser), so "today" matches their calendar."""

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st


def local_tz_name() -> str:
    try:
        name = st.context.timezone
    except AttributeError:
        name = None
    if not name:
        return "UTC"
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"
    return name


def local_now() -> datetime:
    return datetime.now(ZoneInfo(local_tz_name()))


def local_today() -> date:
    return local_now().date()
