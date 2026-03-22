from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Literal, Dict

import pandas as pd
from dateutil.relativedelta import relativedelta


def _to_date(x) -> Optional[date]:
    if x is None or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and x.strip() == ""):
        return None
    if isinstance(x, date) and not hasattr(x, "hour"):
        return x
    if hasattr(x, "date"):
        return x.date()
    return pd.to_datetime(x).date()


def normalize_absence_df(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure columns and types are sane."""
    if df is None or len(df) == 0:
        return pd.DataFrame({"leave_date": pd.Series(dtype="datetime64[ns]"),
                             "return_date": pd.Series(dtype="datetime64[ns]")})

    out = df.copy()
    # column normalization
    cols = {c.lower().strip(): c for c in out.columns}
    if "leave_date" not in cols and "date you left the uk" in cols:
        out = out.rename(columns={cols["date you left the uk"]: "leave_date"})
    if "return_date" not in cols and "date yuo have returned" in cols:
        out = out.rename(columns={cols["date yuo have returned"]: "return_date"})

    if "leave_date" not in out.columns:
        # attempt first column
        out = out.rename(columns={out.columns[0]: "leave_date"})
    if "return_date" not in out.columns:
        # attempt second column if present
        if len(out.columns) >= 2:
            out = out.rename(columns={out.columns[1]: "return_date"})
        else:
            out["return_date"] = None

    out = out[["leave_date", "return_date"]].copy()

    out["leave_date"] = out["leave_date"].apply(_to_date)
    out["return_date"] = out["return_date"].apply(_to_date)

    # drop fully empty rows
    out = out[~(out["leave_date"].isna() & out["return_date"].isna())].copy()
    out = out.reset_index(drop=True)

    return out


def overlap_days(
    leave: date,
    ret: Optional[date],
    window_start: date,
    as_of: date,
) -> int:
    """
    Spreadsheet-style overlap:
      MAX(0, (MIN(IF(ret="",as_of,ret), as_of) - MAX(leave, window_start)) - 1)
    """
    if leave is None:
        return 0
    end = ret or as_of
    end = min(end, as_of)
    start = max(leave, window_start)
    delta = (end - start).days - 1
    return max(0, int(delta))


def compute_window_totals(df: pd.DataFrame, as_of: date) -> Dict[str, int]:
    df = normalize_absence_df(df)

    w5 = as_of + relativedelta(months=-60)
    w3 = as_of + relativedelta(months=-36)
    w1 = as_of + relativedelta(months=-12)

    last_5y = 0
    last_3y = 0
    last_1y = 0

    for _, row in df.iterrows():
        leave = row["leave_date"]
        ret = row["return_date"]
        if leave is None:
            continue
        last_5y += overlap_days(leave, ret, w5, as_of)
        last_3y += overlap_days(leave, ret, w3, as_of)
        last_1y += overlap_days(leave, ret, w1, as_of)

    return {
        "last_5y_days": int(last_5y),
        "last_3y_days": int(last_3y),
        "last_1y_days": int(last_1y),
    }


def is_settled_eligible(last_5y_days: int, max_5y: int) -> bool:
    return int(last_5y_days) < int(max_5y)


def is_citizenship_eligible(
    last_5y_days: int,
    last_1y_days: int,
    have_ilr: bool,
    max_5y: int,
    max_1y: int,
) -> bool:
    return (int(last_5y_days) < int(max_5y)) and (int(last_1y_days) < int(max_1y)) and bool(have_ilr)


def earliest_eligible_date(
    df: pd.DataFrame,
    as_of: date,
    kind: Literal["settled", "citizenship"],
    max_5y: int,
    max_1y: int = 0,
    ilr_required: bool = False,
    have_ilr: bool = True,
    horizon_days: int = 730,
) -> Optional[date]:
    """
    Brute-force search for the earliest date >= as_of where rules are satisfied,
    assuming no new future absences beyond what's in df.
    """
    df = normalize_absence_df(df)

    for i in range(0, horizon_days + 1):
        d = as_of + timedelta(days=i)
        totals = compute_window_totals(df, as_of=d)

        if kind == "settled":
            if is_settled_eligible(totals["last_5y_days"], max_5y):
                return d
        else:
            ok_ilr = have_ilr if ilr_required else True
            if is_citizenship_eligible(
                last_5y_days=totals["last_5y_days"],
                last_1y_days=totals["last_1y_days"],
                have_ilr=ok_ilr,
                max_5y=max_5y,
                max_1y=max_1y,
            ):
                return d

    return None
