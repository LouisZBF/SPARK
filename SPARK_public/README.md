# SPARK

**Stratified Primary-care Assessment of Risk for Kidney decline**

SPARK is a Streamlit-based research implementation of the locked, ACR-free
Primary prediction model. SPARK is the name of the application, not the name
of the prediction model.

The application estimates the predicted risk of sustained 30% or greater eGFR
decline within 3 years. It is intended to support research communication,
manuscript review, and sensitivity checking of monitoring-priority thresholds.

## Research-use disclaimer

This application is for research purposes only and should not replace clinical
judgement.

SPARK does not replace urinary albumin-to-creatinine ratio (ACR) testing or
KFRE-based kidney failure risk assessment. It is not a diagnostic, treatment,
referral, or deployment-ready clinical decision-support tool. The application
has not undergone prospective workflow evaluation. Local validation,
recalibration or threshold review, governance, and prospective evaluation
would be required before any clinical use.

Do not enter identifiable patient information. The application does not
require or include patient-level datasets, and the source data used to develop
and validate the model are not included in this repository.

## Installation

Python 3.10 or later is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate the environment with:

```powershell
.venv\Scripts\activate
```

## Local execution

From the repository root:

```bash
streamlit run app.py
```

Streamlit will print the local application address in the terminal.

## Deployment with Streamlit Community Cloud

1. Create a GitHub repository containing the files in this directory.
2. In Streamlit Community Cloud, select **Create app**.
3. Choose the GitHub repository and branch.
4. Set the entrypoint file to `app.py`.
5. Deploy the app. Community Cloud will install the single dependency listed
   in `requirements.txt`.

No secrets, external database, or patient-level data are required.

## Repository structure

The recommended public repository contains:

```text
.
├── app.py                   # Streamlit user interface and input collection
├── score_model.py           # Input validation, preprocessing, and scoring
├── model_parameters.json    # Locked all-sex Primary-model parameters
├── requirements.txt         # Minimal third-party runtime dependency
└── README.md                # Project and deployment documentation
```

The application has no image, CSS, database, or external data-file dependency.

## Model inputs

SPARK uses:

- age at the index date;
- sex recorded as female, male, or unknown/unspecified;
- current/index eGFR;
- 2-year mean pre-index eGFR;
- number of pre-index eGFR measurements in the 2-year lookback;
- relative eGFR change from the pre-index mean to the index value;
- annualised 2-year eGFR slope;
- prior-year ACE inhibitor or angiotensin receptor blocker exposure;
- prior-year diuretic exposure; and
- prior-year polypharmacy of five or more unique ATC components.

The default eGFR-test mode derives the eGFR-history inputs from the current
test and at least two previous tests. The advanced mode accepts already derived
model-ready inputs.

## Output

The application displays:

- predicted 3-year risk of sustained 30% or greater eGFR decline;
- the corresponding displayed risk band;
- whether the locked 5% monitoring-priority threshold is met; and
- a conservative research-use interpretation.

## Citation

Citation placeholder: **[Insert the final SPARK manuscript citation and DOI.]**

## Public application

Streamlit URL placeholder: **[Insert the public Streamlit Community Cloud URL.]**

## License

License placeholder: **[Select and add the approved public-release license.]**
