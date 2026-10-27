"""PRIORE scoring engine.

Reproduces the locked final PRIORE model exactly from the frozen parameters in
model_parameters.json. Nothing is fitted, recalibrated or imputed here.

The eGFR-history inputs are derived with the rules of the development code:

* previous eGFR results recorded on the same calendar day are averaged into one
  daily value;
* a daily value is used when its date is within the 730 days before the current
  eGFR (the current eGFR date itself is excluded) and the value is 30 to 120
  mL/min/1.73 m2 inclusive;
* at least 2 days must be used; the previous 2-year mean is the mean of the
  daily values used, and the relative change is
  (current eGFR - previous mean) / previous mean.

The model was developed for adults aged 18 to 100 years with a current eGFR of
30 to 120 mL/min/1.73 m2. Outside these limits no estimate is returned; values
are never clamped.
"""

from __future__ import annotations

import datetime
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple

PARAMETER_PATH = Path(__file__).with_name("model_parameters.json")

NUMERIC_PREDICTORS = (
    "age_at_index",
    "index_egfr",
    "baseline_egfr_mean_preindex_2y",
    "egfr_relative_change_mean_to_index_2y",
)
BINARY_PREDICTORS = ("acei_arb_1y", "diuretic_1y", "polypharmacy_5plus_1y")
SEX_CODES = ("F", "M", "U")

EGFR_UNIT = "mL/min/1.73 m²"


class InputError(ValueError):
    """One or more inputs are missing or not plausible. Messages are shown to the user."""

    def __init__(self, messages: Sequence[str]):
        self.messages = list(messages)
        super().__init__(" ".join(self.messages))


class OutsideIntendedUse(ValueError):
    """The inputs are valid but outside the population PRIORE was developed for."""

    def __init__(self, messages: Sequence[str], history: Optional["EgfrHistory"] = None):
        self.messages = list(messages)
        self.history = history
        super().__init__(" ".join(self.messages))


@dataclass(frozen=True)
class PreviousResult:
    date: datetime.date
    egfr: float


@dataclass(frozen=True)
class DayValue:
    date: datetime.date
    egfr: float  # average of the results recorded on this day
    n_results: int


@dataclass(frozen=True)
class NotUsed:
    date: datetime.date
    egfr: float  # daily average
    n_results: int
    reason: str


@dataclass(frozen=True)
class EgfrHistory:
    days_used: Tuple[DayValue, ...]
    not_used: Tuple[NotUsed, ...]


@dataclass(frozen=True)
class Estimate:
    probability: float
    higher_priority: bool
    previous_mean: float
    relative_change: float
    history: EgfrHistory


def load_parameters(path: Path = PARAMETER_PATH) -> dict:
    """Load and check the frozen parameter file."""
    with Path(path).open("r", encoding="utf-8") as handle:
        params = json.load(handle)
    numeric = [p["name"] for p in params["numeric_predictors"]]
    binary = [p["name"] for p in params["binary_predictors"]]
    if tuple(numeric) != NUMERIC_PREDICTORS or tuple(binary) != BINARY_PREDICTORS:
        raise RuntimeError("model_parameters.json does not list the PRIORE predictors in the expected order")
    if tuple(params["sex"]["categories"]) != SEX_CODES or params["sex"]["reference"] != "F":
        raise RuntimeError("model_parameters.json has an unexpected sex coding")
    for p in params["numeric_predictors"]:
        if not p["scaling_sd"] > 0:
            raise RuntimeError(f"Scaling SD for {p['name']} must be positive")
    return params


def _number(value: Any) -> Optional[float]:
    """Return value as a float, or None when it is blank or not a finite number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _plausible(value: float, params: Mapping[str, Any]) -> bool:
    limits = params["eligibility"]["plausible_egfr_result"]
    return limits["greater_than"] < value <= limits["at_most"]


def _plausible_text(params: Mapping[str, Any]) -> str:
    limits = params["eligibility"]["plausible_egfr_result"]
    return f"above {limits['greater_than']:g} and no more than {limits['at_most']:g} {EGFR_UNIT}"


def parse_previous_results(
    rows: Sequence[Tuple[Optional[datetime.date], Any]], params: Mapping[str, Any]
) -> Tuple[List[PreviousResult], List[str]]:
    """Turn entered (date, eGFR) rows into results. Fully blank rows are ignored."""
    results: List[PreviousResult] = []
    errors: List[str] = []
    for number, (date, raw_value) in enumerate(rows, start=1):
        value = _number(raw_value)
        if date is None and raw_value is None:
            continue
        if date is None or value is None:
            errors.append(f"Previous result {number}: enter both the date and the eGFR.")
            continue
        if not _plausible(value, params):
            errors.append(f"Previous result {number}: check the eGFR. Results must be {_plausible_text(params)}.")
            continue
        results.append(PreviousResult(date=date, egfr=value))
    return results, errors


def summarise_egfr_history(
    current_date: datetime.date, previous: Sequence[PreviousResult], params: Mapping[str, Any]
) -> EgfrHistory:
    """Apply the development rules: same-day averaging, then the 730-day window and the 30-120 range."""
    rules = params["egfr_history"]
    lookback_start = current_date - datetime.timedelta(days=rules["lookback_days"])
    low, high = rules["valid_range_inclusive"]

    by_day: dict = {}
    for result in previous:
        by_day.setdefault(result.date, []).append(result.egfr)

    used: List[DayValue] = []
    not_used: List[NotUsed] = []
    for day in sorted(by_day):
        values = by_day[day]
        daily = math.fsum(values) / len(values)
        if day >= current_date:
            reason = "dated on or after the current eGFR"
        elif day < lookback_start:
            reason = f"more than {rules['lookback_days']} days before the current eGFR"
        elif not (low <= daily <= high):
            reason = f"outside {low:g} to {high:g} {EGFR_UNIT}"
        else:
            used.append(DayValue(date=day, egfr=daily, n_results=len(values)))
            continue
        not_used.append(NotUsed(date=day, egfr=daily, n_results=len(values), reason=reason))
    return EgfrHistory(days_used=tuple(used), not_used=tuple(not_used))


def linear_predictor(
    params: Mapping[str, Any],
    *,
    age: float,
    sex: str,
    current_egfr: float,
    previous_mean: float,
    relative_change: float,
    acei_arb: int,
    diuretic: int,
    polypharmacy: int,
) -> float:
    values = {
        "age_at_index": age,
        "index_egfr": current_egfr,
        "baseline_egfr_mean_preindex_2y": previous_mean,
        "egfr_relative_change_mean_to_index_2y": relative_change,
    }
    flags = {"acei_arb_1y": acei_arb, "diuretic_1y": diuretic, "polypharmacy_5plus_1y": polypharmacy}
    lp = params["intercept"]
    for p in params["numeric_predictors"]:
        lp += p["coefficient"] * (values[p["name"]] - p["scaling_mean"]) / p["scaling_sd"]
    for code in ("M", "U"):
        lp += params["sex"]["coefficients"][code] * (1 if sex == code else 0)
    for p in params["binary_predictors"]:
        lp += p["coefficient"] * flags[p["name"]]
    return lp


def probability(lp: float) -> float:
    return 1.0 / (1.0 + math.exp(-lp))


def is_higher_priority(p: float, params: Mapping[str, Any]) -> bool:
    """Classification uses the unrounded probability."""
    return p >= params["threshold"]["value"]


def format_risk(p: float, params: Mapping[str, Any]) -> str:
    """Percentage to one decimal place, never contradicting the priority category.

    A value just below the threshold that would round up to it (for example
    4.96%) is shown as 4.9%.
    """
    threshold_percent = params["threshold"]["value"] * 100
    percent = p * 100
    if percent < 0.05:
        return "<0.1%"
    shown = float(f"{percent:.1f}")
    if not is_higher_priority(p, params) and shown >= threshold_percent:
        shown = math.floor(threshold_percent * 10 - 1) / 10
    if shown >= 100.0:
        return ">99.9%"
    return f"{shown:.1f}%"


def estimate_risk(
    params: Mapping[str, Any],
    *,
    age: Any,
    sex: Optional[str],
    current_date: Optional[datetime.date],
    current_egfr: Any,
    previous_rows: Sequence[Tuple[Optional[datetime.date], Any]],
    acei_arb: Optional[bool],
    diuretic: Optional[bool],
    polypharmacy: Optional[bool],
) -> Estimate:
    """Validate the entered values, derive the eGFR-history inputs and return the estimate.

    Raises InputError for missing or implausible entries and OutsideIntendedUse
    when the person is outside the population PRIORE was developed for.
    """
    errors: List[str] = []

    age_value = _number(age)
    if age_value is None:
        errors.append("Enter age in years.")
    elif age_value != int(age_value):
        errors.append("Enter age in whole years.")

    if sex is None:
        errors.append("Select sex.")
    elif sex not in SEX_CODES:
        errors.append("Sex must be female, male or unknown.")

    if current_date is None:
        errors.append("Enter the date of the current eGFR.")
    egfr_value = _number(current_egfr)
    if egfr_value is None:
        errors.append("Enter the current eGFR.")
    elif not _plausible(egfr_value, params):
        errors.append(f"Check the current eGFR. Results must be {_plausible_text(params)}.")

    previous, row_errors = parse_previous_results(previous_rows, params)
    errors.extend(row_errors)

    answers = {
        "ACE inhibitor or ARB use": acei_arb,
        "diuretic use": diuretic,
        "5 or more regular medicines": polypharmacy,
    }
    for question, answer in answers.items():
        if answer is None:
            errors.append(f"Answer the question on {question} in the previous year.")

    if errors:
        raise InputError(errors)

    eligibility = params["eligibility"]
    age_low, age_high = eligibility["age_years_inclusive"]
    egfr_low, egfr_high = eligibility["current_egfr_inclusive"]
    rules = params["egfr_history"]
    history = summarise_egfr_history(current_date, previous, params)

    outside: List[str] = []
    if not (age_low <= age_value <= age_high):
        outside.append(f"PRIORE was developed for adults aged {age_low} to {age_high} years.")
    if not (egfr_low <= egfr_value <= egfr_high):
        outside.append(
            f"PRIORE was developed for people with a current eGFR of {egfr_low:g} to {egfr_high:g} {EGFR_UNIT}."
        )
    if len(history.days_used) < rules["minimum_days"]:
        low, high = rules["valid_range_inclusive"]
        outside.append(
            f"PRIORE needs eGFR results from at least {rules['minimum_days']} different days in the "
            f"{rules['lookback_days']} days before the current eGFR, each between {low:g} and {high:g} "
            f"{EGFR_UNIT}. Results usable here: {len(history.days_used)} day(s)."
        )
    if outside:
        raise OutsideIntendedUse(outside, history)

    previous_mean = math.fsum(day.egfr for day in history.days_used) / len(history.days_used)
    relative_change = (egfr_value - previous_mean) / previous_mean
    lp = linear_predictor(
        params,
        age=float(age_value),
        sex=sex,
        current_egfr=egfr_value,
        previous_mean=previous_mean,
        relative_change=relative_change,
        acei_arb=int(bool(acei_arb)),
        diuretic=int(bool(diuretic)),
        polypharmacy=int(bool(polypharmacy)),
    )
    p = probability(lp)
    return Estimate(
        probability=p,
        higher_priority=is_higher_priority(p, params),
        previous_mean=previous_mean,
        relative_change=relative_change,
        history=history,
    )
