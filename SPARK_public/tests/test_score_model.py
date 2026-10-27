"""Tests for the PRIORE scoring engine.

Run from the repository root:  python -m unittest discover -s SPARK_public/tests -v

reference_cases.json holds raw inputs with values computed independently from the
frozen production pipeline and the development code (see README).
"""

import datetime
import json
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import score_model as engine  # noqa: E402

PARAMS = engine.load_parameters()
REFERENCE = json.loads((HERE / "reference_cases.json").read_text(encoding="utf-8"))
TOLERANCE = 1e-12


def run_case(case):
    rows = [(datetime.date.fromisoformat(r["date"]), r["egfr"]) for r in case["previous"]]
    return engine.estimate_risk(
        PARAMS,
        age=case["age"],
        sex=case["sex"],
        current_date=datetime.date.fromisoformat(case["index_date"]),
        current_egfr=case["index_egfr"],
        previous_rows=rows,
        acei_arb=bool(case["acei_arb"]),
        diuretic=bool(case["diuretic"]),
        polypharmacy=bool(case["polypharmacy"]),
    )


def base_inputs(**changes):
    inputs = dict(
        age=70,
        sex="F",
        current_date=datetime.date(2026, 6, 15),
        current_egfr=60,
        previous_rows=[(datetime.date(2025, 12, 1), 64), (datetime.date(2025, 6, 1), 66)],
        acei_arb=True,
        diuretic=False,
        polypharmacy=True,
    )
    inputs.update(changes)
    return inputs


class ParameterFile(unittest.TestCase):
    def test_exactly_eight_predictors(self):
        self.assertEqual([p["name"] for p in PARAMS["numeric_predictors"]], list(engine.NUMERIC_PREDICTORS))
        self.assertEqual([p["name"] for p in PARAMS["binary_predictors"]], list(engine.BINARY_PREDICTORS))
        self.assertEqual(PARAMS["sex"]["categories"], ["F", "M", "U"])
        self.assertEqual(len(PARAMS["numeric_predictors"]) + 1 + len(PARAMS["binary_predictors"]), 8)

    def test_no_count_or_slope_term(self):
        text = (HERE.parent / "model_parameters.json").read_text(encoding="utf-8")
        self.assertNotIn("n_egfr", text)
        self.assertNotIn("slope", text)

    def test_parameter_provenance(self):
        provenance = PARAMS["provenance"]
        self.assertEqual(provenance["source_parameter_file_sha256"], REFERENCE["authoritative_parameters_sha256"])
        self.assertEqual(provenance["production_pipeline_sha256"], REFERENCE["production_pipeline_sha256"])

    def test_rules_match_reference(self):
        rules = REFERENCE["rules"]
        self.assertEqual(PARAMS["egfr_history"]["lookback_days"], rules["lookback_days"])
        self.assertEqual(PARAMS["egfr_history"]["valid_range_inclusive"], rules["history_valid_range_inclusive"])
        self.assertEqual(PARAMS["egfr_history"]["minimum_days"], rules["min_history_days"])
        self.assertEqual(PARAMS["eligibility"]["current_egfr_inclusive"], rules["current_egfr_range_inclusive"])
        self.assertEqual(PARAMS["eligibility"]["age_years_inclusive"], rules["age_range_inclusive"])
        self.assertEqual(PARAMS["threshold"]["value"], rules["threshold"])


class ReferenceCases(unittest.TestCase):
    def test_calculable_cases(self):
        cases = [c for c in REFERENCE["cases"] if c["expected"]["calculable"]]
        self.assertGreaterEqual(len(cases), 30)
        for case in cases:
            with self.subTest(case=case["id"]):
                expected = case["expected"]
                estimate = run_case(case)
                self.assertLessEqual(abs(estimate.probability - expected["probability"]), TOLERANCE)
                self.assertLessEqual(abs(estimate.previous_mean - expected["previous_2y_mean_egfr"]), TOLERANCE)
                self.assertLessEqual(abs(estimate.relative_change - expected["relative_change"]), TOLERANCE)
                self.assertEqual(len(estimate.history.days_used), expected["n_previous_days_used"])
                self.assertEqual(
                    [(d.date.isoformat(), d.egfr) for d in estimate.history.days_used],
                    [(d["date"], d["daily_egfr"]) for d in expected["previous_days_used"]],
                )
                self.assertEqual(estimate.higher_priority, expected["priority"] == "higher")

    def test_not_calculable_cases(self):
        cases = [c for c in REFERENCE["cases"] if not c["expected"]["calculable"]]
        self.assertEqual(len(cases), 7)
        for case in cases:
            with self.subTest(case=case["id"]):
                with self.assertRaises(engine.OutsideIntendedUse) as raised:
                    run_case(case)
                self.assertEqual(len(raised.exception.messages), len(case["expected"]["reasons"]))

    def test_frozen_verification_cases(self):
        for case in PARAMS["verification_cases"]:
            if case["baseline_egfr_mean_preindex_2y"] is None:
                continue  # needs median imputation, which the calculator does not do
            with self.subTest(case=case["case"]):
                lp = engine.linear_predictor(
                    PARAMS,
                    age=case["age_at_index"],
                    sex=case["gender_at_index"],
                    current_egfr=case["index_egfr"],
                    previous_mean=case["baseline_egfr_mean_preindex_2y"],
                    relative_change=case["egfr_relative_change_mean_to_index_2y"],
                    acei_arb=case["acei_arb_1y"],
                    diuretic=case["diuretic_1y"],
                    polypharmacy=case["polypharmacy_5plus_1y"],
                )
                self.assertLessEqual(abs(lp - case["expected_linear_predictor"]), TOLERANCE)
                self.assertLessEqual(abs(engine.probability(lp) - case["expected_probability"]), TOLERANCE)


class Threshold(unittest.TestCase):
    def test_classification_uses_unrounded_probability(self):
        self.assertFalse(engine.is_higher_priority(0.05 - 1e-12, PARAMS))
        self.assertTrue(engine.is_higher_priority(0.05, PARAMS))
        self.assertTrue(engine.is_higher_priority(0.05 + 1e-12, PARAMS))

    def test_display_never_contradicts_priority(self):
        self.assertEqual(engine.format_risk(0.0499997568888927, PARAMS), "4.9%")
        self.assertEqual(engine.format_risk(0.0495, PARAMS), "4.9%")
        self.assertEqual(engine.format_risk(0.0494, PARAMS), "4.9%")
        self.assertEqual(engine.format_risk(0.05, PARAMS), "5.0%")
        self.assertEqual(engine.format_risk(0.0500005826660988, PARAMS), "5.0%")
        self.assertEqual(engine.format_risk(0.0849411348, PARAMS), "8.5%")
        self.assertEqual(engine.format_risk(0.0000085, PARAMS), "<0.1%")
        self.assertEqual(engine.format_risk(0.00051, PARAMS), "0.1%")
        self.assertEqual(engine.format_risk(0.9996, PARAMS), ">99.9%")
        for p in [i / 100000 for i in range(1, 100000)]:
            shown = engine.format_risk(p, PARAMS)
            if shown.startswith(("<", ">")):
                continue
            self.assertEqual(float(shown.rstrip("%")) >= 5.0, engine.is_higher_priority(p, PARAMS), p)


class Validation(unittest.TestCase):
    def assert_input_error(self, text, **changes):
        with self.assertRaises(engine.InputError) as raised:
            engine.estimate_risk(PARAMS, **base_inputs(**changes))
        self.assertTrue(any(text in m for m in raised.exception.messages), raised.exception.messages)

    def assert_outside(self, text, **changes):
        with self.assertRaises(engine.OutsideIntendedUse) as raised:
            engine.estimate_risk(PARAMS, **base_inputs(**changes))
        self.assertTrue(any(text in m for m in raised.exception.messages), raised.exception.messages)

    def test_base_case_calculates(self):
        estimate = engine.estimate_risk(PARAMS, **base_inputs())
        self.assertTrue(0 < estimate.probability < 1)

    def test_missing_values_are_never_imputed(self):
        self.assert_input_error("Enter age", age=None)
        self.assert_input_error("Select sex", sex=None)
        self.assert_input_error("date of the current eGFR", current_date=None)
        self.assert_input_error("Enter the current eGFR", current_egfr=None)
        self.assert_input_error("ACE inhibitor or ARB", acei_arb=None)
        self.assert_input_error("diuretic", diuretic=None)
        self.assert_input_error("5 or more regular medicines", polypharmacy=None)

    def test_implausible_values(self):
        self.assert_input_error("whole years", age=70.5)
        self.assert_input_error("Sex must be", sex="X")
        self.assert_input_error("Check the current eGFR", current_egfr=0)
        self.assert_input_error("Check the current eGFR", current_egfr=200.5)
        self.assert_input_error("Previous result 1", previous_rows=[(datetime.date(2025, 12, 1), 250)])
        self.assert_input_error("Previous result 2", previous_rows=[(datetime.date(2025, 12, 1), 60), (None, 61)])
        self.assert_input_error("Previous result 2", previous_rows=[(datetime.date(2025, 12, 1), 60),
                                                                  (datetime.date(2025, 6, 1), None)])

    def test_outside_intended_use_is_not_clamped(self):
        self.assert_outside("aged 18 to 100", age=17)
        self.assert_outside("aged 18 to 100", age=101)
        self.assert_outside("current eGFR of 30 to 120", current_egfr=29.9)
        self.assert_outside("current eGFR of 30 to 120", current_egfr=120.1)
        self.assert_outside("at least 2 different days", previous_rows=[(datetime.date(2025, 12, 1), 64)])

    def test_limits_are_inclusive(self):
        for changes in (dict(age=18), dict(age=100), dict(current_egfr=30), dict(current_egfr=120)):
            with self.subTest(**changes):
                engine.estimate_risk(PARAMS, **base_inputs(**changes))

    def test_blank_rows_are_ignored(self):
        rows = base_inputs()["previous_rows"] + [(None, None), (None, None)]
        a = engine.estimate_risk(PARAMS, **base_inputs())
        b = engine.estimate_risk(PARAMS, **base_inputs(previous_rows=rows))
        self.assertEqual(a.probability, b.probability)

    def test_entry_order_does_not_matter(self):
        rows = base_inputs()["previous_rows"]
        a = engine.estimate_risk(PARAMS, **base_inputs(previous_rows=rows))
        b = engine.estimate_risk(PARAMS, **base_inputs(previous_rows=list(reversed(rows))))
        self.assertEqual(a.probability, b.probability)

    def test_sex_categories(self):
        p = {s: engine.estimate_risk(PARAMS, **base_inputs(sex=s)).probability for s in ("F", "M", "U")}
        self.assertLess(p["F"], p["U"])
        self.assertLess(p["U"], p["M"])

    def test_each_medicine_increases_risk(self):
        none = engine.estimate_risk(PARAMS, **base_inputs(acei_arb=False, diuretic=False, polypharmacy=False))
        for key in ("acei_arb", "diuretic", "polypharmacy"):
            with self.subTest(key=key):
                changes = dict(acei_arb=False, diuretic=False, polypharmacy=False)
                changes[key] = True
                self.assertGreater(engine.estimate_risk(PARAMS, **base_inputs(**changes)).probability,
                                   none.probability)

    def test_probability_is_logistic(self):
        self.assertEqual(engine.probability(0.0), 0.5)
        self.assertTrue(math.isclose(engine.probability(-2.944439), 0.05, rel_tol=1e-6))


if __name__ == "__main__":
    unittest.main()
