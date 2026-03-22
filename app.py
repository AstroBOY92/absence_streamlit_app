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

st.set_page_config(
    page_title="UK Absence Eligibility Dashboard - per il Fratacchione Rompipalle!!",
    layout="wide",
)

st.title("UK Absence Eligibility Dashboard - FORZA NAPOLI E FORZA CAVESE!!")
st.caption(
    "A calculator-style dashboard based on the same overlap logic used in your spreadsheet (rolling windows). "
    "Not legal advice fratacchia."
)

# -----------------------
# Sidebar
# -----------------------
with st.sidebar:
    st.header("Inputs")
    uploaded = st.file_uploader(
        "Upload your absences file (.xlsx from the spreadsheet, or .csv)",
        type=["xlsx", "csv"],
    )

    as_of = st.date_input(
        "As-of date",
        value=date.today(),
        help="All rolling windows are calculated up to this date.",
    )

    st.subheader("Rules (editable)")

    # Settled
    settled_max_5y = st.number_input(
        "Settled status: max absence in last 5y (days)",
        value=913,
        min_value=0,
        step=1,
    )

    st.markdown("---")
    st.markdown("### Citizenship (standard + exception)")

    # Citizenship standard (5y)
    citizen_standard_max_5y = st.number_input(
        "Citizenship standard: max absence in last 5y (days)",
        value=450,
        min_value=0,
        step=1,
        help="Standard threshold. If you exceed this, you may still be possible under exception depending on 7y total.",
    )

    # Citizenship exception (7y)
    citizenship_exception_max_7y = st.number_input(
        "Citizenship exception: max absence in last 7y (days)",
        value=730,
        min_value=0,
        step=1,
        help="If 5y is above the standard limit, but 7y stays under this cap, you might justify an exception.",
    )

    # Citizenship (1y)
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

# -----------------------
# Load data
# -----------------------
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

# -----------------------
# Editable grid
# -----------------------
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

# -----------------------
# Calculations
# -----------------------
totals = compute_window_totals(calc_df, as_of=as_of)

# -----------------------
# Metrics (now includes 7y)
# -----------------------
m1, m2, m3, m4 = st.columns(4)
m1.metric("Absence in last 7 years (days)", int(totals.get("last_7y_days", 0)))
m2.metric("Absence in last 5 years (days)", int(totals["last_5y_days"]))
m3.metric("Absence in last 3 years (days)", int(totals["last_3y_days"]))
m4.metric("Absence in last 1 year (days)", int(totals["last_1y_days"]))

st.divider()

# -----------------------
# Eligibility logic
# -----------------------
ok_ilr = (have_ilr if ilr_required else True)

# Settled: still the simple 5y check
settled_ok = is_settled_eligible(totals["last_5y_days"], settled_max_5y)

# Citizenship: 3-state (standard / exception / not)
cit_standard_ok = (
    totals["last_5y_days"] <= int(citizen_standard_max_5y)
    and totals["last_1y_days"] <= int(citizen_max_1y)
    and ok_ilr
)

cit_exception_possible = (
    totals["last_5y_days"] > int(citizen_standard_max_5y)
    and totals.get("last_7y_days", 0) <= int(citizenship_exception_max_7y)
    and totals["last_1y_days"] <= int(citizen_max_1y)
    and ok_ilr
)

if cit_standard_ok:
    citizenship_status = "STANDARD_OK"
elif cit_exception_possible:
    citizenship_status = "EXCEPTION_POSSIBLE"
else:
    citizenship_status = "NOT_OK"

# -----------------------
# Earliest dates helpers
# -----------------------
def earliest_exception_date(
    df_in: pd.DataFrame,
    as_of_in: date,
    max_7y: int,
    max_1y: int,
    ok_ilr_flag: bool,
    horizon_days: int = 730,
):
    """Earliest date where exception route is 'possible' (7y + 1y + ILR), assuming no future absences."""
    if not ok_ilr_flag:
        return None

    for i in range(horizon_days + 1):
        d = (pd.Timestamp(as_of_in) + pd.Timedelta(days=i)).date()
        t = compute_window_totals(df_in, as_of=d)
        if int(t.get("last_7y_days", 0)) <= int(max_7y) and int(t["last_1y_days"]) <= int(max_1y):
            return d
    return None


# -----------------------
# Panels
# -----------------------
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

    if citizenship_status == "STANDARD_OK":
        st.success("✅ Eligible (standard rule).")
    elif citizenship_status == "EXCEPTION_POSSIBLE":
        st.warning("⚠️ Possible via exception route (you may need justification).")
        st.write(
            f"- Last 5y: **{int(totals['last_5y_days'])}** days (over standard limit **{int(citizen_standard_max_5y)}**)\n"
            f"- Last 7y: **{int(totals.get('last_7y_days', 0))}** days (within exception cap **{int(citizenship_exception_max_7y)}**)\n"
            f"- Last 1y: **{int(totals['last_1y_days'])}** days (must be ≤ **{int(citizen_max_1y)}**)"
        )
    else:
        st.error("❌ Not eligible yet.")

    if ilr_required and not have_ilr:
        st.info("Note: ILR/Settled/PR is required (per your toggle), but you indicated you don’t have it yet.")

    st.markdown("**Earliest dates (assuming no new absences):**")

    # Standard earliest date (uses existing helper: 5y+1y+ILR)
    ed_standard = earliest_eligible_date(
        df=calc_df,
        as_of=as_of,
        kind="citizenship",
        max_5y=int(citizen_standard_max_5y),
        max_1y=int(citizen_max_1y),
        ilr_required=ilr_required,
        have_ilr=ok_ilr,
    )
    if ed_standard is not None:
        st.write(f"- Standard eligibility date: **{ed_standard.isoformat()}**")
    else:
        st.write("- Standard eligibility date: not found within 2 years")

    # Exception earliest date (7y+1y+ILR)
    ed_exception = earliest_exception_date(
        df_in=calc_df,
        as_of_in=as_of,
        max_7y=int(citizenship_exception_max_7y),
        max_1y=int(citizen_max_1y),
        ok_ilr_flag=ok_ilr,
        horizon_days=730,
    )
    if ed_exception is not None:
        st.write(f"- Exception-possible date (7y + 1y): **{ed_exception.isoformat()}**")
    else:
        st.write("- Exception-possible date (7y + 1y): not found within 2 years")

st.divider()

# -----------------------
# Download / Export
# -----------------------
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
