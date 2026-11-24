"""RIDE (Risk Index for Decline in eGFR) web calculator (Streamlit).

All calculation is done by score_model.py; this file only collects the entered
values and shows the result.
"""

from __future__ import annotations

import datetime
import html

import streamlit as st

import score_model as engine

SOURCE_CODE_URL = "https://github.com/LouisZBF/SPARK"

TITLE = "RIDE"
SUBTITLE = "Risk Index for Decline in eGFR"
INTRO = (
    "Estimates the 3-year risk of sustained eGFR decline of 30% or greater from routinely available "
    "primary care data, without albuminuria measurements, to help prioritise repeat eGFR and urine ACR testing."
)
RESULT_HEADING = "Estimated 3-year risk"
HIGHER_PRIORITY = "Higher priority for kidney reassessment"
ROUTINE_PRIORITY = "Routine priority for kidney reassessment"
INTERPRETATION = "A 5% risk threshold was used in the study to prioritise repeat eGFR and urine ACR assessment."
STATEMENT = (
    "RIDE is intended to support prioritisation of kidney assessment in primary care. "
    "It does not diagnose CKD and does not replace urine ACR testing or KFRE when these are indicated."
)

UNIT = engine.EGFR_UNIT
SEX_OPTIONS = {"Female": "F", "Male": "M", "Unknown": "U"}
YES_NO = ("Yes", "No")
MEDICINE_QUESTIONS = (
    (
        "acei_arb",
        "ACE inhibitor or ARB use in the previous year",
        "Any prescription for an ACE inhibitor or angiotensin receptor blocker (ARB), including "
        "combination tablets, in the year before the current eGFR.",
    ),
    (
        "diuretic",
        "Diuretic use in the previous year",
        "Any prescription for a diuretic in the year before the current eGFR. In the study, combination "
        "tablets coded only as an ACE inhibitor or ARB combination (for example, irbesartan with "
        "hydrochlorothiazide) were not counted as diuretic use.",
    ),
    (
        "polypharmacy",
        "5 or more different medicines in the previous year",
        "Prescriptions for 5 or more different medicines in the year before the current eGFR.",
    ),
)
INPUT_REQUIREMENTS = f"""
All inputs are required.

- **Age:** whole years. RIDE was developed for ages 18 to 100.
- **Sex:** female, male or unknown. Choose Unknown if sex is not recorded.
- **Current eGFR and its date:** RIDE was developed for a current eGFR of 30 to 120 {engine.EGFR_UNIT}. Enter results
  reported as >90 as 90. If more than one eGFR was recorded that day, enter their average.
- **Previous eGFR results:** every result from the 2 years (730 days) before the current eGFR, each with its date.
  Results from the same day are averaged. Results outside this window, and daily values below 30 or above 120
  {engine.EGFR_UNIT}, are not used. At least 2 days with usable results are needed.
- **Medicines in the previous year:** yes or no for ACE inhibitor or ARB, diuretic, and 5 or more different medicines.

If an input is missing, a previous result lacks its date or value, or an eGFR is 0 or less or above 200
{engine.EGFR_UNIT}, no estimate is given and the calculator lists what to check. If age is outside 18 to 100 or the
current eGFR is outside 30 to 120 {engine.EGFR_UNIT}, or fewer than 2 days of previous results can be used, no estimate
is given and the reason is shown. Missing values are not imputed and out-of-range values are not adjusted.
"""

MIN_ROWS = 2
MAX_ROWS = 100
DATE_FORMAT = "DD/MM/YYYY"
EARLIEST_DATE = datetime.date(1990, 1, 1)
LATEST_DATE = datetime.date(2100, 12, 31)

STYLE = """
<style>
.block-container {max-width: 46rem; padding-top: 4.75rem; padding-bottom: 3rem;}
h1 {font-size: 2.3rem !important; margin-bottom: 0 !important; padding-bottom: 0 !important; letter-spacing: 0.03em;}
div[data-testid="stMarkdownContainer"] p.ride-subtitle {font-size: 1.15rem; font-weight: 600; color: #3d4a57;
  margin: 0.1rem 0 0.5rem 0;}
div.ride-result {border: 1px solid #d5dbe1; border-left-width: 6px; border-radius: 6px;
  padding: 1rem 1.25rem; margin: 0.75rem 0 0.75rem 0; background: #ffffff;}
div.ride-result p {margin: 0;}
div.ride-result p.ride-result-label {font-size: 0.95rem; color: #3d4a57;}
div.ride-result p.ride-result-value {font-size: 2.8rem; font-weight: 700; line-height: 1.2; color: #1a1a1a;
  margin: 0.1rem 0;}
div.ride-result p.ride-result-priority {font-size: 1.15rem; font-weight: 600;}
div.ride-result p.ride-result-note {font-size: 0.95rem; color: #3d4a57; margin-top: 0.6rem;}
div.ride-higher {border-left-color: #b45309;}
div.ride-higher p.ride-result-priority {color: #92400e;}
div.ride-routine {border-left-color: #3f6f5a;}
div.ride-routine p.ride-result-priority {color: #2f5446;}
</style>
"""


@st.cache_resource
def parameters() -> dict:
    return engine.load_parameters()


# --------------------------------------------------------------------------- entered values
def row_count() -> int:
    return st.session_state.get("n_previous", MIN_ROWS)


def input_keys() -> list:
    keys = ["age", "sex", "current_date", "current_egfr"] + [q[0] for q in MEDICINE_QUESTIONS]
    for i in range(1, row_count() + 1):
        keys += [f"prev_date_{i}", f"prev_egfr_{i}"]
    return keys


def keep_inputs() -> None:
    """Keep entered values while the About and Study pages are open.

    Streamlit discards the state of widgets that are not on the current page;
    re-saving the values prevents this.
    """
    for key in input_keys():
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def start_blank() -> None:
    """Every input starts empty: nothing is assumed."""
    for key in input_keys():
        st.session_state.setdefault(key, None)


def add_row() -> None:
    st.session_state["n_previous"] = min(row_count() + 1, MAX_ROWS)


def remove_row() -> None:
    n = row_count()
    if n > MIN_ROWS:
        st.session_state.pop(f"prev_date_{n}", None)
        st.session_state.pop(f"prev_egfr_{n}", None)
        st.session_state["n_previous"] = n - 1


def yes_no(answer):
    return None if answer is None else answer == "Yes"


def entered_values() -> dict:
    s = st.session_state
    rows = tuple((s.get(f"prev_date_{i}"), s.get(f"prev_egfr_{i}")) for i in range(1, row_count() + 1))
    return {
        "age": s.get("age"),
        "sex": SEX_OPTIONS.get(s.get("sex")),
        "current_date": s.get("current_date"),
        "current_egfr": s.get("current_egfr"),
        "previous_rows": rows,
        "acei_arb": yes_no(s.get("acei_arb")),
        "diuretic": yes_no(s.get("diuretic")),
        "polypharmacy": yes_no(s.get("polypharmacy")),
    }


def fingerprint(values: dict) -> str:
    """Identifies the entered values, so a result is never shown for values that have since changed."""
    shown = dict(values)
    shown["previous_rows"] = tuple(r for r in values["previous_rows"] if r != (None, None))
    return repr(sorted(shown.items()))


def calculate(values: dict):
    try:
        return engine.estimate_risk(parameters(), **values)
    except (engine.InputError, engine.OutsideIntendedUse) as problem:
        return problem


# --------------------------------------------------------------------------- display helpers
def egfr_text(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def day_text(day: datetime.date) -> str:
    return day.strftime("%d/%m/%Y")


def show_history(history, estimate) -> None:
    with st.expander("eGFR results used"):
        if estimate is not None:
            change = estimate.relative_change * 100
            if abs(change) < 0.05:
                change_text = "the same as this average"
            else:
                change_text = f"{abs(change):.1f}% {'higher' if change > 0 else 'lower'} than this average"
            st.markdown(
                f"Average of the previous results used: **{egfr_text(estimate.previous_mean)} {UNIT}** "
                f"({len(history.days_used)} days)  \nCurrent eGFR: **{change_text}**"
            )
        if history.days_used:
            lines = []
            for day in history.days_used:
                note = f" (average of {day.n_results} results that day)" if day.n_results > 1 else ""
                lines.append(f"- {day_text(day.date)}: {egfr_text(day.egfr)}{note}")
            st.markdown("Used:\n" + "\n".join(lines))
        if history.not_used:
            lines = []
            for day in history.not_used:
                note = f" (average of {day.n_results} results that day)" if day.n_results > 1 else ""
                lines.append(f"- {day_text(day.date)}: {egfr_text(day.egfr)}{note}: {day.reason}")
            st.markdown("Not used:\n" + "\n".join(lines))


def show_result(estimate, params: dict) -> None:
    higher = estimate.higher_priority
    css = "ride-higher" if higher else "ride-routine"
    priority = HIGHER_PRIORITY if higher else ROUTINE_PRIORITY
    risk = html.escape(engine.format_risk(estimate.probability, params))
    st.markdown(
        f'<div class="ride-result {css}" role="status">'
        f'<p class="ride-result-label">{RESULT_HEADING}</p>'
        f'<p class="ride-result-value">{risk}</p>'
        f'<p class="ride-result-priority">{priority}</p>'
        f'<p class="ride-result-note">{INTERPRETATION}</p>'
        f"</div>",
        unsafe_allow_html=True,
    )
    if estimate.history.not_used:
        st.caption("Some entered results were not used. See the list below.")
    show_history(estimate.history, estimate)


def show_outcome(outcome, params: dict) -> None:
    if isinstance(outcome, engine.InputError):
        st.error("Please check the following:\n\n" + "\n".join(f"- {m}" for m in outcome.messages))
    elif isinstance(outcome, engine.OutsideIntendedUse):
        st.warning("No estimate was calculated.\n\n" + "\n".join(f"- {m}" for m in outcome.messages))
        if outcome.history is not None and (outcome.history.days_used or outcome.history.not_used):
            show_history(outcome.history, None)
    else:
        show_result(outcome, params)


# --------------------------------------------------------------------------- page parts
def navigation(back_link: bool) -> None:
    with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
        if back_link:
            st.page_link(CALCULATOR, label="Calculator")
        st.page_link(ABOUT, label="About RIDE")
        st.page_link(STUDY, label="Study")
        st.page_link(SOURCE_CODE_URL, label="Source code")


def header(back_link: bool = False) -> None:
    navigation(back_link)
    st.title(TITLE, anchor=False)
    st.markdown(f'<p class="ride-subtitle">{SUBTITLE}</p>', unsafe_allow_html=True)


def footer() -> None:
    st.divider()
    st.caption(STATEMENT)


# --------------------------------------------------------------------------- pages
def calculator_page() -> None:
    params = parameters()
    start_blank()
    header()
    st.markdown(INTRO)
    with st.expander("Input requirements"):
        st.markdown(INPUT_REQUIREMENTS)

    st.subheader("Patient", anchor=False)
    left, right = st.columns(2)
    with left:
        st.number_input("Age (years)", key="age", step=1, format="%d",
                        help="Age in whole years at the date of the current eGFR.")
    with right:
        st.radio("Sex", tuple(SEX_OPTIONS), key="sex", horizontal=True,
                 help="Choose Unknown if sex is not recorded.")

    st.subheader("Current eGFR", anchor=False)
    left, right = st.columns(2)
    with left:
        st.date_input("Date of current eGFR", key="current_date", format=DATE_FORMAT,
                      min_value=EARLIEST_DATE, max_value=LATEST_DATE)
    with right:
        st.number_input(f"Current eGFR ({UNIT})", key="current_egfr", step=1.0, format="%.1f",
                        help="If reported as >90, enter 90. If more than one eGFR was recorded that day, "
                             "enter their average.")

    st.subheader("eGFR results from the previous 2 years", anchor=False)
    st.caption(
        "Enter every eGFR result from the 2 years (730 days) before the current eGFR. At least 2 days with "
        f"results of 30 to 120 {UNIT} are needed. Enter results reported as >90 as 90."
    )
    for i in range(1, row_count() + 1):
        left, right = st.columns(2)
        with left:
            st.date_input(f"Date of result {i}", key=f"prev_date_{i}", format=DATE_FORMAT,
                          min_value=EARLIEST_DATE, max_value=LATEST_DATE)
        with right:
            st.number_input(f"eGFR result {i} ({UNIT})", key=f"prev_egfr_{i}", step=1.0, format="%.1f")
    with st.container(horizontal=True, gap="small"):
        st.button("Add another result", on_click=add_row, disabled=row_count() >= MAX_ROWS)
        if row_count() > MIN_ROWS:
            st.button("Remove last result", on_click=remove_row)
    if row_count() >= MAX_ROWS:
        st.caption(f"Up to {MAX_ROWS} results can be entered.")

    st.subheader("Medicines", anchor=False)
    for key, label, help_text in MEDICINE_QUESTIONS:
        st.radio(label, YES_NO, key=key, horizontal=True, help=help_text)

    values = entered_values()
    if st.button("Calculate risk", type="primary", key="calculate", width="stretch"):
        st.session_state["outcome"] = (fingerprint(values), calculate(values))
    stored = st.session_state.get("outcome")
    if stored is not None and stored[0] == fingerprint(values):
        show_outcome(stored[1], params)
    footer()


def about_page() -> None:
    header(back_link=True)
    st.subheader("About RIDE", anchor=False)
    st.markdown(
        """
RIDE (Risk Index for Decline in eGFR) estimates the 3-year risk of sustained eGFR decline of 30% or greater. It uses
age, sex, the current eGFR, eGFR results from the previous 2 years and medication records from the previous year.
It does not require albuminuria measurements.

**Reading the result**

The result is the estimated chance of a sustained eGFR decline of 30% or greater within 3 years: an eGFR at or below
70% of the average of the previous 2 years, confirmed by a second result at or below that level at least 90 days
later, with no result above that level in between. In the study, an estimated risk of 5% or greater identified
patients for higher-priority reassessment. A routine-priority result does not rule out kidney function decline.

**Intended use**

RIDE is intended to help prioritise repeat eGFR and urine albumin-to-creatinine ratio (ACR) testing in primary care.
It does not estimate the risk of kidney failure. In people with chronic kidney disease, the Kidney Failure Risk
Equation (KFRE), which requires a urine ACR result, can be used when indicated.

**Development**

RIDE was developed and validated using past records. It has not been evaluated prospectively, and estimates may be
less accurate in populations that differ from those studied.

**Privacy**

The calculator does not save the information entered. Do not enter names or other identifying details.
"""
    )
    footer()


def study_page() -> None:
    header(back_link=True)
    st.subheader("Study", anchor=False)
    st.markdown(
        f"""
RIDE was developed and validated in a retrospective prognostic study.

**Data.** De-identified electronic health records from Australian general practices, supplied to Monash University
by IQVIA. External validation used the ASPirin in Reducing Events in the Elderly (ASPREE) trial of older adults in
Australia and the United States.

**Participants.** Primary care: adults aged 18 to 100 years with an eGFR of 30 to 120 {UNIT} between 1 January 2015 and
31 March 2020, at least 2 eGFR results in the previous 2 years and at least 2 eGFR results in the following 3 years.
People with an earlier sustained eGFR decline were excluded.

- Development: 33,377 patients, index dates in 2015 and 2016 (1,013 sustained declines)
- Temporal validation: 14,812 patients, index dates from January 2017 to March 2020 (375 sustained declines)
- External validation: 12,595 ASPREE participants, index at the second annual visit (177 sustained declines)

**Outcome.** Sustained eGFR decline of 30% or greater within 3 years.

**Predictors.** Age, sex, current eGFR, mean eGFR of the previous 2 years, relative change from that mean to the
current eGFR, and recorded use of ACE inhibitors or ARBs, diuretics and 5 or more different medicines in the previous
year. A urine ACR result is not needed.

**The 5% threshold.** In temporal validation, 12.2% of patients had an estimated risk of 5% or greater; this group
included 44.0% of the patients who had a sustained decline. In ASPREE, 8.6% of participants had an estimated risk of
5% or greater, including 42.4% of those who had a sustained decline. In ASPREE, mean estimated risk was higher than
the observed risk (2.12% vs 1.41%).

Publication details will be added when available.
"""
    )
    footer()


st.set_page_config(page_icon=":material/clinical_notes:", layout="centered", initial_sidebar_state="collapsed")
CALCULATOR = st.Page(calculator_page, title="RIDE — Risk Index for Decline in eGFR", url_path="calculator",
                     default=True)
ABOUT = st.Page(about_page, title="About RIDE", url_path="about")
STUDY = st.Page(study_page, title="Study — RIDE", url_path="study")
current_page = st.navigation([CALCULATOR, ABOUT, STUDY], position="hidden")
keep_inputs()
st.html(STYLE)
current_page.run()
