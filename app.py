#!/usr/bin/env python3
"""
Streamlit UI for the Cronometer nutrient deficiency analyzer.

Same underlying logic as full_analysis.py (the CLI) -- this just swaps
argparse + print() for st widgets + st output. All the real work still
happens in parser.py / analyzer.py / food_recommender.py / local_food_data.py.
"""
from __future__ import annotations

import tempfile
import os

import streamlit as st

from parser import parse_cronometer_csv
from analyzer import UserProfile, analyze_deficiencies, NutrientStatus
from food_recommender import build_food_pool, recommend_foods, CANDIDATE_FOODS
from local_food_data import LocalFDCClient

# ---------------------------------------------------------------------------
# Config -- point this at wherever the static JSON database lives in the repo.
# If you have both a Foundation Foods and an SR Legacy file, list both.
# ---------------------------------------------------------------------------
DATABASE_JSON_PATHS = ["FoodData_Central_foundation_food_json_2026-04-30.json"]  # <-- rename to match your actual file
EXCLUDED_CATEGORIES = {"Beverages"}


@st.cache_resource(show_spinner="Loading food database...")
def get_fdc_client():
    """Loaded once per server process, not once per user click."""
    return LocalFDCClient(DATABASE_JSON_PATHS, excluded_categories=EXCLUDED_CATEGORIES)


def status_line(s: NutrientStatus) -> str:
    if s.status == "no_data":
        return f"**{s.nutrient}** -- not present in this export"
    pct = f"{s.pct_of_target:.1f}%" if s.pct_of_target is not None else "n/a"
    target = f"{s.target:.2f}" if s.target is not None else "n/a"
    return (
        f"**{s.nutrient}**: {s.median_intake:.2f} {s.unit} "
        f"vs {s.target_type or '?'} {target} → {pct}  `[{s.status}]`"
    )


def render_deficiency_report(report, show_adequate: bool) -> None:
    st.subheader("Summary")
    st.write(
        f"Window analyzed: {report.window[0]} to {report.window[1]} "
        f"({report.days_analyzed} days logged)"
    )
    st.write(f"Profile: age {report.profile.age}, {report.profile.sex}")

    deficiencies = report.deficiencies()
    st.subheader(f"Deficient / Borderline ({len(deficiencies)})")
    if not deficiencies:
        st.success("None -- nice work.")
    else:
        for s in deficiencies:
            st.markdown(status_line(s))

    excesses = report.excesses()
    if excesses:
        st.subheader(f"Above Recommended Ceiling ({len(excesses)})")
        for s in excesses:
            ul_label = s.ul_type or "UL"
            st.markdown(f"**{s.nutrient}**: {s.median_intake:.2f} {s.unit} vs {ul_label} {s.ul:.2f}")

    no_data = report.no_data()
    if no_data:
        st.subheader(f"Not Tracked In This Export ({len(no_data)})")
        st.write(", ".join(s.nutrient for s in no_data))

    if report.limitations:
        st.subheader("Known Limitations")
        for note in report.limitations:
            st.caption(f"- {note}")

    if show_adequate:
        adequate = [s for s in report.statuses if s.status == "adequate"]
        st.subheader(f"Adequate ({len(adequate)})")
        for s in adequate:
            st.markdown(status_line(s))


def render_food_recommendations(recs) -> None:
    st.subheader("Recommended Foods (per 100g serving)")
    if not recs:
        st.info("No recommendations -- either no deficiencies found, or no food data available.")
        return
    for i, r in enumerate(recs, 1):
        addressed = ", ".join(f"{n} {pct:.0f}%" for n, pct in r.addressed)
        with st.container(border=True):
            st.markdown(f"**{i}. {r.food.description}**  _{r.food.data_type}_")
            st.caption(f"closes: {addressed}")


def main():
    st.set_page_config(page_title="Nutrient Deficiency Analyzer", layout="centered")
    st.title("Nutrient Deficiency Analyzer")
    st.caption("Upload a Cronometer 'Daily Nutrition' CSV export to check for deficiencies")
    st.caption("cronometer.com -> 'More' -> 'Your Account' -> 'Account Data' -> 'Export Data'")

    with st.sidebar:
        st.header("Your Info")
        age = st.number_input("Age", min_value=19, max_value=120, value=30, step=1)
        sex = st.selectbox("Sex", ["male", "female"])

        st.header("Options")
        show_adequate = st.checkbox("Show adequate nutrients too", value=False)
        no_food_recs = st.checkbox("Skip food recommendations", value=False)
        top_n = st.slider("Number of foods to recommend", min_value=1, max_value=20, value=6)

    uploaded_file = st.file_uploader("Cronometer CSV export", type=["csv"])

    if not uploaded_file:
        st.info("Upload a CSV file to get started.")
        return

    if st.button("Run Analysis", type="primary"):
        # parse_cronometer_csv expects a path, so write the upload to a temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        try:
            with st.spinner("Parsing CSV..."):
                try:
                    parsed = parse_cronometer_csv(tmp_path)
                except (FileNotFoundError, ValueError) as e:
                    st.error(f"Error reading file: {e}")
                    return

            st.write(f"Date range: {parsed.date_range[0]} to {parsed.date_range[1]}")
            st.write(
                f"Days in range: {parsed.days_in_range}, "
                f"days with logged data: {parsed.days_logged}"
            )
            if parsed.skipped_dates:
                st.warning(f"Skipped (no data logged): {parsed.skipped_dates}")

            if parsed.days_logged == 0:
                st.error("No logged days in this export -- nothing to analyze.")
                return

            try:
                profile = UserProfile(age=age, sex=sex)
            except ValueError as e:
                st.error(str(e))
                return

            report = analyze_deficiencies(parsed.daily, profile)
            render_deficiency_report(report, show_adequate)

            if no_food_recs:
                return

            if not report.deficiencies():
                st.success("No deficiencies found -- skipping food recommendations.")
                return

            with st.spinner("Scoring food recommendations..."):
                client = get_fdc_client()
                use_full_database = False
                if use_full_database:
                    pool = client.all_food_profiles()
                    st.caption(f"Scoring against the full local database: {len(pool)} foods")
                else:
                    pool = build_food_pool(client, CANDIDATE_FOODS, cache_path=None)

                try:
                    recs = recommend_foods(report, pool, top_n=top_n)
                except Exception as e:
                    st.warning(f"Skipping food recommendations: lookup failed ({e})")
                    return

            render_food_recommendations(recs)

        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    main()
