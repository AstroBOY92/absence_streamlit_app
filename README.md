# UK Absence Eligibility Dashboard (Streamlit)

This app reproduces the rolling-window absence counters from your Excel workbook and makes them interactive:
- Pick an **as-of** date (simulate eligibility on any date)
- Edit absences in an interactive table
- Add a **what-if planned trip**
- See rolling totals for **last 5y / 3y / 1y**
- Get an **earliest eligible date** estimate (assuming no new future absences)

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

## Data input

Upload either:
- The original `.xlsx` workbook (it reads sheet **Counter Sheet**, columns A and B), or
- A `.csv` with columns `leave_date,return_date` (return_date can be blank)

## Notes

- Day-count logic matches the spreadsheet: each absence contributes `(return - leave - 1)` days.
- This is a calculator-style tool and **not legal advice**.
