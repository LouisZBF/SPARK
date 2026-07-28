"""Scoring utilities for the ACR-free monitoring-priority calculator.

The model parameters are loaded from the locked JSON export. This module does
not read manuscript or supplement files.
"""

from __future__ import annotations

import datetime
import json
import math
from pathlib import Path
from typing import Any, Mapping


PARAMETER_PATH = Path(__file__).with_name("model_parameters.json")

NUMERIC_INPUTS = (
    "age_at_index",
    "index_egfr",
    "baseline_egfr_mean_preindex_2y",
    "n_egfr_preindex_2y",
    "egfr_relative_change_mean_to_index_2y",
    "egfr_slope_2y",
)

BINARY_INPUTS = (
    "acei_arb_1y",
    "diuretic_1y",
    "polypharmacy_5plus_1y",
)

REQUIRED_INPUTS = NUMERIC_INPUTS + ("gender_at_index",) + BINARY_INPUTS

# The locked model_parameters.json defines five detailed risk bands. The
# calculator intentionally displays four bands by merging the two intermediate
# sub-bands (5% to <7.5% and 7.5% to <10%) into a single 5% to <10% band. These
# four display bands are validated against the JSON definitions by
# derive_display_bands_from_json(); see calculator_audit_fix_report.md.
RISK_BANDS = (
    ("<2.5%", 0.0, 0.025),
    ("2.5% to <5%", 0.025, 0.05),
    ("5% to <10%", 0.05, 0.10),
    ("≥10%", 0.10, None),
)

# JSON sub-bands that the calculator merges into a single displayed band.
_MERGED_DISPLAY_LABEL = "5% to <10%"
_MERGED_JSON_SOURCE_LABELS = ("5% to <7.5%", "7.5% to <10%")
# JSON labels mapped 1:1 to display labels (JSON uses ">=10%" for the top band).
_DISPLAY_LABEL_BY_JSON_LABEL = {
    "<2.5%": "<2.5%",
    "2.5% to <5%": "2.5% to <5%",
    ">=10%": "≥10%",
}

# Fallback default if model_parameters.json omits the threshold; the JSON value
# is preferred via get_monitoring_threshold().
MONITORING_PRIORITY_THRESHOLD = 0.05

# --- Raw eGFR-test input mode -----------------------------------------------
#
# These helpers support the user-friendly "eGFR-test input" mode. They derive
# the model-ready eGFR-history predictors from a current/index eGFR and a list
# of previous eGFR measurements. They do NOT change any scoring logic,
# coefficients, scaling, encoding, or the prediction formula; they only build
# inputs that are then fed to the existing scorer.

# 2-year (730-day) pre-index lookback window.
EGFR_LOOKBACK_DAYS = 730

# Model-valid eGFR range (inclusive). This matches the locked development
# pipeline, which restricts pre-index lookback eGFR to 30-120 before computing
# baseline/history features and requires a valid index eGFR in the same range.
# Out-of-range values are excluded (previous) or block scoring (index); they are
# never silently clipped.
EGFR_MIN_VALID = 30.0
EGFR_MAX_VALID = 120.0

INDEX_OUT_OF_RANGE_MESSAGE = (
    "Current/index eGFR is outside the model-valid range of 30 to 120 "
    "mL/min/1.73 m²."
)

INSUFFICIENT_HISTORY_MESSAGE = (
    "Insufficient pre-index eGFR history. This calculator requires a "
    "current/index eGFR and at least two previous eGFR measurements within the "
    "prior 2 years."
)

# Maps the derived eGFR-history feature names returned by
# calculate_egfr_history_features() to the model-ready feature names the scorer
# expects. The scorer's feature names are unchanged.
EGFR_HISTORY_TO_MODEL_FEATURE = {
    "index_egfr": "index_egfr",
    "egfr_mean_2y": "baseline_egfr_mean_preindex_2y",
    "egfr_count_2y": "n_egfr_preindex_2y",
    "egfr_relative_change_2y": "egfr_relative_change_mean_to_index_2y",
    "egfr_slope_2y": "egfr_slope_2y",
}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    try:
        return bool(math.isnan(value))
    except (TypeError, ValueError):
        return False


def load_parameters(path: str | Path = "model_parameters.json") -> dict[str, Any]:
    """Load and validate the locked model parameter JSON."""
    parameter_path = Path(path)
    if not parameter_path.is_absolute():
        parameter_path = Path(__file__).with_name(str(parameter_path))

    with parameter_path.open("r", encoding="utf-8") as handle:
        params = json.load(handle)

    _validate_parameter_file(params)
    return params


def _validate_parameter_file(params: Mapping[str, Any]) -> None:
    required_top_level = {
        "intercept",
        "feature_order",
        "coefficients",
        "numeric_predictors",
        "categorical_predictors",
        "binary_predictors",
        "monitoring_priority_threshold_5_percent",
    }
    missing = sorted(required_top_level.difference(params))
    if missing:
        raise ValueError(f"Missing top-level parameter fields: {', '.join(missing)}")

    feature_order = params["feature_order"]
    coefficients = params["coefficients"]
    missing_coefficients = [name for name in feature_order if name not in coefficients]
    if missing_coefficients:
        raise ValueError(
            "Missing coefficients for feature(s): " + ", ".join(missing_coefficients)
        )

    for name in NUMERIC_INPUTS:
        if name not in params["numeric_predictors"]:
            raise ValueError(f"Missing numeric preprocessing parameters for {name}")
        numeric = params["numeric_predictors"][name]
        for key in ("imputation_median", "scaling_mean", "scaling_sd"):
            if key not in numeric:
                raise ValueError(f"Missing {key} for numeric predictor {name}")
            if not isinstance(numeric[key], (int, float)):
                raise ValueError(f"{key} for {name} must be numeric")
        if numeric["scaling_sd"] == 0:
            raise ValueError(f"Scaling SD for {name} must be non-zero")

    categorical = params["categorical_predictors"].get("gender_at_index")
    if not categorical:
        raise ValueError("Missing categorical encoding parameters for gender_at_index")
    for dummy in ("gender_at_index_M", "gender_at_index_U"):
        if dummy not in coefficients:
            raise ValueError(f"Missing sex dummy coefficient {dummy}")
        if dummy not in categorical.get("encoding_rules", {}):
            raise ValueError(f"Missing sex encoding rule for {dummy}")

    for name in BINARY_INPUTS:
        if name not in params["binary_predictors"]:
            raise ValueError(f"Missing binary predictor rule for {name}")
        if name not in coefficients:
            raise ValueError(f"Missing binary coefficient for {name}")


def validate_inputs(input_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Validate calculator inputs and return a normalized copy."""
    missing_required = [
        name for name in REQUIRED_INPUTS if name not in input_dict and name not in NUMERIC_INPUTS
    ]
    if missing_required:
        raise ValueError("Missing required input(s): " + ", ".join(missing_required))

    normalized: dict[str, Any] = {}
    for name in NUMERIC_INPUTS:
        value = input_dict.get(name)
        if _is_missing(value):
            normalized[name] = None
        else:
            try:
                normalized[name] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be numeric or missing") from exc

    sex = input_dict.get("gender_at_index", input_dict.get("sex"))
    normalized["gender_at_index"] = _normalize_sex(sex)

    for name in BINARY_INPUTS:
        normalized[name] = _normalize_binary(input_dict.get(name), name)

    return normalized


def _normalize_sex(value: Any) -> str:
    if _is_missing(value):
        raise ValueError("gender_at_index is required; choose F, M, or U")

    text = str(value).strip().upper()
    aliases = {
        "F": "F",
        "FEMALE": "F",
        "M": "M",
        "MALE": "M",
        "U": "U",
        "UNKNOWN": "U",
        "UNSPECIFIED": "U",
        "UNKNOWN/UNSPECIFIED": "U",
    }
    if text not in aliases:
        raise ValueError("gender_at_index must be F, M, or U")
    return aliases[text]


def _encode_sex_dummies(sex: str, params: Mapping[str, Any]) -> dict[str, float]:
    """Encode sex into dummy columns using the JSON categorical encoding rules.

    The reference category (F) sets every dummy to 0. Each non-reference dummy
    column is set to 1.0 only when the input sex equals the ``category`` declared
    for that column in ``model_parameters.json``. No category mapping is
    hard-coded here; it is read entirely from the locked parameter file.
    """
    gender_params = params["categorical_predictors"]["gender_at_index"]
    encoding_rules = gender_params["encoding_rules"]
    dummies: dict[str, float] = {}
    for dummy_column, rule in encoding_rules.items():
        category = rule["category"]
        dummies[dummy_column] = 1.0 if sex == category else 0.0
    return dummies


def _normalize_binary(value: Any, name: str) -> int:
    if _is_missing(value):
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and value in (0, 1):
        return int(value)
    text = str(value).strip().lower()
    if text in {"yes", "y", "true", "1"}:
        return 1
    if text in {"no", "n", "false", "0"}:
        return 0
    raise ValueError(f"{name} must be encoded as yes/no or 0/1")


def preprocess_inputs(
    input_dict: Mapping[str, Any], params: Mapping[str, Any]
) -> dict[str, float]:
    """Apply imputation, scaling, sex dummy encoding, and binary handling."""
    validated = validate_inputs(input_dict)
    processed: dict[str, float] = {}

    for name in NUMERIC_INPUTS:
        numeric_params = params["numeric_predictors"][name]
        value = validated[name]
        if value is None:
            value = numeric_params["imputation_median"]
        processed[name] = (
            (float(value) - float(numeric_params["scaling_mean"]))
            / float(numeric_params["scaling_sd"])
        )

    sex = validated["gender_at_index"]
    processed.update(_encode_sex_dummies(sex, params))

    for name in BINARY_INPUTS:
        processed[name] = float(validated[name])

    return processed


def predict_risk(input_dict: Mapping[str, Any], params: Mapping[str, Any]) -> float:
    """Predict 3-year risk from already derived predictor values."""
    processed = preprocess_inputs(input_dict, params)
    logit = float(params["intercept"])
    for feature in params["feature_order"]:
        logit += float(params["coefficients"][feature]) * processed[feature]
    return 1.0 / (1.0 + math.exp(-logit))


def get_monitoring_threshold(params: Mapping[str, Any]) -> float:
    """Return the >=5% monitoring-priority threshold, preferring the JSON value."""
    value = params.get("monitoring_priority_threshold_5_percent")
    if value is None:
        return MONITORING_PRIORITY_THRESHOLD
    return float(value)


def derive_display_bands_from_json(
    params: Mapping[str, Any],
) -> tuple[tuple[str, float, float | None], ...]:
    """Derive the four calculator display bands from the JSON risk-band definitions.

    The locked JSON defines five bands. The calculator intentionally merges the
    two intermediate sub-bands (5% to <7.5% and 7.5% to <10%) into a single
    displayed ``5% to <10%`` band. All numeric boundaries are taken from JSON, so
    the displayed bands stay consistent with model_parameters.json.
    """
    json_bands = {band["label"]: band for band in params["risk_bands"]}

    def bounds(label: str) -> tuple[float, float | None]:
        band = json_bands[label]
        return band["lower_bound_inclusive"], band["upper_bound_exclusive"]

    low_label, high_label = _MERGED_JSON_SOURCE_LABELS
    merged_lower, _ = bounds(low_label)
    _, merged_upper = bounds(high_label)

    display_bands: list[tuple[str, float, float | None]] = []
    for json_label, band in json_bands.items():
        if json_label in _MERGED_JSON_SOURCE_LABELS:
            continue
        if json_label not in _DISPLAY_LABEL_BY_JSON_LABEL:
            raise ValueError(f"Unexpected JSON risk-band label: {json_label}")
        display_label = _DISPLAY_LABEL_BY_JSON_LABEL[json_label]
        lower, upper = bounds(json_label)
        display_bands.append((display_label, lower, upper))

    display_bands.append((_MERGED_DISPLAY_LABEL, merged_lower, merged_upper))
    display_bands.sort(key=lambda item: item[1])
    return tuple(display_bands)


def assign_risk_band(
    risk: float,
    bands: tuple[tuple[str, float, float | None], ...] = RISK_BANDS,
) -> str:
    """Assign the four calculator risk bands requested for reporting.

    ``bands`` defaults to the module display bands; pass
    ``derive_display_bands_from_json(params)`` to bind boundaries to the JSON.
    """
    if risk < 0 or risk > 1:
        raise ValueError("risk must be between 0 and 1")
    for label, lower, upper in bands:
        if risk >= lower and (upper is None or risk < upper):
            return label
    raise ValueError("risk could not be assigned to a risk band")


def explain_result(risk: float, threshold: float = MONITORING_PRIORITY_THRESHOLD) -> str:
    """Return conservative research-use interpretation text."""
    band = assign_risk_band(risk)
    if risk >= threshold:
        return (
            f"Predicted risk falls in the {band} band and meets the ≥5% "
            "monitoring-priority threshold. May support consideration of earlier "
            "repeat eGFR testing, ACR completion if absent, medication review, or "
            "closer follow-up according to local clinical judgement."
        )
    return (
        f"Predicted risk falls in the {band} band and does not meet the ≥5% "
        "monitoring-priority threshold. Interpret in context of local clinical "
        "judgement and the research-use limitations of this calculator."
    )


def _parse_date(value: Any) -> datetime.date:
    """Parse a date-like value or date string into a datetime.date."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return datetime.date.fromisoformat(text)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    raise ValueError(f"Could not parse date value: {value!r}")


def _normalize_egfr_record(record: Any) -> tuple[datetime.date, float] | None:
    """Normalize one previous eGFR record into (date, egfr) or None if blank.

    Accepts a mapping with ``date`` and ``egfr`` (or ``value``) keys, or a
    two-item (date, egfr) sequence. Fully blank records return None so callers
    can pass fixed-size tables with empty rows. Partially blank or malformed
    records raise a clear ValueError.
    """
    if record is None:
        return None
    if isinstance(record, Mapping):
        date_val = record.get("date")
        egfr_val = record.get("egfr", record.get("value"))
    elif isinstance(record, (list, tuple)) and len(record) == 2:
        date_val, egfr_val = record
    else:
        raise ValueError(
            "Each previous eGFR record must provide a date and an eGFR value."
        )

    date_blank = _is_missing(date_val)
    egfr_blank = _is_missing(egfr_val)
    if date_blank and egfr_blank:
        return None
    if date_blank or egfr_blank:
        raise ValueError(
            "Each previous eGFR record must include both a valid date and a "
            "numeric eGFR value."
        )

    record_date = _parse_date(date_val)
    try:
        record_egfr = float(egfr_val)
    except (TypeError, ValueError) as exc:
        raise ValueError("Previous eGFR values must be numeric.") from exc
    if math.isnan(record_egfr):
        raise ValueError("Previous eGFR values must be numeric.")
    return record_date, record_egfr


def validate_egfr_records(
    index_date: Any,
    index_egfr: Any,
    previous_egfr_records: Any,
) -> dict[str, Any]:
    """Validate raw eGFR-test inputs and return cleaned valid records.

    Returns a dict with the parsed ``index_date`` and ``index_egfr``, the sorted
    list of valid ``previous_records`` (each a ``(date, egfr)`` tuple), and a
    list of human-readable ``warnings`` about excluded or out-of-range records.

    A valid previous record is strictly before the index date, within the prior
    730 days, and has an eGFR value within the model-valid range (30-120
    inclusive). Out-of-range previous records are excluded (matching the locked
    pipeline) with a warning, not clipped. The index eGFR is never treated as a
    previous record. Raises ValueError for an invalid index date/value, an index
    eGFR outside the model-valid range, or when fewer than two valid previous
    records remain.
    """
    warnings: list[str] = []

    index_date_parsed = _parse_date(index_date)

    if _is_missing(index_egfr):
        raise ValueError("index_egfr must be numeric.")
    try:
        index_egfr_value = float(index_egfr)
    except (TypeError, ValueError) as exc:
        raise ValueError("index_egfr must be numeric.") from exc
    if math.isnan(index_egfr_value):
        raise ValueError("index_egfr must be numeric.")

    # The locked pipeline requires a valid index eGFR in 30-120; do not clip.
    if not (EGFR_MIN_VALID <= index_egfr_value <= EGFR_MAX_VALID):
        raise ValueError(INDEX_OUT_OF_RANGE_MESSAGE)

    records = previous_egfr_records or []
    valid: list[tuple[datetime.date, float]] = []
    for record in records:
        normalized = _normalize_egfr_record(record)
        if normalized is None:
            continue
        record_date, record_egfr = normalized

        if record_date >= index_date_parsed:
            warnings.append(
                f"Excluded a previous eGFR record dated {record_date.isoformat()} "
                f"because it is on or after the index date "
                f"{index_date_parsed.isoformat()}."
            )
            continue

        days_before = (index_date_parsed - record_date).days
        if days_before > EGFR_LOOKBACK_DAYS:
            warnings.append(
                f"Excluded a previous eGFR record dated {record_date.isoformat()} "
                f"because it is more than {EGFR_LOOKBACK_DAYS} days "
                f"({days_before} days) before the index date."
            )
            continue

        # Out-of-range previous values are excluded from baseline/history
        # features (matching the locked pipeline), not silently clipped.
        if not (EGFR_MIN_VALID <= record_egfr <= EGFR_MAX_VALID):
            warnings.append(
                f"Excluded a previous eGFR record dated {record_date.isoformat()} "
                f"({record_egfr:g} mL/min/1.73 m²) because it is outside the "
                f"model-valid range of {EGFR_MIN_VALID:g} to {EGFR_MAX_VALID:g} "
                f"mL/min/1.73 m²."
            )
            continue

        valid.append((record_date, record_egfr))

    if len(valid) < 2:
        raise ValueError(INSUFFICIENT_HISTORY_MESSAGE)

    valid.sort(key=lambda item: item[0])

    # Deduplicate warnings while preserving order.
    seen: set[str] = set()
    deduped = [w for w in warnings if not (w in seen or seen.add(w))]

    return {
        "index_date": index_date_parsed,
        "index_egfr": index_egfr_value,
        "previous_records": valid,
        "warnings": deduped,
    }


def _ols_slope(xs: list[float], ys: list[float]) -> float:
    """Ordinary least squares slope of ys on xs (annualised when xs are years).

    For exactly two points this reduces to (y2 - y1) / (x2 - x1).
    """
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        raise ValueError(
            "Cannot compute an eGFR slope because all previous eGFR records "
            "share the same date."
        )
    return numerator / denominator


def calculate_egfr_history_features(
    index_date: Any,
    index_egfr: Any,
    previous_egfr_records: Any,
) -> tuple[dict[str, float], list[str]]:
    """Derive model-ready eGFR-history features from raw eGFR-test inputs.

    Returns ``(features, warnings)`` where ``features`` contains exactly:
    ``index_egfr``, ``egfr_mean_2y``, ``egfr_count_2y``,
    ``egfr_relative_change_2y``, and ``egfr_slope_2y``. Age, sex, and medication
    flags are intentionally not created here.

    The index/current eGFR is never included in the pre-index mean, count, or
    slope. Time for the slope is coded in years as
    ``(record_date - index_date) / 365.25`` (negative = before the index date);
    the slope is the OLS slope of eGFR on this time, annualised in
    mL/min/1.73 m² per year.
    """
    validated = validate_egfr_records(index_date, index_egfr, previous_egfr_records)
    index_date_parsed = validated["index_date"]
    index_egfr_value = validated["index_egfr"]
    previous_records = validated["previous_records"]

    egfr_values = [egfr for _, egfr in previous_records]
    count = len(previous_records)
    mean = sum(egfr_values) / count
    relative_change = (index_egfr_value - mean) / mean

    years = [
        (record_date - index_date_parsed).days / 365.25
        for record_date, _ in previous_records
    ]
    slope = _ols_slope(years, egfr_values)

    features = {
        "index_egfr": index_egfr_value,
        "egfr_mean_2y": mean,
        "egfr_count_2y": float(count),
        "egfr_relative_change_2y": relative_change,
        "egfr_slope_2y": slope,
    }
    return features, validated["warnings"]


def egfr_history_to_model_inputs(features: Mapping[str, float]) -> dict[str, float]:
    """Map derived eGFR-history feature names to the scorer's model-ready names."""
    return {
        EGFR_HISTORY_TO_MODEL_FEATURE[name]: value
        for name, value in features.items()
        if name in EGFR_HISTORY_TO_MODEL_FEATURE
    }


if __name__ == "__main__":
    params = load_parameters()
    example = {
        "age_at_index": 71,
        "gender_at_index": "F",
        "index_egfr": 73,
        "baseline_egfr_mean_preindex_2y": 73.66666666666667,
        "n_egfr_preindex_2y": 2,
        "egfr_relative_change_mean_to_index_2y": 0,
        "egfr_slope_2y": 0,
        "acei_arb_1y": 0,
        "diuretic_1y": 0,
        "polypharmacy_5plus_1y": 0,
    }
    risk = predict_risk(example, params)
    print(f"Predicted risk: {risk:.6f}")
    print(f"Risk band: {assign_risk_band(risk)}")
    print(explain_result(risk))
