import io
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from src.io_utils import load_absences_from_xlsx, load_absences_from_csv, to_csv_bytes
from src.calc import (
    normalize_absence_df,
    compute_window_totals,
    is_settled_eligible,
    is_citizenship_eligible,
    earliest_eligible_date,
)

st.set_page_config(page_title="UK Absence Eligibility Dashboard", layout="wide")

st.title("UK Absence Eligibility Dashboard")
st.caption("A calculator-style dashboard based on the same overlap logic used in your spreadsheet (rolling windows). Not legal advice.")

with st.sidebar:
    st.header("Inputs")
    uploaded = st.file_uploader("Upload your absences file (.xlsx from the spreadsheet, or .csv)", type=["xlsx", "csv"])

    as_of = st.date_input("As-of date", value=date.today(), help="All rolling windows are calculated up to this date (inclusive end, spreadsheet-style).")

    st.subheader("Rules (editable)")
    settled_max_5y = st.number_input("Settled status: max absence in last 5y (days)", value=913, min_value=0, step=1)
    citizen_max_5y = st.number_input("Citizenship: max absence in last 5y (days)", value=540, min_value=0, step=1)
    citizen_max_1y = st.number_input("Citizenship: max absence in last 1y (days)", value=90, min_value=0, step=1)
    ilr_required = st.checkbox("Citizenship requires ILR/Settled/PR already", value=True)
    have_ilr = st.checkbox("I already have ILR/Settled/PR", value=False, disabled=not ilr_required)

    st.subheader("What-if planned trip")
    include_planned = st.checkbox("Include a planned trip in the counters", value=False)
    planned_leave = st.date_input("Planned leave date", value=as_of, disabled=not include_planned)
    planned_return = st.date_input("Planned return date", value=as_of, disabled=not include_planned)

# ---- Load data
df = None
source_note = None
if uploaded is not None:
    if uploaded.name.lower().endswith(".xlsx"):
        df = load_absences_from_xlsx(uploaded)
        source_note = f"Loaded {len(df)} rows from XLSX: {uploaded.name}"
    else:
        df = load_absences_from_csv(uploaded)
        source_note = f"Loaded {len(df)} rows from CSV: {uploaded.name}"
else:
    df = pd.DataFrame({"leave_date": [], "return_date": []})
    source_note = "No file uploaded — start with an empty table or upload your spreadsheet."

st.info(source_note)

df = normalize_absence_df(df)

# Editable grid
st.subheader("Absence list")
st.write("Edit your absences here. Leave **return_date** blank if you are still away.")
edited = st.data_editor(
    df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "leave_date": st.column_config.DateColumn("leave_date", required=True),
        "return_date": st.column_config.DateColumn("return_date", required=False),
    },
    key="editor",
)
edited = normalize_absence_df(edited)

# Planned trip row
planned_df = pd.DataFrame(columns=["leave_date", "return_date"])
if include_planned:
    planned_df = pd.DataFrame([{"leave_date": planned_leave, "return_date": planned_return}])
    planned_df = normalize_absence_df(planned_df)

calc_df = pd.concat([edited, planned_df], ignore_index=True)
calc_df = normalize_absence_df(calc_df)

# ---- Calculations
totals = compute_window_totals(calc_df, as_of=as_of)

settled_ok = is_settled_eligible(totals["last_5y_days"], settled_max_5y)
citizen_ok = is_citizenship_eligible(
    last_5y_days=totals["last_5y_days"],
    last_1y_days=totals["last_1y_days"],
    have_ilr=(have_ilr if ilr_required else True),
    max_5y=citizen_max_5y,
    max_1y=citizen_max_1y,
)

col1, col2, col3 = st.columns(3)
col1.metric("Absence in last 5 years (days)", int(totals["last_5y_days"]))
col2.metric("Absence in last 3 years (days)", int(totals["last_3y_days"]))
col3.metric("Absence in last 1 year (days)", int(totals["last_1y_days"]))

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("Settled status")
    if settled_ok:
        st.success("✅ Eligible (based on your thresholds).")
    else:
        st.error("❌ Not eligible yet (based on your thresholds).")
        ed = earliest_eligible_date(
            df=calc_df,
            as_of=as_of,
            kind="settled",
            max_5y=settled_max_5y,
        )
        if ed is not None:
            st.write(f"Earliest date that meets the rule (assuming no new absences): **{ed.isoformat()}**")
        else:
            st.write("Couldn't find an eligible date within the search horizon (2 years).")

with right:
    st.subheader("Citizenship")
    if citizen_ok:
        st.success("✅ Eligible (based on your thresholds and ILR flag).")
    else:
        st.error("❌ Not eligible yet (based on your thresholds and ILR flag).")
        ed = earliest_eligible_date(
            df=calc_df,
            as_of=as_of,
            kind="citizenship",
            max_5y=citizen_max_5y,
            max_1y=citizen_max_1y,
            ilr_required=ilr_required,
            have_ilr=(have_ilr if ilr_required else True),
        )
        if ed is not None:
            st.write(f"Earliest date that meets the rule (assuming no new absences): **{ed.isoformat()}**")
        else:
            st.write("Couldn't find an eligible date within the search horizon (2 years).")

st.divider()

st.subheader("Download / Export")
c1, c2 = st.columns(2)
with c1:
    st.download_button(
        "Download current absences as CSV",
        data=to_csv_bytes(edited),
        file_name="absences.csv",
        mime="text/csv",
        use_container_width=True,
    )
with c2:
    st.download_button(
        "Download absences + planned trip as CSV",
        data=to_csv_bytes(calc_df),
        file_name="absences_with_planned.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.divider()
st.subheader("How the day-count works (matches spreadsheet logic)")
st.write(
    """
- Each absence contributes **(return_date - leave_date - 1)** days (i.e., excludes departure/return boundary days),
  matching the spreadsheet formulas.
- Rolling window overlap is computed per absence against **[as_of - window, as_of]** using the same `-1` boundary rule.
"""
)

