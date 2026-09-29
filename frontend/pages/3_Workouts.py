"""Workout logging and exercise progress.

Log tab: the next planned workout pre-filled with progressive-overload targets; the user
ticks each set they completed, adjusting reps/weight/RPE to what they actually did.
History tab: recent sessions and a per-exercise progress chart.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from client.api_client import ApiError, CoachinClient
from components.auth import handle_api_error, require_login
from components.charts import exercise_progress_chart

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
API_ERRORS = (ApiError, httpx.TransportError)


def workout_label(workout: dict[str, Any]) -> str:
    return f"Week {workout['week_number']} · {DAY_NAMES[workout['day_of_week']]} — {workout['name']}"


def target_caption(rec: dict[str, Any]) -> str:
    lo, hi = rec["recommended_reps_min"], rec["recommended_reps_max"]
    reps = str(lo) if lo == hi else f"{lo}-{hi}"
    parts = [f"{rec['target_sets']} × {reps}"]
    if rec["recommended_weight_kg"]:
        parts.append(f"@ {rec['recommended_weight_kg']:g} kg")
    if rec["target_rpe"]:
        parts.append(f"RPE {rec['target_rpe']:g}")
    if rec["rest_seconds"]:
        parts.append(f"rest {rec['rest_seconds']} s")
    return " · ".join(parts)


def set_editor(rec: dict[str, Any]) -> pd.DataFrame:
    rows = [{"Set": i, "Done": False, "Reps": rec["recommended_reps_min"],
             "Weight (kg)": rec["recommended_weight_kg"], "RPE": None}
            for i in range(1, rec["target_sets"] + 1)]
    return st.data_editor(
        pd.DataFrame(rows),
        key=f"sets_{rec['planned_exercise_id']}",
        hide_index=True,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "Set": st.column_config.NumberColumn(disabled=True, width="small"),
            "Done": st.column_config.CheckboxColumn(help="Tick each set you completed"),
            "Reps": st.column_config.NumberColumn(min_value=0, max_value=500, step=1),
            "Weight (kg)": st.column_config.NumberColumn(min_value=0.0, max_value=1000.0, step=0.5,
                                                         help="Leave empty for bodyweight"),
            "RPE": st.column_config.NumberColumn(min_value=1.0, max_value=10.0, step=0.5,
                                                 help="How hard was it? 10 = no reps left"),
        },
    )


def collect_sets(targets: dict[str, Any], tables: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Turn the ticked rows of every exercise table into API set payloads."""
    sets = []
    for rec in targets["exercises"]:
        table = tables[rec["planned_exercise_id"]]
        done = table[(table["Done"] == True) & (table["Reps"].fillna(0) > 0)]  # noqa: E712
        for number, (_, row) in enumerate(done.iterrows(), start=1):
            sets.append({
                "exercise_id": rec["exercise"]["id"],
                "set_number": number,
                "reps": int(row["Reps"]),
                "weight_kg": float(row["Weight (kg)"]) if pd.notna(row["Weight (kg)"]) and row["Weight (kg)"] > 0 else None,
                "rpe": float(row["RPE"]) if pd.notna(row["RPE"]) else None,
            })
    return sets


def render_log_tab(client: CoachinClient) -> None:
    try:
        program = client.get_active_program()
    except API_ERRORS as exc:
        handle_api_error(exc)
        return
    if program is None:
        st.info("Start a program first; your workouts and targets come from it.")
        st.page_link("pages/2_Program.py", label="Go to Program", icon="🗓️")
        return

    try:
        next_up = client.next_targets()
    except API_ERRORS as exc:
        handle_api_error(exc)
        return

    workouts = sorted(program["workouts"], key=lambda w: (w["week_number"], w["day_of_week"]))
    ids = [w["id"] for w in workouts]
    default = next_up["program_workout_id"] if next_up else ids[-1]
    chosen = st.selectbox("Workout", ids, index=ids.index(default),
                          format_func=lambda wid: workout_label(next(w for w in workouts if w["id"] == wid))
                          + ("  (next up)" if next_up and wid == next_up["program_workout_id"] else ""))
    if next_up is None:
        st.info("You've logged every workout in this program. Generate a new one on the Program page when you're ready.")

    try:
        targets = next_up if next_up and chosen == next_up["program_workout_id"] else client.next_targets(chosen)
    except API_ERRORS as exc:
        handle_api_error(exc)
        return
    if targets is None:
        st.error("Couldn't load that workout.")
        return
    if targets["already_logged"]:
        st.warning("You've already logged this workout. Saving again records another session.")

    st.caption("Tick **Done** for each set you complete and adjust reps, weight and RPE to what you actually did.")
    with st.form(f"log_{chosen}"):
        tables = {}
        for rec in targets["exercises"]:
            st.markdown(f"#### {rec['exercise']['name']}")
            st.caption(target_caption(rec))
            st.markdown(f"💡 {rec['rationale']}")
            if rec["notes"]:
                st.markdown(f"📝 _{rec['notes']}_")
            tables[rec["planned_exercise_id"]] = set_editor(rec)

        st.divider()
        c1, c2 = st.columns(2)
        duration = c1.number_input("Session length (minutes)", min_value=5, max_value=300, value=60, step=5)
        session_rpe = c2.slider("How hard was the whole session?", 1, 10, 7)
        notes = st.text_area("Notes (optional)", placeholder="How did it feel? Any pain or discomfort?")
        submitted = st.form_submit_button("Save workout", type="primary")

    if not submitted:
        return
    sets = collect_sets(targets, tables)
    if not sets:
        st.error("Tick **Done** on at least one set before saving.")
        return
    completed = datetime.now(UTC)
    try:
        client.log_workout({
            "program_workout_id": chosen,
            "started_at": (completed - timedelta(minutes=int(duration))).isoformat(),
            "completed_at": completed.isoformat(),
            "session_rpe": session_rpe,
            "notes": notes.strip() or None,
            "source": "manual",
            "sets": sets,
        })
    except API_ERRORS as exc:
        handle_api_error(exc)
        return
    st.session_state["workout_message"] = f"Workout saved: {len(sets)} sets logged. Great work! 💪"
    st.rerun()


def sets_table(session: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Exercise": s["exercise"]["name"],
        "Set": s["set_number"],
        "Reps": s["reps"],
        "Weight (kg)": s["weight_kg"] if s["weight_kg"] is not None else "—",
        "RPE": s["rpe"] if s["rpe"] is not None else "—",
    } for s in session["sets"]])


def render_history_tab(client: CoachinClient) -> None:
    try:
        page = client.list_workouts(limit=30)
    except API_ERRORS as exc:
        handle_api_error(exc)
        return
    sessions = page["items"]
    if not sessions:
        st.info("No workouts logged yet. Your history and progress charts will appear here.")
        return

    exercises = {s["exercise"]["id"]: s["exercise"]["name"] for session in sessions for s in session["sets"]}
    st.subheader("Progress")
    exercise_id = st.selectbox("Exercise", list(exercises), format_func=exercises.get)
    weeks = st.segmented_control("Period", [4, 12, 26, 52], default=12, format_func=lambda w: f"{w} weeks")
    try:
        history = client.exercise_history(exercise_id, weeks=weeks or 12)
    except API_ERRORS as exc:
        handle_api_error(exc)
        return
    if any(p["estimated_1rm_kg"] for p in history):
        st.plotly_chart(exercise_progress_chart(history, exercises[exercise_id]), width="stretch")
    else:
        st.caption("No weighted sets for this exercise in this period, so there's no strength chart to draw.")
    with st.expander("Show as table"):
        st.dataframe(pd.DataFrame([{
            "Date": p["performed_at"][:10], "Top set (kg)": p["top_set_weight_kg"], "Reps": p["top_set_reps"],
            "Est. 1RM (kg)": p["estimated_1rm_kg"], "Volume (kg)": p["total_volume_kg"],
        } for p in history]), hide_index=True, width="stretch")

    st.subheader(f"Recent sessions ({page['total']})")
    for session in sessions:
        started = datetime.fromisoformat(session["started_at"])
        names = list(dict.fromkeys(s["exercise"]["name"] for s in session["sets"]))
        title = f"{started:%a %d %b} · {len(names)} exercises, {len(session['sets'])} sets"
        with st.expander(title):
            if session["session_rpe"]:
                st.caption(f"Session RPE {session['session_rpe']:g}")
            if session["notes"]:
                st.write(session["notes"])
            st.dataframe(sets_table(session), hide_index=True, width="stretch")
            if st.button("Delete this session", key=f"del_{session['id']}"):
                try:
                    client.delete_workout(session["id"])
                except API_ERRORS as exc:
                    handle_api_error(exc)
                else:
                    st.session_state["workout_message"] = "Session deleted."
                    st.rerun()


def main() -> None:
    client = require_login()
    st.title("Workouts")
    if message := st.session_state.pop("workout_message", None):
        st.success(message)
    log_tab, history_tab = st.tabs(["Log workout", "History & progress"])
    with log_tab:
        render_log_tab(client)
    with history_tab:
        render_history_tab(client)


main()
