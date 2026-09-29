"""Coachin Streamlit entrypoint (home / dashboard).

Run with: `streamlit run frontend/app.py`
Additional pages live in `pages/` and appear in the sidebar automatically.
"""

from datetime import date

import httpx
import streamlit as st

from client.api_client import ApiError
from components.auth import current_user, handle_api_error, require_login
from components.safety import render_disclaimer

st.set_page_config(page_title="Coachin", page_icon="🏋️", layout="wide")

GOAL_LABELS = {
    "general_fitness": "General fitness",
    "fat_loss": "Fat loss",
    "muscle_gain": "Muscle gain",
    "strength": "Strength",
    "endurance": "Endurance",
}


def main() -> None:
    """Dashboard: greeting, profile snapshot, and quick links.

    Sends new users without a profile to the Profile page for onboarding.
    """
    client = require_login()
    user = current_user() or {}
    first_name = (user.get("full_name") or "").split(" ")[0]
    st.title(f"Welcome{', ' + first_name if first_name else ''}!")

    try:
        profile = client.get_profile()
    except (ApiError, httpx.TransportError) as exc:
        handle_api_error(exc)
        return

    if profile is None:
        st.info("Let's set up your profile so your coach can build your program.")
        st.page_link("pages/6_Profile.py", label="Complete your profile", icon="📝")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Goal", GOAL_LABELS.get(profile["primary_goal"], profile["primary_goal"]))
    c2.metric("Training days / week", profile["training_days_per_week"])
    c3.metric("Weight", f"{profile['weight_kg']:g} kg" if profile.get("weight_kg") else "—")

    st.divider()
    render_today(client)
    st.caption("Nutrition and progress will appear here as those features are built.")
    st.page_link("pages/6_Profile.py", label="Edit profile", icon="📝")
    render_disclaimer()


def render_today(client) -> None:
    """Today's planned workout from the active program, if any."""
    try:
        program = client.get_active_program()
    except (ApiError, httpx.TransportError) as exc:
        handle_api_error(exc)
        return
    if program is None:
        st.subheader("Today's workout")
        st.write("No active program yet.")
        st.page_link("pages/2_Program.py", label="Generate your program", icon="🏋️")
        return

    today = date.today()
    days_in = (today - date.fromisoformat(program["start_date"])).days
    if days_in < 0:
        st.subheader("Today's workout")
        st.write(f"**{program['name']}** starts on {program['start_date']}.")
        return
    week = min(days_in // 7 + 1, program["duration_weeks"])
    workout = next(
        (w for w in program["workouts"] if w["week_number"] == week and w["day_of_week"] == today.weekday()),
        None,
    )
    st.subheader(f"Today's workout · week {week} of {program['duration_weeks']}")
    if workout is None:
        st.write("Rest day. Recover well! 💤")
    else:
        st.markdown(f"**{workout['name']}**" + (f" — _{workout['focus']}_" if workout.get("focus") else ""))
        for planned in workout["exercises"]:
            lo, hi = planned["target_reps_min"], planned["target_reps_max"]
            reps = str(lo) if lo == hi else f"{lo}-{hi}"
            st.markdown(f"- {planned['exercise']['name']}: {planned['target_sets']} × {reps}")
    st.page_link("pages/2_Program.py", label="View full program", icon="🗓️")


if __name__ == "__main__":
    main()
