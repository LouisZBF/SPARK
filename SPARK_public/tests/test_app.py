"""User-interface tests: the calculator page passes the entered values to the engine correctly.

Run from the repository root:  python -m unittest discover -s SPARK_public/tests -v
"""

import datetime
import html
import json
import sys
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

HERE = Path(__file__).resolve().parent
APP = HERE.parent / "app.py"
sys.path.insert(0, str(HERE.parent))

import score_model as engine  # noqa: E402

PARAMS = engine.load_parameters()
REFERENCE = json.loads((HERE / "reference_cases.json").read_text(encoding="utf-8"))
SEX_LABEL = {"F": "Female", "M": "Male", "U": "Unknown"}
TOLERANCE = 1e-12


class Recorder:
    """Wraps engine.estimate_risk to capture the unrounded estimate produced through the page."""

    def __init__(self):
        self.original = engine.estimate_risk
        self.estimates = []

    def __call__(self, *args, **kwargs):
        estimate = self.original(*args, **kwargs)
        self.estimates.append(estimate)
        return estimate


def new_app():
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    return at


def button(at, label):
    return next(b for b in at.button if b.label == label)


def page_text(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [t.value for t in at.title]
    parts += [s.value for s in at.subheader] + [e.value for e in at.error] + [w.value for w in at.warning]
    parts += [w.label for w in at.number_input] + [w.label for w in at.date_input] + [w.label for w in at.radio]
    parts += [b.label for b in at.button]
    return "\n".join(str(p) for p in parts)


def fill(at, case):
    for _ in range(len(case["previous"]) - 2):
        button(at, "Add another result").click().run()
    at.number_input(key="age").set_value(case["age"])
    at.radio(key="sex").set_value(SEX_LABEL[case["sex"]])
    at.date_input(key="current_date").set_value(datetime.date.fromisoformat(case["index_date"]))
    at.number_input(key="current_egfr").set_value(float(case["index_egfr"]))
    for i, result in enumerate(case["previous"], start=1):
        at.date_input(key=f"prev_date_{i}").set_value(datetime.date.fromisoformat(result["date"]))
        at.number_input(key=f"prev_egfr_{i}").set_value(float(result["egfr"]))
    for key in ("acei_arb", "diuretic", "polypharmacy"):
        at.radio(key=key).set_value("Yes" if case[key] else "No")
    at.button(key="calculate").click().run()


class CalculatorPage(unittest.TestCase):
    def setUp(self):
        self.recorder = Recorder()
        engine.estimate_risk = self.recorder

    def tearDown(self):
        engine.estimate_risk = self.recorder.original

    def test_page_content(self):
        at = new_app()
        self.assertFalse(at.exception)
        text = page_text(at)
        for expected in ("PRIORE", "Kidney reassessment prioritisation",
                         "Estimates the likelihood of sustained kidney function decline over the next 3 years "
                         "using information already available in the primary care record.",
                         "Age (years)", "Sex", "Current eGFR", "eGFR results from the previous 2 years",
                         "ACE inhibitor or ARB use in the previous year", "Diuretic use in the previous year",
                         "5 or more regular medicines in the previous year", "Calculate risk",
                         "PRIORE is intended to support prioritisation of kidney assessment in primary care. It does "
                         "not diagnose CKD and does not replace urine ACR testing or KFRE when these are indicated."):
            self.assertIn(expected, text)
        for forbidden in ("SPARK", "coefficient", "logit", "z-score", "feature", "AUROC", "preprocess"):
            self.assertNotIn(forbidden.lower(), text.lower())

    def test_inputs_start_empty(self):
        at = new_app()
        self.assertIsNone(at.number_input(key="age").value)
        self.assertIsNone(at.number_input(key="current_egfr").value)
        self.assertIsNone(at.date_input(key="current_date").value)
        for key in ("sex", "acei_arb", "diuretic", "polypharmacy"):
            self.assertIsNone(at.radio(key=key).value)

    def test_empty_form_lists_missing_inputs(self):
        at = new_app()
        at.button(key="calculate").click().run()
        self.assertEqual(len(at.error), 1)
        for text in ("Enter age", "Select sex", "date of the current eGFR", "Enter the current eGFR",
                     "ACE inhibitor or ARB", "diuretic use", "5 or more regular medicines"):
            self.assertIn(text, at.error[0].value)
        self.assertEqual(self.recorder.estimates, [])

    def test_reference_cases_through_the_page(self):
        for case in REFERENCE["cases"]:
            with self.subTest(case=case["id"]):
                at = new_app()
                self.recorder.estimates.clear()
                fill(at, case)
                self.assertFalse(at.exception)
                expected = case["expected"]
                if expected["calculable"]:
                    self.assertEqual(len(self.recorder.estimates), 1)
                    estimate = self.recorder.estimates[0]
                    self.assertLessEqual(abs(estimate.probability - expected["probability"]), TOLERANCE)
                    shown = "\n".join(m.value for m in at.markdown if "priore-result" in m.value)
                    self.assertIn(html.escape(engine.format_risk(expected["probability"], PARAMS)), shown)
                    label = "Higher priority" if expected["priority"] == "higher" else "Routine priority"
                    self.assertIn(f"{label} for kidney reassessment", shown)
                    self.assertIn("A 5% risk threshold was used in the study", shown)
                else:
                    self.assertEqual(self.recorder.estimates, [])
                    self.assertEqual(len(at.warning), 1)
                    self.assertIn("No estimate was calculated", at.warning[0].value)

    def test_result_is_hidden_when_an_input_changes(self):
        case = next(c for c in REFERENCE["cases"] if c["id"] == "R12")
        at = new_app()
        fill(at, case)
        self.assertTrue(any("priore-result" in m.value for m in at.markdown))
        at.number_input(key="age").set_value(case["age"] + 1).run()
        self.assertFalse(any("priore-result" in m.value for m in at.markdown))

    def test_rows_can_be_added_and_removed(self):
        at = new_app()
        self.assertEqual(len([w for w in at.date_input if w.key.startswith("prev_date_")]), 2)
        button(at, "Add another result").click().run()
        self.assertEqual(len([w for w in at.date_input if w.key.startswith("prev_date_")]), 3)
        button(at, "Remove last result").click().run()
        self.assertEqual(len([w for w in at.date_input if w.key.startswith("prev_date_")]), 2)


if __name__ == "__main__":
    unittest.main()
