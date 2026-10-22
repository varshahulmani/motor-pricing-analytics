"""Paths, assumptions and helpers shared by every step.

Every judgement call that changes the numbers lives in ASSUMPTIONS so it is stated
once and printed into the reports.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = Path(os.environ.get("MTPL_RAW", DATA / "raw"))
DB = Path(os.environ.get("MTPL_DB", DATA / "mtpl.duckdb"))
SQL = ROOT / "sql"
OUT = ROOT / "outputs"
REPORTS = ROOT / "reports"
TABLEAU = ROOT / "tableau" / "data"
for d in (DATA, RAW, OUT, REPORTS, TABLEAU):
    d.mkdir(parents=True, exist_ok=True)

ASSUMPTIONS = {
    # cleaning
    "claim_count_cap": 4,              # policies with more than 4 claims are treated as 4
    "exposure_cap": 1.0,               # exposure above 1 year is a data error; cap at 1
    "large_claim_quantile": 0.995,     # individual claims above this percentile are 'large'
    # pricing
    "permissible_loss_ratio": 0.70,    # gross premium = risk premium / 0.70 (expenses + profit)
    "tariff_factors": ["bm_band", "driv_age_band", "area"],  # the assumed current tariff
    "tariff_method": os.environ.get("MTPL_TARIFF", "glm"),   # 'glm' (multivariate) or 'oneway' (naive)
    "mispricing_threshold": 0.10,      # |model / tariff - 1| above this = mispriced
    "min_segment_exposure": 500,       # policy-years; smaller segments are not judged
    "segment_factors": ["driv_age_band", "bm_band", "veh_age_band", "veh_gas"],
    # validation split
    "test_share": 0.2,                 # deterministic by hash(IDpol)
    "seed": 42,
}

# factor bands, as SQL CASE expressions (also used to label levels in a sensible order)
BANDS = {
    "driv_age_band": ("DrivAge", [(20, "18-20"), (25, "21-25"), (30, "26-30"), (40, "31-40"),
                                  (50, "41-50"), (60, "51-60"), (70, "61-70"), (None, "71+")]),
    "veh_age_band": ("VehAge", [(0, "0"), (2, "1-2"), (5, "3-5"), (10, "6-10"), (15, "11-15"), (None, "16+")]),
    "bm_band": ("BonusMalus", [(50, "50"), (60, "51-60"), (80, "61-80"), (100, "81-100"), (None, "101+")]),
    "veh_power_band": ("VehPower", [(4, "4"), (5, "5"), (6, "6"), (7, "7"), (8, "8"), (None, "9+")]),
}


def band_sql(name: str) -> str:
    col, cuts = BANDS[name]
    parts = [f"WHEN {col} <= {hi} THEN '{lab}'" for hi, lab in cuts if hi is not None]
    return f"CASE {' '.join(parts)} ELSE '{cuts[-1][1]}' END AS {name}"


def band_order(name: str) -> list[str]:
    return [lab for _, lab in BANDS[name][1]]


def con(read_only=False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(DB.as_posix(), read_only=read_only)


def lorenz_gini(y_true, y_pred, exposure):
    """Exposure-weighted Lorenz curve: policies ordered from lowest to highest predicted risk.

    Returns (cum_exposure_share, cum_claim_share, gini). Gini = 1 - 2 * area under the curve;
    higher means the model separates good and bad risks better. Same definition as the
    scikit-learn insurance examples.
    """
    order = np.argsort(y_pred, kind="mergesort")
    w = np.asarray(exposure)[order]
    yt = np.asarray(y_true)[order] * w  # y_true is a rate, so * exposure gives claims/losses
    x = np.concatenate([[0], np.cumsum(w) / w.sum()])
    y = np.concatenate([[0], np.cumsum(yt) / yt.sum()])
    auc = np.trapezoid(y, x) if hasattr(np, "trapezoid") else np.trapz(y, x)
    return x, y, 1 - 2 * auc


def weighted_poisson_deviance(y, mu, w):
    y, mu, w = map(np.asarray, (y, mu, w))
    mu = np.clip(mu, 1e-12, None)
    term = np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / mu), 0.0)
    return float(np.sum(w * 2 * (term - (y - mu))) / np.sum(w))


def weighted_gamma_deviance(y, mu, w):
    y, mu, w = map(np.asarray, (y, mu, w))
    return float(np.sum(w * 2 * (-np.log(y / mu) + (y - mu) / mu)) / np.sum(w))


def md_table(df, fmt: dict | None = None) -> list[str]:
    fmt = fmt or {}
    lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    for row in df.itertuples(index=False):
        cells = []
        for col, v in zip(df.columns, row):
            f = fmt.get(col)
            cells.append(f.format(v) if f and v == v else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return lines
