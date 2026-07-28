from __future__ import annotations

import datetime
from pathlib import Path

import streamlit as st

from score_model import (
    assign_risk_band,
    calculate_egfr_history_features,
    derive_display_bands_from_json,
    egfr_history_to_model_inputs,
    explain_result,
    get_monitoring_threshold,
    load_parameters,
    predict_risk,
)


PARAMETER_PATH = Path(__file__).with_name("model_parameters.json")

APP_TITLE = "SPARK: Stratified Primary-care Assessment of Risk for Kidney decline"
APP_SUBTITLE = (
    "Research-use calculator for predicted 3-year risk of sustained "
    "≥30% eGFR decline"
)
APP_TAGLINE = "An ACR-free, diagnosis-code-free monitoring-priority calculator"

ABOUT_SPARK = (
    "SPARK (Stratified Primary-care Assessment of Risk for Kidney decline) is a "
    "research-use calculator that reconstructs the locked ACR-free Primary model "
    "for predicted 3-year risk of sustained ≥30% eGFR decline. It is intended for "
    "manuscript support, sensitivity checking, and research communication about "
    "monitoring-priority thresholds. The model uses six numeric predictors, sex, "
    "and three prior-year medication or medication-burden indicators."
)

DISCLAIMER = (
    "This calculator is for research and manuscript-support use only. It is not "
    "a diagnostic, treatment, referral, or deployment-ready clinical "
    "decision-support tool. Local validation, recalibration or threshold review, "
    "and prospective workflow evaluation are required before clinical use. "
    "Interpret only in the context of clinical judgement and local pathways."
)

RESEARCH_USE_SHORT = "Research-use only — not for clinical decision-making."

COL_RATIO = [0.58, 0.42]

SEX_OPTIONS = ("Female", "Male", "Unknown/unspecified")
SEX_VALUE = {"Female": "F", "Male": "M", "Unknown/unspecified": "U"}


@st.cache_data
def cached_parameters():
    return load_parameters(PARAMETER_PATH)


def yes_no_to_int(value: str) -> int:
    return 1 if value == "Yes" else 0


def render_result_card(input_values, params) -> None:
    """Render the prominent shared result card used by both input modes."""
    with st.container(border=True):
        st.markdown("#### Result")
        try:
            monitoring_threshold = get_monitoring_threshold(params)
            display_bands = derive_display_bands_from_json(params)
            risk = predict_risk(input_values, params)
            risk_band = assign_risk_band(risk, display_bands)
            threshold_met = risk >= monitoring_threshold

            st.metric("Predicted 3-year risk", f"{risk * 100:.2f}%")
            st.markdown(f"**Risk band:** {risk_band}")
            st.markdown(
                f"**≥{monitoring_threshold * 100:g}% monitoring-priority "
                f"threshold:** " + ("Met" if threshold_met else "Not met")
            )
            explanation = explain_result(risk, monitoring_threshold)
            if threshold_met:
                st.success(explanation)
            else:
                st.info(explanation)
            st.caption(RESEARCH_USE_SHORT)
        except ValueError as exc:
            st.error(str(exc))
            st.caption(RESEARCH_USE_SHORT)


def render_placeholder_card() -> None:
    with st.container(border=True):
        st.markdown("#### Result")
        st.info("Enter inputs and select **Calculate risk** to see the result.")
        st.caption(RESEARCH_USE_SHORT)


def previous_egfr_inputs(today: datetime.date) -> list[dict]:
    """Render five compact previous-eGFR rows and collect non-blank ones."""
    st.markdown("**Previous eGFR measurements (prior 2 years)**")
    st.caption(
        "Rows 1–2 are required; rows 3–5 are optional. Do not include the "
        "current/index eGFR. Blank optional rows are ignored."
    )
    defaults = [
        (today - datetime.timedelta(days=180), 75.0),
        (today - datetime.timedelta(days=540), 78.0),
        (None, None),
        (None, None),
        (None, None),
    ]
    records: list[dict] = []
    for i, (date_default, value_default) in enumerate(defaults, start=1):
        date_col, value_col = st.columns([1, 1])
        with date_col:
            record_date = st.date_input(
                f"Previous eGFR {i} — date",
                value=date_default,
                format="YYYY-MM-DD",
                key=f"egfr_prev_date_{i}",
            )
        with value_col:
            record_value = st.number_input(
                f"Previous eGFR {i} — value",
                min_value=0.0,
                max_value=300.0,
                value=value_default,
                step=1.0,
                help="mL/min/1.73 m²",
                key=f"egfr_prev_value_{i}",
            )
        if record_date is None and record_value is None:
            continue
        records.append({"date": record_date, "egfr": record_value})
    return records


st.set_page_config(
    page_title="SPARK kidney-decline monitoring-priority calculator",
    page_icon="",
    layout="wide",
)

st.title(APP_TITLE)
st.caption(APP_TAGLINE)
st.markdown(f"**{APP_SUBTITLE}**")

with st.expander("About SPARK"):
    st.write(ABOUT_SPARK)

params = cached_parameters()

tab_egfr, tab_advanced = st.tabs(
    ["eGFR-test input", "Advanced model-ready input"]
)


# --------------------------------------------------------------------------- #
# Tab 1: eGFR-test input (default, user-friendly)
# --------------------------------------------------------------------------- #
with tab_egfr:
    today = datetime.date.today()
    inputs_col, result_col = st.columns(COL_RATIO)

    with inputs_col:
        st.caption(
            "Enter the current eGFR test plus at least two previous eGFR tests "
            "from the prior 2 years. eGFR-history inputs are derived "
            "automatically."
        )

        demo_a, demo_b = st.columns([1, 1])
        with demo_a:
            egfr_age = st.number_input(
                "Age at index",
                min_value=18.0,
                max_value=120.0,
                value=71.0,
                step=1.0,
                key="egfr_age",
            )
        with demo_b:
            egfr_sex_label = st.selectbox(
                "Sex", options=SEX_OPTIONS, index=0, key="egfr_sex"
            )

        index_a, index_b = st.columns([1, 1])
        with index_a:
            egfr_index_date = st.date_input(
                "Current eGFR test date",
                value=today,
                format="YYYY-MM-DD",
                key="egfr_index_date",
            )
        with index_b:
            egfr_index_value = st.number_input(
                "Current/index eGFR value",
                min_value=0.0,
                max_value=300.0,
                value=73.0,
                step=1.0,
                help="mL/min/1.73 m²; must be within 30–120 to score.",
                key="egfr_index_value",
            )

        previous_records = previous_egfr_inputs(today)

        st.markdown("**Prior-year medication / burden**")
        egfr_acei_arb = st.radio(
            "ACEi/ARB exposure in prior year", ("No", "Yes"),
            horizontal=True, key="egfr_acei_arb",
        )
        egfr_diuretic = st.radio(
            "Diuretic exposure in prior year", ("No", "Yes"),
            horizontal=True, key="egfr_diuretic",
        )
        egfr_polypharmacy = st.radio(
            "Polypharmacy ≥5 ATC components in prior year", ("No", "Yes"),
            horizontal=True, key="egfr_polypharmacy",
        )

        calculate = st.button(
            "Calculate risk", type="primary", key="egfr_calculate"
        )

    with result_col:
        if not calculate:
            render_placeholder_card()
        else:
            try:
                features, warnings = calculate_egfr_history_features(
                    egfr_index_date, egfr_index_value, previous_records
                )
                sex_value = SEX_VALUE[egfr_sex_label]
                input_values = {
                    "age_at_index": egfr_age,
                    "gender_at_index": sex_value,
                    **egfr_history_to_model_inputs(features),
                    "acei_arb_1y": yes_no_to_int(egfr_acei_arb),
                    "diuretic_1y": yes_no_to_int(egfr_diuretic),
                    "polypharmacy_5plus_1y": yes_no_to_int(egfr_polypharmacy),
                }
                render_result_card(input_values, params)

                for warning in warnings:
                    st.warning(warning)

                with st.expander("Calculated model inputs"):
                    st.write(
                        f"- **Index eGFR:** {features['index_egfr']:.4g} "
                        "mL/min/1.73 m²"
                    )
                    st.write(
                        f"- **2-year mean pre-index eGFR:** "
                        f"{features['egfr_mean_2y']:.4g} mL/min/1.73 m²"
                    )
                    st.write(
                        f"- **Count of pre-index eGFR measurements:** "
                        f"{int(features['egfr_count_2y'])}"
                    )
                    st.write(
                        f"- **Relative eGFR change over 2 years:** "
                        f"{features['egfr_relative_change_2y']:.4f}"
                    )
                    st.write(
                        f"- **Annualised 2-year eGFR slope:** "
                        f"{features['egfr_slope_2y']:.4g} mL/min/1.73 m²/year"
                    )
                    st.write(f"- **Age at index:** {egfr_age:g}")
                    st.write(f"- **Sex:** {egfr_sex_label}")
                    st.write(
                        f"- **ACEi/ARB exposure in prior year:** {egfr_acei_arb}"
                    )
                    st.write(
                        f"- **Diuretic exposure in prior year:** {egfr_diuretic}"
                    )
                    st.write(
                        f"- **Polypharmacy ≥5 ATC components in prior year:** "
                        f"{egfr_polypharmacy}"
                    )
            except ValueError as exc:
                with st.container(border=True):
                    st.markdown("#### Result")
                    st.error(str(exc))
                    st.caption(RESEARCH_USE_SHORT)

    with st.expander("Research-use limitations"):
        st.write(DISCLAIMER)


# --------------------------------------------------------------------------- #
# Tab 2: Advanced model-ready input (existing validated calculator preserved)
# --------------------------------------------------------------------------- #
with tab_advanced:
    inputs_col, result_col = st.columns(COL_RATIO)

    with inputs_col:
        st.caption(
            "Enter already derived predictor values for the locked Primary "
            "model. This mode supports reproducibility and model-ready inputs."
        )

        adv_a, adv_b = st.columns([1, 1])
        with adv_a:
            age_at_index = st.number_input(
                "Age at index",
                min_value=18.0,
                max_value=120.0,
                value=71.0,
                step=1.0,
                key="adv_age",
            )
        with adv_b:
            sex_label = st.selectbox(
                "Sex", options=SEX_OPTIONS, index=0, key="adv_sex"
            )
        sex_value = SEX_VALUE[sex_label]

        index_egfr = st.number_input(
            "Index eGFR",
            min_value=0.0,
            max_value=150.0,
            value=73.0,
            step=1.0,
            help="mL/min/1.73 m² at the index date.",
            key="adv_index_egfr",
        )
        baseline_egfr_mean_preindex_2y = st.number_input(
            "2-year mean pre-index eGFR",
            min_value=0.0,
            max_value=150.0,
            value=73.7,
            step=0.1,
            help="mL/min/1.73 m²; mean of pre-index eGFR over the 2-year lookback.",
            key="adv_baseline_egfr_mean",
        )
        n_egfr_preindex_2y = st.number_input(
            "Count of pre-index eGFR measurements",
            min_value=0,
            max_value=100,
            value=2,
            step=1,
            help="Number of pre-index eGFR measurements over the 2-year lookback.",
            key="adv_n_egfr",
        )
        egfr_relative_change_mean_to_index_2y = st.number_input(
            "Relative eGFR change over 2 years",
            min_value=-1.0,
            max_value=1.0,
            value=0.0,
            step=0.01,
            format="%.4f",
            help=(
                "Enter as a proportion; for example, -0.10 means a 10% decrease "
                "from baseline to index."
            ),
            key="adv_relative_change",
        )
        egfr_slope_2y = st.number_input(
            "Annualised 2-year eGFR slope",
            min_value=-200.0,
            max_value=200.0,
            value=0.0,
            step=0.5,
            help="mL/min/1.73 m²/year.",
            key="adv_slope",
        )

        acei_arb = st.radio(
            "ACEi/ARB exposure in prior year", ("No", "Yes"),
            horizontal=True, key="adv_acei_arb",
        )
        diuretic = st.radio(
            "Diuretic exposure in prior year", ("No", "Yes"),
            horizontal=True, key="adv_diuretic",
        )
        polypharmacy = st.radio(
            "Polypharmacy ≥5 ATC components", ("No", "Yes"),
            horizontal=True, key="adv_polypharmacy",
        )

    input_values = {
        "age_at_index": age_at_index,
        "gender_at_index": sex_value,
        "index_egfr": index_egfr,
        "baseline_egfr_mean_preindex_2y": baseline_egfr_mean_preindex_2y,
        "n_egfr_preindex_2y": n_egfr_preindex_2y,
        "egfr_relative_change_mean_to_index_2y": egfr_relative_change_mean_to_index_2y,
        "egfr_slope_2y": egfr_slope_2y,
        "acei_arb_1y": yes_no_to_int(acei_arb),
        "diuretic_1y": yes_no_to_int(diuretic),
        "polypharmacy_5plus_1y": yes_no_to_int(polypharmacy),
    }

    with result_col:
        render_result_card(input_values, params)
        with st.expander("Model description"):
            st.write(ABOUT_SPARK)
            st.write(
                "The score is intended to support manuscript review, sensitivity "
                "checks, and research communication about monitoring-priority "
                "thresholds."
            )

    with st.expander("Research-use limitations"):
        st.write(DISCLAIMER)
