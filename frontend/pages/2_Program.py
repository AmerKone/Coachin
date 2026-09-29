"""Weekly training program view and generation.

Shows a program by week (tabs) with each day's exercises and targets; offers a form to
generate a new program and buttons to start or delete programs.
"""

from datetime import date
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from client.api_client import ApiError, CoachinClient
from components.auth import handle_api_error, require_login
from components.safety import render_disclaimer

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
GOALS = {
    "general_fitness": "General fitness",
    "fat_loss": "Fat loss",
    "muscle_gain": "Muscle gain",
    "strength": "Strength",
    "endurance": "Endurance",
}
STATUS_LABELS = {"active": "🟢 Active", "draft": "📝 Draft", "completed": "✅ Completed", "archived": "🗄️ Archived"}
API_ERRORS = (ApiError, httpx.TransportError)


def current_week(program: dict[str, Any]) -> int:
    days_in = (date.today() - date.fromisoformat(program["start_date"])).days
    return min(max(days_in // 7 + 1, 1), program["duration_weeks"])


def exercise_table(workout: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for planned in workout["exercises"]:
        lo, hi = planned["target_reps_min"], planned["target_reps_max"]
        rows.append({
            "Exercise": planned["exercise"]["name"],
            "Sets": planned["target_sets"],
            "Reps": str(lo) if lo == hi else f"{lo}-{hi}",
            "RPE": f"{planned['target_rpe']:g}" if planned["target_rpe"] is not None else "—",
            "Rest": f"{planned['rest_seconds']} s" if planned["rest_seconds"] is not None else "—",
            "Notes": planned["notes"] or "",
        })
    return pd.DataFrame(rows)


def render_program(program: dict[str, Any]) -> None:
    week_now = current_week(program)
    st.subheader(program["name"])
    st.caption(
        f"{STATUS_LABELS.get(program['status'], program['status'])} · "
        f"{GOALS.get(program['goal'], program['goal'])} · {program['duration_weeks']} weeks · "
        f"starts {program['start_date']}"
        + (f" · you're in week {week_now}" if program["status"] == "active" else "")
    )
    if program.get("notes"):
        with st.expander("Why this plan", expanded=program["status"] == "draft"):
            st.write(program["notes"])

    weeks = sorted({w["week_number"] for w in program["workouts"]})
    labels = [
        f"Week {n}" + (" (deload)" if program["duration_weeks"] >= 4 and n == program["duration_weeks"] else "")
        for n in weeks
    ]
    for week_number, tab in zip(weeks, st.tabs(labels)):
        with tab:
            if program["status"] == "active" and week_number == week_now:
                st.caption("This week")
            for workout in (w for w in program["workouts"] if w["week_number"] == week_number):
                title = f"**{DAY_NAMES[workout['day_of_week']]} — {workout['name']}**"
                st.markdown(title + (f"  \n_{workout['focus']}_" if workout.get("focus") else ""))
                st.dataframe(exercise_table(workout), hide_index=True, width="stretch")


def render_actions(client: CoachinClient, program: dict[str, Any]) -> None:
    c1, c2 = st.columns([1, 1])
    if program["status"] != "active":
        if c1.button("Start this program", type="primary", key=f"start_{program['id']}"):
            try:
                client.update_program(program["id"], {"status": "active"})
            except API_ERRORS as exc:
                handle_api_error(exc)
            else:
                st.session_state["program_message"] = "Program started. Good luck!"
                st.session_state["selected_program"] = program["id"]
                st.rerun()

    with c2.popover("Delete program"):
        st.write("This permanently deletes the program. Logged workouts are kept.")
        if st.button("Yes, delete it", key=f"delete_{program['id']}"):
            try:
                client.delete_program(program["id"])
            except API_ERRORS as exc:
                handle_api_error(exc)
            else:
                st.session_state.pop("selected_program", None)
                st.session_state["program_message"] = "Program deleted."
                st.rerun()


def render_generate_form(client: CoachinClient, profile: dict[str, Any], expanded: bool) -> None:
    with st.expander("Generate a new program", expanded=expanded), st.form("generate"):
        goal_keys = list(GOALS)
        c1, c2 = st.columns(2)
        goal = c1.selectbox("Goal", goal_keys, index=goal_keys.index(profile["primary_goal"]),
                            format_func=GOALS.get)
        days = c2.slider("Training days per week", 1, 7, profile["training_days_per_week"])
        weeks = c1.slider("Program length (weeks)", 1, 16, 4,
                          help="Programs of 4+ weeks end with a lighter deload week.")
        start = c2.date_input("Start date", value=date.today(), min_value=date.today())
        extra = st.text_area("Anything else your coach should know? (optional)",
                             placeholder="e.g. more core work, no overhead pressing, short sessions on Fridays",
                             max_chars=1000)
        st.caption("Uses your profile's equipment, injuries and session length. Update them on the Profile page.")
        if not st.form_submit_button("Generate program", type="primary"):
            return

    with st.spinner("Your coach is designing your program… this can take up to a minute."):
        try:
            program = client.generate_program({
                "goal": goal, "training_days_per_week": days, "duration_weeks": weeks,
                "start_date": start.isoformat(), "extra_instructions": extra.strip() or None,
            })
        except API_ERRORS as exc:
            handle_api_error(exc)
            return
    st.session_state["selected_program"] = program["id"]
    st.session_state["program_message"] = "Your new program is ready. Review it and press **Start this program**."
    st.rerun()


def main() -> None:
    client = require_login()
    st.title("Program")
    if message := st.session_state.pop("program_message", None):
        st.success(message)

    try:
        profile = client.get_profile()
        programs = client.list_programs() if profile else []
    except API_ERRORS as exc:
        handle_api_error(exc)
        return

    if profile is None:
        st.info("Complete your profile first so your coach can personalize your program.")
        st.page_link("pages/6_Profile.py", label="Complete your profile", icon="📝")
        return

    render_generate_form(client, profile, expanded=not programs)
    if not programs:
        st.info("You don't have a program yet. Generate one above.")
        render_disclaimer()
        return

    # Active first, then drafts, then the rest (API returns newest first within each).
    order = {"active": 0, "draft": 1, "completed": 2, "archived": 3}
    programs.sort(key=lambda p: order.get(p["status"], 9))
    ids = [p["id"] for p in programs]
    by_id = {p["id"]: p for p in programs}
    selected = st.session_state.get("selected_program")
    selected_id = st.selectbox(
        "Program", ids, index=ids.index(selected) if selected in ids else 0,
        format_func=lambda pid: f"{by_id[pid]['name']} — {STATUS_LABELS.get(by_id[pid]['status'], '')} "
                                f"({by_id[pid]['created_at'][:10]})",
    )
    st.session_state["selected_program"] = selected_id

    try:
        program = client.get_program(selected_id)
    except API_ERRORS as exc:
        handle_api_error(exc)
        return
    render_actions(client, program)
    render_program(program)
    render_disclaimer()


main()
