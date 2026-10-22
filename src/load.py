"""Step 1: load freMTPL2freq (policies) and freMTPL2sev (claim amounts) into DuckDB.

Source, in order of preference:
  1. CSVs already in data/raw (freMTPL2freq.csv, freMTPL2sev.csv), e.g. from a previous run
  2. OpenML via scikit-learn: data_id 41214 (frequency) and 41215 (severity)
  3. the CASdatasets R package's .rda files on GitHub (same data; Region has full names
     instead of codes), read with the `rdata` package

Raw tables are stored as delivered (apart from type fixes) so the validation step can
reconcile every report number back to them.

    python src/load.py
"""
from __future__ import annotations

import pandas as pd

from common import RAW, con

FREQ_CSV, SEV_CSV = RAW / "freMTPL2freq.csv", RAW / "freMTPL2sev.csv"


def fetch():
    if FREQ_CSV.exists() and SEV_CSV.exists():
        print(f"reading CSVs from {RAW}")
        return pd.read_csv(FREQ_CSV), pd.read_csv(SEV_CSV)
    try:
        from sklearn.datasets import fetch_openml
        print("downloading from OpenML (data_id 41214 and 41215) ...")
        freq = fetch_openml(data_id=41214, as_frame=True, parser="auto").frame
        sev = fetch_openml(data_id=41215, as_frame=True, parser="auto").frame
    except Exception as e:
        print(f"OpenML failed ({str(e)[:80]}); trying CASdatasets on GitHub ...")
        freq, sev = fetch_casdatasets()
    freq.to_csv(FREQ_CSV, index=False)
    sev.to_csv(SEV_CSV, index=False)
    return freq, sev


def fetch_casdatasets():
    import urllib.request

    import rdata  # pip install rdata

    base = "https://raw.githubusercontent.com/dutangc/CASdatasets/master/data/"
    out = []
    for name in ("freMTPL2freq", "freMTPL2sev"):
        path = RAW / f"{name}.rda"
        if not path.exists():
            urllib.request.urlretrieve(base + f"{name}.rda", path)
        out.append(next(iter(rdata.read_rda(path).values())).reset_index(drop=True))
    return out


def tidy(df):
    df = df.copy()
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].astype(str).str.strip("'\" ")  # OpenML ARFF wraps strings in quotes
    df["IDpol"] = pd.to_numeric(df["IDpol"]).astype("int64")
    return df


def main():
    freq, sev = map(tidy, fetch())
    for col in ("ClaimNb", "VehPower", "VehAge", "DrivAge", "BonusMalus", "Density"):
        freq[col] = pd.to_numeric(freq[col]).astype("int64")
    freq["Exposure"] = pd.to_numeric(freq["Exposure"]).astype(float)
    sev["ClaimAmount"] = pd.to_numeric(sev["ClaimAmount"]).astype(float)

    c = con()
    c.execute("CREATE OR REPLACE TABLE raw_freq AS SELECT * FROM freq")
    c.execute("CREATE OR REPLACE TABLE raw_sev AS SELECT row_number() OVER () AS claim_row, * FROM sev")
    nf, ns, amt = c.execute(
        "SELECT (SELECT count(*) FROM raw_freq), (SELECT count(*) FROM raw_sev), (SELECT sum(ClaimAmount) FROM raw_sev)"
    ).fetchone()
    print(f"raw_freq: {nf:,} policies | raw_sev: {ns:,} claims, total {amt:,.0f}")


if __name__ == "__main__":
    main()
