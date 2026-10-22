"""Step 2: run sql/prep.sql -> tables claims, claims_per_policy, policy (in data/mtpl.duckdb)

The large-claim threshold is the chosen percentile of individual claim amounts.
Claims above it are capped for modelling; the excess is spread back over the whole
portfolio as a loading in the pricing step.

    python src/prep.py
"""
from __future__ import annotations

import json

from common import ASSUMPTIONS as A
from common import OUT, SQL, band_sql, con


def main():
    c = con()
    thr = c.execute(
        f"SELECT quantile_cont(ClaimAmount, {A['large_claim_quantile']}) FROM raw_sev SEMI JOIN raw_freq USING (IDpol)"
    ).fetchone()[0]
    sql = SQL.joinpath("prep.sql").read_text().format(
        large_threshold=round(thr, 2), exposure_cap=A["exposure_cap"], claim_count_cap=A["claim_count_cap"],
        band_driv_age=band_sql("driv_age_band"), band_veh_age=band_sql("veh_age_band"),
        band_bm=band_sql("bm_band"), band_veh_power=band_sql("veh_power_band"),
        seed=A["seed"], test_permille=int(A["test_share"] * 1000))
    c.execute(sql)
    s = c.execute("""
        SELECT count(*), sum(exposure), sum(n_claims), sum(total_amount), sum(excess_amount),
               sum(n_large), count_if(split = 'test') / count(*)
        FROM policy""").fetchone()
    params = {"large_claim_threshold": round(thr, 2)}
    (OUT / "prep_params.json").write_text(json.dumps(params, indent=2))
    print(f"policy table: {s[0]:,} policies, {s[1]:,.0f} policy-years, {s[2]:,} claims, losses {s[3]:,.0f}")
    print(f"large-claim threshold {thr:,.0f} ({A['large_claim_quantile']:.1%} percentile): "
          f"{s[5]:,} large claims carry {s[4] / s[3]:.1%} of losses above the threshold")
    print(f"test share {s[6]:.1%}")


if __name__ == "__main__":
    main()
