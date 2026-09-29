"""Monthly progress: curves for body weight, strength, calories and training volume, summary
tiles, and the coach's written monthly report. Also records body weight."""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import streamlit as st

from client.api_client import ApiError, CoachinClient
from components.auth import handle_api_error, require_login
from components.charts import body_weight_trend_chart, calories_chart, strength_chart, volume_chart
from components.local_time import local_today, local_tz_name
from components.safety import render_disclaimer

API_ERRORS = (ApiError, httpx.TransportError)
FLAG_TEXT = {
    "rapid_weight_loss": "You're losing weight faster than about 1% of body weight per week. A slower pace protects "
                         "your muscle and energy; consider eating a little more.",
    "eating_far_below_target": "Your average intake is well below your target. Under-eating makes training and "
                               "recovery harder; try to eat closer to your target.",
    "low_protein": "Protein has been under your target on average. Adding a protein source to each meal helps.",
    "low_adherence": "You completed fewer than half of your planned sessions. A shorter plan may be easier to keep.",
    "safety_events": "Some messages this month raised health concerns. If you had symptoms, please check in with a "
                     "health professional.",
}


def month_bounds(first: date, today: date) -> tuple[date, date]:
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return first, min(last, today)


def choose_period(today: date) -> tuple[date, date, bool]:
    """Returns (start, end, is_complete_month)."""
    months = []
    first = today.replace(day=1)
    for _ in range(12):
        months.append(first)
        first = (first - timedelta(days=1)).replace(day=1)
    choice = st.selectbox("Month", months, format_func=lambda m: ("This month (so far)" if m == months[0]
                          else f"{m:%B %Y}"), index=1 if today.day <= 3 else 0)
    start, end = month_bounds(choice, today)
    return start, end, choice != months[0]


def render_tiles(o: dict[str, Any]) -> None:
    t, n, b = o["training"], o["nutrition"], o["body"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sessions", f"{t['sessions_completed']}" + (f" / {t['workouts_planned']}" if t["workouts_planned"] else ""),
              f"{t['adherence_pct']:g}% of plan" if t["adherence_pct"] is not None else None, delta_color="off")
    c2.metric("Avg calories", f"{n['avg_calories']:,.0f} kcal" if n["avg_calories"] is not None else "—",
              f"target {n['calorie_target']:,.0f}" if n["calorie_target"] else None, delta_color="off")
    c3.metric("Avg protein", f"{n['avg_protein_g']:.0f} g" if n["avg_protein_g"] is not None else "—",
              f"target {n['protein_target_g']:.0f} g" if n["protein_target_g"] else None, delta_color="off")
    c4.metric("Weight", f"{b['end_weight_kg']:.1f} kg" if b["end_weight_kg"] else "—",
              f"{b['change_kg']:+.1f} kg this period" if b["change_kg"] is not None else None, delta_color="off")
    st.caption(f"{n['days_logged']} days of meals logged · {t['total_sets']} working sets · "
               f"{t['total_volume_kg']:,.0f} kg lifted")
    for flag in o["flags"]:
        if flag in FLAG_TEXT:
            st.info(FLAG_TEXT[flag], icon="💡")


def chart_block(title: str, has_data: bool, empty_hint: str, figure_fn, table: pd.DataFrame) -> None:
    st.markdown(f"**{title}**")
    if not has_data:
        st.caption(empty_hint)
        return
    st.plotly_chart(figure_fn(), width="stretch")
    with st.expander("Show as table"):
        st.dataframe(table, hide_index=True, width="stretch")


def render_charts(o: dict[str, Any]) -> None:
    left, right = st.columns(2)
    with left:
        chart_block("Body weight", len(o["weight_series"]) >= 2,
                    "Log your weight at least twice this month to see the curve.",
                    lambda: body_weight_trend_chart(o["weight_series"]),
                    pd.DataFrame(o["weight_series"]).rename(columns={"day": "Date", "weight_kg": "Weight (kg)"}))
    with right:
        rows = [{"Exercise": e["name"], "Date": p["day"], "Est. 1RM (kg)": p["estimated_1rm_kg"]}
                for e in o["strength"] for p in e["points"]]
        chart_block("Strength (estimated 1RM)", any(len(e["points"]) >= 2 for e in o["strength"]),
                    "Log the same exercise with weights on at least two days to see strength curves.",
                    lambda: strength_chart([e for e in o["strength"] if len(e["points"]) >= 2]),
                    pd.DataFrame(rows))
    left, right = st.columns(2)
    with left:
        chart_block("Calories per day", len(o["calorie_series"]) >= 2,
                    "Log meals on at least two days to see your calorie curve.",
                    lambda: calories_chart(o["calorie_series"], o["nutrition"]["calorie_target"]),
                    pd.DataFrame(o["calorie_series"]).rename(columns={"day": "Date", "calories": "kcal",
                                                                       "protein_g": "Protein (g)"}))
    with right:
        chart_block("Training volume", len(o["volume_series"]) >= 2,
                    "Train in at least two different weeks to see your volume curve.",
                    lambda: volume_chart(o["volume_series"]),
                    pd.DataFrame(o["volume_series"]).rename(columns={
                        "week_start": "Week of", "sessions": "Sessions", "sets": "Sets", "volume_kg": "Volume (kg)"}))


def render_report(client: CoachinClient, start: date, end: date, complete: bool) -> None:
    st.subheader("Your coach's report")
    try:
        existing = next((r for r in client.list_reports() if r["period_start"] == start.isoformat()), None)
        report = client.get_report(existing["id"]) if existing else None
    except API_ERRORS as exc:
        handle_api_error(exc)
        return

    if report:
        st.markdown(report["summary"])
        if report["recommendations"]:
            st.markdown("**For next month**")
            for line in report["recommendations"].splitlines():
                st.markdown(f"- {line}")
        st.caption(f"Written {report['updated_at'][:10]} for {report['period_start']} → {report['period_end']}.")
    else:
        st.caption("No report for this period yet." + ("" if complete else " This month isn't over, so a report "
                                                                              "now covers the days so far."))
    label = "Regenerate report" if report else "Write my report"
    if st.button(label, type="secondary" if report else "primary"):
        with st.spinner("Your coach is reviewing your month…"):
            try:
                client.generate_report(start, end, local_tz_name())
            except API_ERRORS as exc:
                handle_api_error(exc)
                return
        st.rerun()


def render_weight_form(client: CoachinClient) -> None:
    with st.expander("⚖️ Log your weight"), st.form("weight", clear_on_submit=True):
        c1, c2 = st.columns(2)
        weight = c1.number_input("Weight (kg)", min_value=20.5, max_value=399.0, value=None, step=0.1)
        day = c2.date_input("Date", value=local_today(), max_value=local_today())
        if st.form_submit_button("Save weight"):
            if weight is None:
                st.error("Enter your weight.")
                return
            recorded = datetime.combine(day, time(8, 0), tzinfo=ZoneInfo(local_tz_name()))
            try:
                client.record_metric({"recorded_at": recorded.isoformat(), "weight_kg": weight})
            except API_ERRORS as exc:
                handle_api_error(exc)
                return
            st.session_state["progress_message"] = f"Saved {weight:.1f} kg."
            st.rerun()


def main() -> None:
    client = require_login()
    st.title("Progress")
    if message := st.session_state.pop("progress_message", None):
        st.success(message)

    start, end, complete = choose_period(local_today())
    try:
        overview = client.progress_overview(start, end, local_tz_name())
    except API_ERRORS as exc:
        handle_api_error(exc)
        return

    render_tiles(overview)
    render_weight_form(client)
    st.divider()
    render_charts(overview)
    st.divider()
    render_report(client, start, end, complete)
    render_disclaimer()


main()
