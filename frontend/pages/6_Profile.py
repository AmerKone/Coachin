"""Onboarding / profile settings.

Goal, level, schedule, equipment, injuries & medical conditions (with a clearance
checkbox), dietary preferences, macro targets, and preferred coach voice.
"""

from datetime import date
from typing import Any

import httpx
import streamlit as st

from client.api_client import ApiError
from components.auth import handle_api_error, require_login
from components.safety import render_disclaimer

SEX_OPTIONS = {None: "Prefer not to say / skip", "female": "Female", "male": "Male", "other": "Other"}
LEVELS = {"beginner": "Beginner", "intermediate": "Intermediate", "advanced": "Advanced"}
GOALS = {
    "general_fitness": "General fitness",
    "fat_loss": "Fat loss",
    "muscle_gain": "Muscle gain",
    "strength": "Strength",
    "endurance": "Endurance",
}
# Must match backend `Equipment` enum values so exercises can be matched to what the user owns.
EQUIPMENT = ["barbell", "dumbbells", "kettlebells", "squat rack", "bench", "pull-up bar", "dip bars",
             "resistance bands", "cable machine", "machines", "cardio machine"]
DIETS = ["vegetarian", "vegan", "pescatarian", "halal", "kosher", "gluten-free", "lactose-free",
         "nut allergy"]
VOICES = [None, "alloy", "echo", "fable", "onyx", "nova", "shimmer"]


def _index(options: list, value: Any) -> int:
    return options.index(value) if value in options else 0


def render_form(profile: dict[str, Any]) -> dict[str, Any] | None:
    """Render the profile form pre-filled from `profile`; return the payload when submitted."""
    with st.form("profile"):
        st.subheader("About you")
        c1, c2 = st.columns(2)
        dob_value = date.fromisoformat(profile["date_of_birth"]) if profile.get("date_of_birth") else None
        date_of_birth = c1.date_input("Date of birth", value=dob_value, min_value=date(1920, 1, 1),
                                      max_value=date.today(), format="YYYY-MM-DD")
        sex_keys = list(SEX_OPTIONS)
        sex = c2.selectbox("Sex", sex_keys, index=_index(sex_keys, profile.get("sex")),
                           format_func=SEX_OPTIONS.get,
                           help="Used to estimate calorie needs.")
        height_cm = c1.number_input("Height (cm)", min_value=51.0, max_value=299.0,
                                    value=profile.get("height_cm"), step=1.0)
        weight_kg = c2.number_input("Weight (kg)", min_value=21.0, max_value=399.0,
                                    value=profile.get("weight_kg"), step=0.5)

        st.subheader("Training")
        c1, c2 = st.columns(2)
        level_keys, goal_keys = list(LEVELS), list(GOALS)
        fitness_level = c1.selectbox("Experience level", level_keys,
                                     index=_index(level_keys, profile.get("fitness_level")),
                                     format_func=LEVELS.get)
        primary_goal = c2.selectbox("Primary goal", goal_keys,
                                    index=_index(goal_keys, profile.get("primary_goal")),
                                    format_func=GOALS.get)
        training_days = c1.slider("Training days per week", 1, 7, profile.get("training_days_per_week", 3))
        session_minutes = c2.slider("Session length (minutes)", 10, 240,
                                    profile.get("session_duration_min", 60), step=5)
        saved_equipment = [e for e in profile.get("available_equipment", []) if e in EQUIPMENT]
        full_gym = st.checkbox("I train at a fully equipped gym",
                               value=set(saved_equipment) == set(EQUIPMENT))
        equipment = st.multiselect("Available equipment", EQUIPMENT, default=saved_equipment,
                                   help="Leave empty if you train with bodyweight only. "
                                        "Ignored when the full-gym box is ticked.")

        st.subheader("Health & safety")
        st.caption("Your coach uses this to avoid unsafe exercises. Leave blank if none.")
        injuries = st.text_area("Injuries or physical limitations", value=profile.get("injuries") or "")
        medical_conditions = st.text_area("Medical conditions or medications",
                                          value=profile.get("medical_conditions") or "")
        medical_clearance = st.checkbox("A doctor has cleared me for exercise",
                                        value=profile.get("medical_clearance", False))

        st.subheader("Nutrition")
        saved_diets = profile.get("dietary_preferences", [])
        dietary_preferences = st.multiselect("Dietary preferences / restrictions",
                                             sorted(set(DIETS) | set(saved_diets)),
                                             default=saved_diets, accept_new_options=True)
        st.caption("Daily targets are optional; leave blank and your coach can suggest them.")
        c1, c2, c3, c4 = st.columns(4)
        calories = c1.number_input("Calories", min_value=800, max_value=10000, step=50,
                                   value=profile.get("daily_calorie_target"))
        protein = c2.number_input("Protein (g)", min_value=0, max_value=1000, step=5,
                                  value=profile.get("daily_protein_target_g"))
        carbs = c3.number_input("Carbs (g)", min_value=0, max_value=2000, step=5,
                                value=profile.get("daily_carbs_target_g"))
        fat = c4.number_input("Fat (g)", min_value=0, max_value=1000, step=5,
                              value=profile.get("daily_fat_target_g"))

        st.subheader("Coach voice")
        preferred_voice = st.selectbox("Voice", VOICES, index=_index(VOICES, profile.get("preferred_tts_voice")),
                                       format_func=lambda v: "Default" if v is None else v.title())

        if not st.form_submit_button("Save profile", type="primary"):
            return None

    return {
        "date_of_birth": date_of_birth.isoformat() if date_of_birth else None,
        "sex": sex,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "fitness_level": fitness_level,
        "primary_goal": primary_goal,
        "training_days_per_week": training_days,
        "session_duration_min": session_minutes,
        "available_equipment": list(EQUIPMENT) if full_gym else equipment,
        "injuries": injuries.strip() or None,
        "medical_conditions": medical_conditions.strip() or None,
        "medical_clearance": medical_clearance,
        "dietary_preferences": dietary_preferences,
        "daily_calorie_target": calories,
        "daily_protein_target_g": protein,
        "daily_carbs_target_g": carbs,
        "daily_fat_target_g": fat,
        "preferred_tts_voice": preferred_voice,
    }


def main() -> None:
    client = require_login()
    st.title("Your profile")
    if st.session_state.pop("profile_saved", False):
        st.success("Profile saved.")

    try:
        profile = client.get_profile()
    except (ApiError, httpx.TransportError) as exc:
        handle_api_error(exc)
        return

    if profile is None:
        st.info("Welcome! Tell your coach about yourself so your training can be personalized.")

    payload = render_form(profile or {})
    if payload is not None:
        try:
            client.save_profile(payload)
        except (ApiError, httpx.TransportError) as exc:
            handle_api_error(exc)
        else:
            # Rerun so the page reflects the saved profile; the flag shows the message after.
            st.session_state["profile_saved"] = True
            st.rerun()

    render_disclaimer()


main()
