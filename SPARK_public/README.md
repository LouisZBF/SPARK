# PRIORE

**Kidney reassessment prioritisation**

PRIORE estimates the likelihood of sustained kidney function decline over the next 3 years using information
already available in the primary care record.

PRIORE is intended to support prioritisation of kidney assessment in primary care. It does not diagnose CKD and
does not replace urine ACR testing or KFRE when these are indicated.

- Web calculator: <https://spark-kidney-decline.streamlit.app>
- Project website: <https://louiszbf.github.io>

## Inputs

| Input | Notes |
| --- | --- |
| Age | Whole years, 18 to 100 |
| Sex | Female, male or unknown (unknown or unrecorded sex is scored as unknown) |
| Current eGFR and its date | mL/min/1.73 m², 30 to 120 |
| eGFR results from the previous 2 years | Every result in the 730 days before the current eGFR, with dates; results from at least 2 different days are needed |
| ACE inhibitor or ARB use in the previous year | Yes / No |
| Diuretic use in the previous year | Yes / No |
| 5 or more regular medicines in the previous year | Yes / No |

Every input is required. Missing values are never imputed, and values outside the limits above are never
clamped: the calculator explains why no estimate can be given.

Enter results reported as ">90" as 90 (this is how such results were recorded in the study data). If more than
one eGFR was recorded on the day of the current eGFR, enter their average.

## Output

- **Estimated 3-year risk** of sustained eGFR decline of 30% or more: a first eGFR at or below 70% of the
  average of the previous 2 years, confirmed by a second result at least 90 days later, with no recovery in
  between.
- **Higher priority for kidney reassessment** when the estimate is 5% or more; otherwise **Routine priority for
  kidney reassessment**. The 5% threshold was used in the study to prioritise repeat eGFR and urine ACR
  assessment. The classification uses the unrounded estimate.
- The estimate is shown to one decimal place. A value just below 5% that would round up to 5.0% is shown as
  4.9%, so the number never contradicts the priority shown.

## How the estimate is calculated

The calculator reproduces the locked final model exactly. Nothing is refitted, recalibrated or imputed.

1. **Previous eGFR results.** Results recorded on the same calendar day are averaged into one daily value. A daily
   value is used when its date is within the 730 days before the current eGFR (the current eGFR date itself is
   excluded) and the value is 30 to 120 mL/min/1.73 m² inclusive. At least 2 days must be used. Results must be
   above 0 and no more than 200 mL/min/1.73 m².
2. **Derived values.** Previous 2-year mean = mean of the daily values used. Relative change =
   (current eGFR − previous mean) / previous mean, as a proportion.
3. **Model.** L2-penalised (ridge) logistic regression with 8 predictors: age, sex (female reference; male;
   unknown), current eGFR, previous 2-year mean eGFR, relative change, ACE inhibitor or ARB use, diuretic use and
   5 or more medicines.

   ```text
   lp = intercept
        + sum over age, current eGFR, previous mean, relative change of coefficient * (value - mean) / SD
        + coefficient_male * [male] + coefficient_unknown * [unknown]
        + sum over the 3 medicine questions of coefficient * [yes]
   risk = 1 / (1 + exp(-lp))
   ```

   The means and SDs (population SD) are those of the development cohort.

All numbers are in [`model_parameters.json`](model_parameters.json). They were copied programmatically, at full
precision, from the frozen final parameter file (SHA-256
`c7b5340f8a58febf270b62a9fb0ca417334416c75013ed4635a09cb63e8b764c`); the file also records the internal
development identifier of the model and the SHA-256 of the frozen production pipeline.

The eGFR-history rules are those of the code that built the study cohorts. Applied to the raw laboratory records,
they reproduce the stored predictor values of all 48,189 development and temporal-validation patients exactly.

## Validation

- `tests/reference_cases.json`: 45 reference cases (low risk, just below and just above 5%, clearly above 5%,
  younger and older people, female, male and unknown sex, all 8 combinations of the medicine questions, improving,
  stable and declining eGFR, same-day results, the 730-day window and range limits, and 7 cases outside the
  intended population). The expected values come from the frozen production pipeline and the study's own cohort
  code, cross-checked with an independent base-R scorer.
- The calculator matches every reference case to within 1e-12 (largest observed difference 2.2e-16).
- End-to-end check, run locally because patient-level data cannot be shared: the complete raw eGFR record of each
  of the 33,377 development and 14,812 temporal-validation patients was passed to the calculator. Every estimate
  equalled the frozen study prediction (largest difference 3.3e-16), and the 5% classification was identical
  (temporal validation: 1,804 patients flagged, including 165 of the 375 with a sustained decline).

Run the tests from the repository root:

```bash
python -m pip install -r SPARK_public/requirements.txt
python -m unittest discover -s SPARK_public/tests -v
```

## Running locally

```bash
python -m pip install -r SPARK_public/requirements.txt
streamlit run SPARK_public/app.py
```

## Repository structure

```text
.streamlit/config.toml          light theme; Streamlit Community Cloud reads it from the repository root
SPARK_public/app.py             user interface (input collection and display only)
SPARK_public/score_model.py     input checks, eGFR-history derivation and scoring
SPARK_public/model_parameters.json
SPARK_public/requirements.txt
SPARK_public/tests/             reference cases, engine tests and user-interface tests
```

The repository and web-calculator addresses keep an earlier working name so that existing links continue to work.

## Privacy

The calculator does not save the information entered. Do not enter names or other identifying details. This
repository contains no patient-level data.

## Citation

Publication details will be added when available.

## Licence

A licence has not yet been specified.
