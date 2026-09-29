"""Nutrition logging.

Describe a meal to get an item-by-item estimate, review/adjust it, and save. Shows the
day's totals against targets and the day's entries. Target suggestions come from the
profile and can be saved to it.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import streamlit as st

from client.api_client import ApiError, CoachinClient
from components.auth import handle_api_error, require_login
from components.local_time import local_now, local_today, local_tz_name
from components.safety import render_disclaimer

MEAL_TYPES = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"}
MACROS = [("calories", "Calories", "kcal"), ("protein_g", "Protein", "g"), ("carbs_g", "Carbs", "g"),
          ("fat_g", "Fat", "g")]
API_ERRORS = (ApiError, httpx.TransportError)


def render_totals(summary: dict[str, Any]) -> None:
    """One tile per macro: eaten vs target with a progress bar (units differ, so no shared chart)."""
    targets = summary["targets"] or {}
    for column, (key, label, unit) in zip(st.columns(4), MACROS):
        eaten, target = summary["totals"][key], targets.get(key) or 0
        with column:
            if target:
                left = target - eaten
                st.metric(label, f"{eaten:,.0f} {unit}",
                          f"{abs(left):,.0f} {unit} {'left' if left >= 0 else 'over'}",
                          delta_color="off")
                st.progress(min(eaten / target, 1.0), text=f"of {target:,.0f} {unit}")
            else:
                st.metric(label, f"{eaten:,.0f} {unit}")
                st.caption("No target set")


def render_targets_help(client: CoachinClient, summary: dict[str, Any]) -> None:
    try:
        targets = client.nutrition_targets()
    except API_ERRORS as exc:
        handle_api_error(exc)
        return
    with st.expander("About your targets", expanded=summary["targets"] is None):
        st.write(targets["explanation"])
        suggested = targets["suggested"]
        if suggested:
            st.caption("Suggested: " + " · ".join(f"{label} {suggested[key]:,.0f} {unit}" for key, label, unit in MACROS))
            if st.button("Save suggested targets to my profile"):
                try:
                    client.update_profile({
                        "daily_calorie_target": int(suggested["calories"]),
                        "daily_protein_target_g": int(suggested["protein_g"]),
                        "daily_carbs_target_g": int(suggested["carbs_g"]),
                        "daily_fat_target_g": int(suggested["fat_g"]),
                    })
                except API_ERRORS as exc:
                    handle_api_error(exc)
                else:
                    st.session_state["nutrition_message"] = "Targets saved to your profile."
                    st.rerun()
        elif targets["missing_profile_fields"]:
            st.page_link("pages/6_Profile.py", label="Update your profile", icon="📝")


def render_estimate_form(client: CoachinClient, day) -> None:
    st.subheader("Log a meal")
    with st.form("describe_meal", clear_on_submit=False):
        description = st.text_area(
            "What did you eat?",
            placeholder="e.g. Two eggs scrambled in butter, a slice of whole-wheat toast and a banana",
            max_chars=2000,
        )
        c1, c2 = st.columns(2)
        meal_type = c1.selectbox("Meal", [None, *MEAL_TYPES], format_func=lambda m: "Detect automatically"
                                 if m is None else MEAL_TYPES[m])
        eaten_time = c2.time_input("Time", value=local_now().time().replace(second=0, microsecond=0))
        submitted = st.form_submit_button("Estimate", type="primary")

    if submitted:
        if not description.strip():
            st.error("Describe what you ate first.")
            return
        eaten_at = datetime.combine(day, eaten_time, tzinfo=ZoneInfo(local_tz_name()))
        with st.spinner("Estimating…"):
            try:
                estimate = client.estimate_meal(description.strip(), meal_type, eaten_at.isoformat())
            except API_ERRORS as exc:
                handle_api_error(exc)
                return
        st.session_state["meal_estimate"] = {**estimate, "eaten_at": eaten_at.isoformat()}

    estimate = st.session_state.get("meal_estimate")
    if estimate:
        render_estimate_review(client, estimate)


def render_estimate_review(client: CoachinClient, estimate: dict[str, Any]) -> None:
    st.markdown("**Estimate** (adjust anything that looks off before saving)")
    items = pd.DataFrame(estimate["items"]).rename(columns={
        "food": "Food", "portion": "Portion", "calories": "kcal", "protein_g": "Protein (g)",
        "carbs_g": "Carbs (g)", "fat_g": "Fat (g)"})
    st.dataframe(items, hide_index=True, width="stretch")
    if estimate["assumptions"]:
        st.caption(f"Assumptions: {estimate['assumptions']}")

    totals = estimate["totals"]
    with st.form("save_meal"):
        cols = st.columns(4)
        values = {key: col.number_input(f"{label} ({unit})", min_value=0.0, max_value=10000.0,
                                        value=float(totals[key]), step=1.0)
                  for col, (key, label, unit) in zip(cols, MACROS)}
        meal_type = st.selectbox("Meal", list(MEAL_TYPES), index=list(MEAL_TYPES).index(estimate["meal_type"]),
                                 format_func=MEAL_TYPES.get)
        c1, c2 = st.columns([1, 1])
        save = c1.form_submit_button("Save meal", type="primary")
        discard = c2.form_submit_button("Discard")

    if discard:
        st.session_state.pop("meal_estimate", None)
        st.rerun()
    if save:
        try:
            client.log_meal({
                "eaten_at": estimate["eaten_at"], "meal_type": meal_type, "description": estimate["description"],
                **values, "is_estimated": True, "source": "manual",  # still an estimate even if adjusted
            })
        except API_ERRORS as exc:
            handle_api_error(exc)
            return
        st.session_state.pop("meal_estimate", None)
        st.session_state["nutrition_message"] = "Meal saved."
        st.rerun()


def render_entries(client: CoachinClient, summary: dict[str, Any]) -> None:
    st.subheader("Meals")
    if not summary["entries"]:
        st.caption("Nothing logged for this day yet.")
        return
    tz = ZoneInfo(summary["timezone"])
    for entry in summary["entries"]:
        eaten = datetime.fromisoformat(entry["eaten_at"]).astimezone(tz)
        c1, c2 = st.columns([6, 1])
        c1.markdown(
            f"**{MEAL_TYPES[entry['meal_type']]}** · {eaten:%H:%M} — {entry['description']}  \n"
            f"{entry['calories']:,.0f} kcal · P {entry['protein_g']:g} g · C {entry['carbs_g']:g} g · "
            f"F {entry['fat_g']:g} g" + (" · _estimated_" if entry["is_estimated"] else "")
        )
        if c2.button("Delete", key=f"del_{entry['id']}"):
            try:
                client.delete_meal(entry["id"])
            except API_ERRORS as exc:
                handle_api_error(exc)
            else:
                st.session_state["nutrition_message"] = "Meal deleted."
                st.rerun()


def main() -> None:
    client = require_login()
    st.title("Nutrition")
    if message := st.session_state.pop("nutrition_message", None):
        st.success(message)

    day = st.date_input("Day", value=local_today(), max_value=local_today(), format="YYYY-MM-DD")
    try:
        summary = client.daily_nutrition(day, local_tz_name())
    except API_ERRORS as exc:
        handle_api_error(exc)
        return

    render_totals(summary)
    render_targets_help(client, summary)
    st.divider()
    render_estimate_form(client, day)
    st.divider()
    render_entries(client, summary)
    render_disclaimer()


main()
