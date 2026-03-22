import io
from datetime import date

import pandas as pd
import streamlit as st

from src.io_utils import load_absences_from_xlsx, load_absences_from_csv, to_csv_bytes
from src.calc import (
    normalize_absence_df,
    compute_window_totals,
    is_settled_eligible,
    earliest_eligible_date,
)

st.set_page_config(page_title="UK Absence Eligibility Dashboard", layout="wide")

st.title("UK Absence Eligibility Dashboard")
st.caption(
    "Calculator-style dashboard based on rolling-window absence overlap logic. "
    "Not legal advice."
)

# ----------------------------
# Sidebar inputs
# ----------------------------
with st.sidebar:
    st.header("Inputs")

    uploaded = st.file_uploader(
        "Upload your absences file (.xlsx from the spreadsheet, or .csv)",
        type=["xlsx", "csv"],
    )

    as_of = st.date_input(
        "As-of date",
        value=date.today(),
        help="Rolling windows are calculated up to this date.",
    )

    st.subheader("Rules (editable)")

    # Settled / ILR
    settled_max_5y = st.number_input(
        "Settled status: max absence in last 5y (days)",
        value=913,
        min_value=0,
        step=1,
    )

    # Citizenship (standard + exception framing)
    citizen_max_5y_standard = st.number_input(
        "Citizenship: standard max absence in last 5y (days)",
        value=450,
        min_value=0,
        step=1,
        help="Typical standard rule threshold (edit if needed).",
    )
    citizen_max_7y_exception = st.number_input(
        "Citizenship: exception max absence in last 7y (days)",
        value=730,
        min_value=0,
        step=1,
        help="If you exceed the 5y standard limit, this can indicate a potential exception route (justification needed).",
    )
    citizen_max_1y = st.number_input(
        "Citizenship: max absence in last 1y (days)",
        value=90,
        min_value=0,
        step=1,
    )

    ilr_required = st.checkbox("Citizenship requires ILR/Settled/PR already", value=True)
    have_ilr = st.checkbox(
        "I already have ILR/Settled/PR",
        value=False,
        disabled=not ilr_required,
    )

    st.subheader("What-if planned trip")
    include_planned = st.checkbox("Include a planned trip in the counters", value=False)
    planned_leave = st.date_input("Planned leave date", value=as_of, disabled=not include_planned)
    planned_return = st.date_input("Planned return date", value=as_of, disabled=not include_planned)

# ----------------------------
# Load input data
# ----------------------------
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

# ----------------------------
# Editable grid
# ----------------------------
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

# Planned trip row (optional)
planned_df = pd.DataFrame(columns=["leave_date", "return_date"])
if include_planned:
    planned_df = pd.DataFrame([{"leave_date": planned_leave, "return_date": planned_return}])
    planned_df = normalize_absence_df(planned_df)

calc_df = pd.concat([edited, planned_df], ignore_index=True)
calc_df = normalize_absence_df(calc_df)

# ----------------------------
# Calculations
# ----------------------------
totals = compute_window_totals(calc_df, as_of=as_of)

# KPIs
c1, c2, c3, c4 = st.columns(4)
c1.metric("Absence in last 7 years (days)", int(totals.get("last_7y_days", 0)))
c2.metric("Absence in last 5 years (days)", int(totals["last_5y_days"]))
c3.metric("Absence in last 3 years (days)", int(totals["last_3y_days"]))
c4.metric("Absence in last 1 year (days)", int(totals["last_1y_days"]))

st.divider()

# ----------------------------
# Eligibility logic
# ----------------------------
ok_ilr = (have_ilr if ilr_required else True)

# Settled: keep simple (5y threshold)
settled_ok = is_settled_eligible(totals["last_5y_days"], settled_max_5y)

# Citizenship: 3-state outcome
standard_ok = (
    totals["last_5y_days"] <= citizen_max_5y_standard
    and totals["last_1y_days"] <= citizen_max_1y
    and ok_ilr
)

exception_possible = (
    totals["last_5y_days"] > citizen_max_5y_standard
    and totals.get("last_7y_days", 0) <= citizen_max_7y_exception
    and totals["last_1y_days"] <= citizen_max_1y
    and ok_ilr
)

if standard_ok:
    citizenship_status = "ELIGIBLE_STANDARD"
elif exception_possible:
    citizenship_status = "POSSIBLE_EXCEPTION"
else:
    citizenship_status = "NOT_ELIGIBLE"

# ----------------------------
# Panels
# ----------------------------
left, right = st.columns(2)

with left:
    st.subheader("Settled status")

    if settled_ok:
        st.success("✅ Eligible (based on your 5-year threshold).")
    else:
        st.error("❌ Not eligible yet (based on your 5-year threshold).")
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

    if citizenship_status == "ELIGIBLE_STANDARD":
        st.success("✅ Eligible (standard rule).")
    elif citizenship_status == "POSSIBLE_EXCEPTION":
        st.warning("⚠️ Potentially eligible via exception route (justification likely needed).")
        st.write(
            f"- Last 5y: **{int(totals['last_5y_days'])}** days (over standard limit **{int(citizen_max_5y_standard)}**)\n"
            f"- Last 7y: **{int(totals.get('last_7y_days', 0))}** days (within exception cap **{int(citizen_max_7y_exception)}**)\n"
            f"- Last 1y: **{int(totals['last_1y_days'])}** days (must be ≤ **{int(citizen_max_1y)}**)"
        )
    else:
        st.error("❌ Not eligible yet.")

    if ilr_required and not have_ilr:
        st.info("Note: you ticked that ILR/Settled/PR is required, but you also indicated you don’t have it yet.")

    # Earliest dates for citizenship (standard + exception)
    st.markdown("**Earliest dates (assuming no new absences):**")

    # Standard eligibility date
    ed_standard = earliest_eligible_date(
        df=calc_df,
        as_of=as_of,
        kind="citizenship",
        max_5y=int(citizen_max_5y_standard),
        max_1y=int(citizen_max_1y),
        ilr_required=ilr_required,
        have_ilr=ok_ilr,
    )
    if ed_standard is not None:
        st.write(f"- Standard eligibility date: **{ed_standard.isoformat()}**")
    else:
        st.write("- Standard eligibility date: not found within 2 years")

    # Exception-possible date:
    # We reuse earliest_eligible_date() by treating the exception condition as:
    #   7y <= citizen_max_7y_exception AND 1y <= citizen_max_1y
    # but earliest_eligible_date currently only checks 5y+1y.
    #
    # So here we do a small local brute-force loop with compute_window_totals.
    def earliest_exception_date():
        if not ok_ilr:
            return None
        horizon_days = 730
        for i in range(horizon_days + 1):
            d = as_of + pd.Timedelta(days=i)
            d = d.date()
            t = compute_window_totals(calc_df, as_of=d)
            if (t.get("last_7y_days", 0) <= citizen_max_7y_exception) and (t["last_1y_days"] <= citizen_max_1y):
                # Only meaningful when 5y is above standard OR you still want to show it anyway.
                # We'll return the first date where exception route is "possible".
                return d
        return None

    ed_exception = earliest_exception_date()
    if ed_exception is not None:
        st.write(f"- Exception-possible date (7y+1y): **{ed_exception.isoformat()}**")
    else:
        st.write("- Exception-possible date (7y+1y): not found within 2 years")

st.divider()

# ----------------------------
# Download / Export
# ----------------------------
st.subheader("Download / Export")
d1, d2 = st.columns(2)
with d1:
    st.download_button(
        "Download current absences as CSV",
        data=to_csv_bytes(edited),
        file_name="absences.csv",
        mime="text/csv",
        use_container_width=True,
    )
with d2:
    st.download_button(
        "Download absences + planned trip as CSV",
        data=to_csv_bytes(calc_df),
        file_name="absences_with_planned.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.divider()

st.subheader("How the day-count works")
st.write(
    """
- Each absence contributes **(return_date - leave_date - 1)** days (excludes boundary days), matching your spreadsheet logic.
- Rolling window overlap is computed per absence against the window **[as_of - window, as_of]** with the same boundary rule.
"""
)